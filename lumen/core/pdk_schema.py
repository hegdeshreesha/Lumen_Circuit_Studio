"""
NovaCad / Lumen Circuit Studio — PDK Schema & Discovery Engine

Professional-grade PDK (Process Design Kit) management system.
Replaces hardcoded PDK data with a JSON-schema-driven system that:
- Discovers PDKs on the filesystem via standard paths
- Auto-resolves SPICE model files (.lib, .model, .va)
- Generates device catalogs from model files
- Provides constraint validation (min W/L, voltage limits, etc.)
- Supports multi-PDK projects
- Maintains layer maps for GDSII compatibility
"""
import json
import os
import re
import fnmatch
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Callable
from enum import Enum


# ── Constants ──────────────────────────────────────────────────

PDK_SCHEMA_VERSION = "1.0"
def _get_discovery_paths() -> list[str]:
    """Get filesystem paths to scan for PDKs, excluding empty entries."""
    paths = []
    for var in ["PDK_ROOT", "PDK_DIR"]:
        val = os.environ.get(var, "")
        if val:
            paths.append(val)
    paths.extend([
        os.path.join(os.path.expanduser("~"), ".pdk"),
        os.path.join(os.path.expanduser("~"), "pdk"),
        "C:\\EDA",
    ])
    return paths

PDK_DISCOVERY_PATHS = _get_discovery_paths()

# File patterns to scan for inside PDK directories
MODEL_FILE_PATTERNS = [
    "*.lib", "*.model", "*.va", "*.vams",
    "*.spice", "*.sp", "*.cdl",
    "models/*.lib", "models/*.model",
    "models/*.va", "models/*.spice",
    "corners/*.lib", "corners/*.model",
]

# Standard PDK directory markers
PDK_IDENTIFIER_FILES = [
    ".pdk_root", "pdk.json", "pdk.yaml",
    "manifest.json", "layers.json", "devices.json",
    ".techfile", "tech.json",
]


# ── Schema Data Classes ────────────────────────────────────────

class DeviceCategory(Enum):
    MOS = "MOSFET"
    RESISTOR = "Resistor"
    CAPACITOR = "Capacitor"
    INDUCTOR = "Inductor"
    DIODE = "Diode"
    BJT = "BJT"
    SOURCE = "Source"
    SWITCH = "Switch"
    OTHER = "Other"


class PinDirection(Enum):
    INPUT = "input"
    OUTPUT = "output"
    INOUT = "inout"
    POWER = "power"
    GROUND = "ground"


@dataclass
class PDKConstraint:
    """Design rule constraint for a device."""
    param: str          # e.g., "W", "L", "Vgs_max"
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    unit: str = ""
    description: str = ""


@dataclass
class PDKPin:
    """A device pin definition."""
    name: str
    direction: PinDirection = PinDirection.INOUT
    x: float = 0.0
    y: float = 0.0
    description: str = ""


@dataclass
class PDKParameter:
    """A parameter (property) for a device."""
    name: str
    default: str = ""
    description: str = ""
    unit: str = ""
    display_name: str = ""


@dataclass
class PDKDevice:
    """A device available in a PDK."""
    name: str
    category: DeviceCategory = DeviceCategory.OTHER
    prefix: str = "X"                    # SPICE prefix: M, R, C, Q, D, etc.
    model: str = ""                      # SPICE model name
    description: str = ""
    pins: list[PDKPin] = field(default_factory=list)
    parameters: list[PDKParameter] = field(default_factory=list)
    constraints: list[PDKConstraint] = field(default_factory=list)
    symbol_style: str = "default"        # Which symbol template to use
    symbol_pin_map: dict[str, str] = field(default_factory=dict)  # pin_name -> symbol_label
    is_primitive: bool = False
    priority: int = 0                    # Higher = prefer in catalogs


@dataclass
class PDKLayer:
    """A layer in the technology stack (GDSII compatible)."""
    name: str
    gds_number: int = 0
    gds_datatype: int = 0
    purpose: str = "drawing"
    color: str = "#808080"
    fill_pattern: str = "solid"
    description: str = ""
    min_width: Optional[float] = None
    min_spacing: Optional[float] = None


@dataclass
class PDKCorner:
    """A process corner definition."""
    name: str
    description: str = ""
    temperature: float = 25.0
    lib_section: str = ""                # The .LIB section name in model files
    model_kwargs: dict = field(default_factory=dict)


@dataclass
class PDKModelFile:
    """A discovered SPICE model file."""
    path: str
    relative_path: str = ""
    format: str = "spice"               # spice, veriloga, etc.
    corners: list[str] = field(default_factory=list)
    size_bytes: int = 0
    last_modified: float = 0.0


@dataclass
class PDKSymbolTemplate:
    """A symbol template for device visualization."""
    name: str
    shapes: list[dict] = field(default_factory=list)  # QPainterPath-like
    pin_style: str = "dot"
    body_color: str = "#e94560"
    pin_color: str = "#ffd60a"
    label_position: dict = field(default_factory=lambda: {"x": 15, "y": -25})


@dataclass
class PDKInfo:
    """Complete PDK definition — the master schema."""
    # Identity
    name: str
    display_name: str = ""
    foundry: str = ""
    process: str = ""
    node: str = ""                       # e.g., "130nm", "180nm", "28nm"
    version: str = "1.0"
    schema_version: str = PDK_SCHEMA_VERSION
    description: str = ""
    license: str = ""

    # Paths
    root_path: str = ""                  # PDK installation root
    models_path: str = ""                # Path to model files
    tech_path: str = ""                  # Path to tech files
    cells_path: str = ""                 # Path to parameterized cells

    # Content
    supply_voltage: float = 1.8
    temperature_range: tuple = (-40, 125)
    corners: list[PDKCorner] = field(default_factory=list)
    devices: list[PDKDevice] = field(default_factory=list)
    layers: list[PDKLayer] = field(default_factory=list)
    model_files: list[PDKModelFile] = field(default_factory=list)
    symbol_templates: list[PDKSymbolTemplate] = field(default_factory=list)

    # Status
    installed: bool = False
    is_builtin: bool = False

    # Metadata
    tags: list[str] = field(default_factory=list)
    url: str = ""
    author: str = ""


# ── Model File Parser ──────────────────────────────────────────

class SpiceModelParser:
    """
    Parses SPICE model library files to extract available devices.
    Handles:
    - .MODEL statements (MOSFET, BJT, Diode, etc.)
    - .SUBCKT definitions (subcircuit-based devices)
    - .LIB sections (corner-specific models)
    - .INCLUDE references
    """

    # SPICE model type -> category mapping
    MODEL_TYPE_MAP = {
        "NMOS": DeviceCategory.MOS,
        "PMOS": DeviceCategory.MOS,
        "NJF": DeviceCategory.MOS,    # JFET N-channel
        "PJF": DeviceCategory.MOS,    # JFET P-channel
        "NPN": DeviceCategory.BJT,
        "PNP": DeviceCategory.BJT,
        "D": DeviceCategory.DIODE,
        "DIO": DeviceCategory.DIODE,
        "RES": DeviceCategory.RESISTOR,
        "CAP": DeviceCategory.CAPACITOR,
        "IND": DeviceCategory.INDUCTOR,
        "CORE": DeviceCategory.OTHER,  # Transformer/inductor
        "SW": DeviceCategory.SWITCH,
        "VSWITCH": DeviceCategory.SWITCH,
        "ISWITCH": DeviceCategory.SWITCH,
    }

    # Default pin mappings for known model types
    DEFAULT_PINS = {
        DeviceCategory.MOS: [PDKPin("D", PinDirection.INOUT, 20, -30),
                             PDKPin("G", PinDirection.INPUT, -20, 0),
                             PDKPin("S", PinDirection.INOUT, 20, 30),
                             PDKPin("B", PinDirection.INOUT, 40, 0)],
        DeviceCategory.BJT: [PDKPin("C", PinDirection.INOUT, 15, -30),
                             PDKPin("B", PinDirection.INPUT, -30, 0),
                             PDKPin("E", PinDirection.INOUT, 15, 30)],
        DeviceCategory.DIODE: [PDKPin("PLUS", PinDirection.INPUT, 0, -30),
                               PDKPin("MINUS", PinDirection.OUTPUT, 0, 30)],
        DeviceCategory.RESISTOR: [PDKPin("PLUS", PinDirection.INPUT, 0, -30),
                                  PDKPin("MINUS", PinDirection.OUTPUT, 0, 30)],
        DeviceCategory.CAPACITOR: [PDKPin("PLUS", PinDirection.INPUT, 0, -30),
                                   PDKPin("MINUS", PinDirection.OUTPUT, 0, 30)],
    }

    DEFAULT_PARAMS = {
        DeviceCategory.MOS: [
            PDKParameter("W", "1u", "Width", "m", "Width"),
            PDKParameter("L", "100n", "Length", "m", "Length"),
            PDKParameter("nf", "1", "Number of Fingers", "", "Fingers"),
            PDKParameter("mult", "1", "Multiplier", "", "Multiplier"),
        ],
        DeviceCategory.RESISTOR: [
            PDKParameter("R", "1k", "Resistance", "ohm", "Resistance"),
            PDKParameter("W", "1u", "Width", "m", "Width"),
            PDKParameter("L", "1u", "Length", "m", "Length"),
        ],
        DeviceCategory.CAPACITOR: [
            PDKParameter("C", "1p", "Capacitance", "F", "Capacitance"),
            PDKParameter("W", "5u", "Width", "m", "Width"),
            PDKParameter("L", "5u", "Length", "m", "Length"),
        ],
        DeviceCategory.DIODE: [
            PDKParameter("area", "1", "Area multiplier", "", "Area"),
        ],
        DeviceCategory.BJT: [
            PDKParameter("mult", "1", "Multiplier", "", "Multiplier"),
            PDKParameter("area", "1", "Area multiplier", "", "Area"),
        ],
    }

    # Default SPICE prefixes
    PREFIX_MAP = {
        DeviceCategory.MOS: "M",
        DeviceCategory.BJT: "Q",
        DeviceCategory.DIODE: "D",
        DeviceCategory.RESISTOR: "R",
        DeviceCategory.CAPACITOR: "C",
        DeviceCategory.INDUCTOR: "L",
        DeviceCategory.SOURCE: "V",
    }

    def __init__(self):
        self._devices: list[PDKDevice] = []
        self._subckts: dict[str, dict] = {}
        self._current_lib_section: str = ""

    def parse_file(self, filepath: str) -> list[PDKDevice]:
        """
        Parse a SPICE model file and extract device definitions.

        Returns:
            List of PDKDevice objects found in the file.
        """
        self._devices = []
        self._subckts = {}
        self._current_lib_section = ""

        if not os.path.isfile(filepath):
            return []

        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            return []

        # Remove comments
        content = self._strip_comments(content)

        # Parse sections
        lines = content.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            up = line.upper()

            if up.startswith(".SUBCKT") or up.startswith(".SUBCKT"):
                sub_lines, i = self._extract_block(lines, i)
                self._parse_subckt(sub_lines)
            elif up.startswith(".LIB"):
                lib_match = re.match(r'\.LIB\s+"?([^"\s]+)"?\s+(\w+)', line)
                if lib_match:
                    self._current_lib_section = lib_match.group(2)
                i += 1
            elif up.startswith(".MODEL") or up.startswith(".MODEL"):
                self._parse_model(line)
                i += 1
            elif up.startswith(".ENDS"):
                self._current_lib_section = ""
                i += 1
            else:
                i += 1

        return self._devices

    def _strip_comments(self, content: str) -> str:
        """Remove SPICE comments while preserving strings."""
        lines = content.split("\n")
        cleaned = []
        for line in lines:
            # Remove inline comments (text after ; or *)
            # But be careful not to remove * in strings
            stripped = line.strip()
            if stripped.startswith("*") and not stripped.startswith(".model"):
                continue
            # Remove trailing comments
            if ";" in line:
                # Simple heuristic — remove after semicolon
                line = line.split(";")[0]
            cleaned.append(line)
        return "\n".join(cleaned)

    def _extract_block(self, lines: list[str], start: int) -> tuple[list[str], int]:
        """Extract a .SUBCKT or .MODEL block until .ENDS or end."""
        block = [lines[start]]
        i = start + 1
        depth = 1
        while i < len(lines) and depth > 0:
            line = lines[i]
            up = line.strip().upper()
            if up.startswith(".SUBCKT"):
                depth += 1
            elif up.startswith(".ENDS"):
                depth -= 1
            if depth > 0:
                block.append(line)
            i += 1
        return block, i

    def _parse_model(self, line: str):
        """
        Parse a .MODEL statement.
        .MODEL model_name type (param1=val1 param2=val2 ...)
        Example: .MODEL nch NMOS (VTO=0.7 KP=200e-6)
        """
        # Match: .MODEL model_name type (params)
        match = re.match(
            r'\.MODEL\s+(\S+)\s+(\S+)(?:\s*\(([^)]*)\))?',
            line, re.IGNORECASE
        )
        if not match:
            return

        model_name = match.group(1)
        model_type = match.group(2).upper()
        params_str = match.group(3) or ""

        # Determine category
        category = self.MODEL_TYPE_MAP.get(model_type, DeviceCategory.OTHER)

        # Determine if NMOS or PMOS for prefix
        prefix = self.PREFIX_MAP.get(category, "X")
        if category == DeviceCategory.MOS:
            if model_type == "NMOS":
                prefix = "M"
            elif model_type == "PMOS":
                prefix = "M"

        # Get default pins
        pins = self.DEFAULT_PINS.get(category, []).copy()

        # Get default parameters
        params = self.DEFAULT_PARAMS.get(category, []).copy()

        # Extract known parameters from the model line
        param_vals = self._extract_params(params_str)
        for param in params:
            if param.name in param_vals:
                param.default = param_vals[param.name]

        description = f"{model_type} model {model_name}"

        device = PDKDevice(
            name=model_name,
            category=category,
            prefix=prefix,
            model=model_name,
            description=description,
            pins=pins,
            parameters=params,
            symbol_style=category.name.lower(),
            is_primitive=False,
            priority=10 if category != DeviceCategory.OTHER else 0,
        )

        # Add constraints based on category
        if category == DeviceCategory.MOS:
            device.constraints = [
                PDKConstraint("W", min_value=0.1e-6, max_value=1e-3, unit="m",
                              description="Transistor width"),
                PDKConstraint("L", min_value=0.05e-6, max_value=0.1e-3, unit="m",
                              description="Transistor length"),
            ]

        self._devices.append(device)

    def _parse_subckt(self, lines: list[str]):
        """
        Parse a .SUBCKT definition.
        .SUBCKT name pin1 pin2 ... [params]
        """
        first = lines[0].strip()
        match = re.match(r'\.SUBCKT\s+(\S+)\s+(.*)', first, re.IGNORECASE)
        if not match:
            return

        sub_name = match.group(1)
        rest = match.group(2).strip()

        # Extract parameters (after ? or PARAMS:)
        pins_part = rest
        params_part = ""

        if "?" in rest:
            parts = rest.split("?")
            pins_part = parts[0].strip()
            params_part = parts[1].strip() if len(parts) > 1 else ""
        elif "PARAMS:" in rest.upper():
            parts = rest.upper().split("PARAMS:")
            pins_part = parts[0].strip()
            params_part = rest[len("PARAMS:") + len(parts[0]) + 1:].strip() if len(parts) > 1 else ""

        # Extract pin names
        pin_names = pins_part.split()
        pins = []
        for i, pname in enumerate(pin_names):
            y_offset = -20 + i * 15
            pins.append(PDKPin(pname, PinDirection.INOUT, 20, y_offset))

        # Extract parameters
        params = []
        if params_part:
            param_list = params_part.split()
            for p in param_list:
                p = p.strip(" {}=")
                if "=" in p:
                    name, _, default = p.partition("=")
                    params.append(PDKParameter(name.strip(), default.strip()))

        # Guess category from content
        category = DeviceCategory.OTHER
        # Look for MOSFET/BJT/diode models inside subcircuit
        for line in lines:
            up = line.strip().upper()
            for model_type in ["NMOS", "PMOS", "NPN", "PNP", "D "] + ["DIO"]:
                if model_type in up:
                    mt = model_type.strip()
                    cat = self.MODEL_TYPE_MAP.get(mt if mt != "D " else "D", DeviceCategory.OTHER)
                    if cat != DeviceCategory.OTHER:
                        category = cat
                    break

        # Determine prefix
        prefix = "X"  # Subcircuits use X prefix
        if category == DeviceCategory.RESISTOR:
            prefix = "R"
        elif category == DeviceCategory.CAPACITOR:
            prefix = "C"
        elif category == DeviceCategory.DIODE:
            prefix = "D"

        device = PDKDevice(
            name=sub_name,
            category=category,
            prefix=prefix,
            model=sub_name,
            description=f"Subcircuit: {sub_name}",
            pins=pins if pins else [PDKPin(f"p{i}", PinDirection.INOUT, 0, -10*i) for i in range(4)],
            parameters=params,
            symbol_style="box",
            is_primitive=False,
            priority=5,
        )
        self._devices.append(device)

    def _extract_params(self, params_str: str) -> dict[str, str]:
        """Extract parameter name=value pairs from string."""
        params = {}
        if not params_str:
            return params
        # Match name=value pairs
        for match in re.finditer(r'(\w+)\s*=\s*([^\s)]+)', params_str):
            params[match.group(1)] = match.group(2)
        return params


# ── PDK Discovery Engine ───────────────────────────────────────

class PDKDiscoveryEngine:
    """
    Scans filesystem locations for PDKs and generates PDKInfo objects.
    Supports:
    - Standard PDK directory structures
    - Custom path lists
    - Built-in PDK definitions (Sky130, IHP, GF180)
    """

    def __init__(self):
        self._scanned_paths: set[str] = set()

    def discover_all(self, extra_paths: Optional[list[str]] = None) -> list[PDKInfo]:
        """
        Discover all available PDKs on the system.

        Args:
            extra_paths: Additional paths to scan beyond defaults.

        Returns:
            List of discovered PDKInfo objects (may include uninstalled built-ins).
        """
        pdks: dict[str, PDKInfo] = {}

        # 1. Add built-in PDK definitions (always available)
        for name, builder in self._get_builtin_pdk_builders().items():
            pdks[name] = builder()

        # 2. Scan filesystem paths
        paths_to_scan = list(PDK_DISCOVERY_PATHS)
        if extra_paths is not None:
            paths_to_scan.extend(extra_paths)

        for path_str in paths_to_scan:
            if not path_str or path_str in self._scanned_paths:
                continue
            self._scanned_paths.add(path_str)
            path = Path(path_str)
            if path.exists() and path.is_dir():
                discovered = self._scan_directory(path)
                for pdk in discovered:
                    if pdk.name not in pdks:
                        pdks[pdk.name] = pdk

        return list(pdks.values())

    def discover_at_path(self, path: str) -> Optional[PDKInfo]:
        """Discover a PDK at a specific directory path."""
        p = Path(path)
        if not p.exists() or not p.is_dir():
            return None
        result = self._scan_directory(p)
        return result[0] if result else None

    def _scan_directory(self, root: Path) -> list[PDKInfo]:
        """Scan a directory for PDKs (recursive up to 2 levels)."""
        pdks = []

        # Check if root itself is a PDK
        pdk = self._identify_pdk(root)
        if pdk:
            pdks.append(pdk)

        # Check immediate subdirectories
        if not pdks:
            for child in sorted(root.iterdir()):
                if child.is_dir() and not child.name.startswith("."):
                    pdk = self._identify_pdk(child)
                    if pdk:
                        pdks.append(pdk)

        # Check one level deeper
        if not pdks:
            for child in sorted(root.iterdir()):
                if child.is_dir() and not child.name.startswith("."):
                    for grandchild in sorted(child.iterdir()):
                        if grandchild.is_dir() and not grandchild.name.startswith("."):
                            pdk = self._identify_pdk(grandchild)
                            if pdk:
                                pdks.append(pdk)

        return pdks

    def _identify_pdk(self, directory: Path) -> Optional[PDKInfo]:
        """Check if a directory looks like a PDK root."""
        # Look for PDK identification markers
        is_pdk = False
        info_data = {}

        for marker in PDK_IDENTIFIER_FILES:
            marker_path = directory / marker
            if marker_path.exists():
                is_pdk = True
                # Try to load JSON metadata
                if marker_path.suffix in (".json", ".yaml") and marker_path.exists():
                    try:
                        with open(marker_path, "r") as f:
                            data = json.load(f)
                        if isinstance(data, dict):
                            info_data.update(data)
                    except (json.JSONDecodeError, OSError):
                        pass
                break

        if not is_pdk:
            # Heuristic: look for model files
            has_models = False
            for pattern in MODEL_FILE_PATTERNS:
                matches = list(directory.glob(pattern))
                if matches:
                    has_models = True
                    break
            if not has_models:
                return None
            is_pdk = True

        # Build PDK info from directory scan
        name = info_data.get("name", directory.name)
        display_name = info_data.get("display_name", name.replace("_", " ").title())
        foundry = info_data.get("foundry", "")
        process = info_data.get("process", name)
        node = info_data.get("node", self._guess_node_from_path(directory))
        description = info_data.get("description", "")
        version = info_data.get("version", "1.0")

        # Discover model files
        model_files = self._discover_model_files(directory)

        # Discover layers from markers
        layers = self._discover_layers(directory)

        # Parse model files for devices
        devices = self._parse_models_for_devices(model_files)

        # Create PDK info
        pdk = PDKInfo(
            name=name,
            display_name=display_name,
            foundry=foundry,
            process=process,
            node=node,
            version=version,
            description=description,
            root_path=str(directory.absolute()),
            models_path=str((directory / "models").absolute()) if (directory / "models").exists() else "",
            tech_path=str((directory / "tech").absolute()) if (directory / "tech").exists() else "",
            cells_path=str((directory / "cells").absolute()) if (directory / "cells").exists() else "",
            supply_voltage=info_data.get("supply_voltage", 1.8),
            temperature_range=(
                info_data.get("temp_min", -40),
                info_data.get("temp_max", 125),
            ),
            layers=layers,
            devices=devices,
            model_files=model_files,
            installed=True,
            tags=self._guess_tags(directory),
            url=info_data.get("url", ""),
            license=info_data.get("license", ""),
        )

        # Try to load corners from model files
        pdk.corners = self._discover_corners(model_files)

        return pdk

    def _discover_model_files(self, directory: Path) -> list[PDKModelFile]:
        """Find all model files in the PDK directory."""
        model_files = []
        seen = set()

        for pattern in MODEL_FILE_PATTERNS:
            for match_path in directory.glob(pattern):
                abs_path = str(match_path.absolute())
                if abs_path in seen:
                    continue
                seen.add(abs_path)

                # Determine format
                suffix = match_path.suffix.lower()
                fmt = "spice"
                if suffix == ".va" or suffix == ".vams":
                    fmt = "veriloga"
                elif suffix == ".cdl":
                    fmt = "cdl"

                try:
                    stat = match_path.stat()
                    model_files.append(PDKModelFile(
                        path=abs_path,
                        relative_path=str(match_path.relative_to(directory)),
                        format=fmt,
                        size_bytes=stat.st_size,
                        last_modified=stat.st_mtime,
                    ))
                except OSError:
                    continue

        return model_files

    def _parse_models_for_devices(self, model_files: list[PDKModelFile]) -> list[PDKDevice]:
        """Parse model files to extract device definitions."""
        all_devices: dict[str, PDKDevice] = {}
        parser = SpiceModelParser()

        for mf in model_files:
            if mf.format in ("spice", "cdl"):
                devices = parser.parse_file(mf.path)
                for dev in devices:
                    if dev.name not in all_devices:
                        all_devices[dev.name] = dev

        return list(all_devices.values())

    def _discover_layers(self, directory: Path) -> list[PDKLayer]:
        """Try to read layer definitions from the PDK."""
        layers = []

        # Try layers.json
        layers_json = directory / "layers.json"
        if layers_json.exists():
            try:
                with open(layers_json, "r") as f:
                    data = json.load(f)
                for entry in data:
                    layers.append(PDKLayer(
                        name=entry.get("name", ""),
                        gds_number=entry.get("gds", 0),
                        gds_datatype=entry.get("datatype", 0),
                        purpose=entry.get("purpose", "drawing"),
                        color=entry.get("color", "#808080"),
                        description=entry.get("description", ""),
                    ))
            except (json.JSONDecodeError, OSError):
                pass

        return layers

    def _discover_corners(self, model_files: list[PDKModelFile]) -> list[PDKCorner]:
        """Extract corner definitions from model library files."""
        corners = []

        # Look for .LIB sections in model files
        corner_pattern = re.compile(r'\.LIB\s+"?([^"]*)"?\s+(\w+)', re.IGNORECASE)

        for mf in model_files:
            if not mf.path.endswith(".lib"):
                continue
            try:
                with open(mf.path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                for match in corner_pattern.finditer(content):
                    section = match.group(2)
                    if section not in [c.name for c in corners]:
                        corners.append(PDKCorner(
                            name=section,
                            description=f"Corner from {os.path.basename(mf.path)}",
                            temperature=25.0,
                            lib_section=section,
                        ))
            except OSError:
                continue

        return corners

    def _guess_node_from_path(self, path: Path) -> str:
        """Guess the technology node from directory path name."""
        name_lower = path.name.lower()
        node_patterns = [
            (r'(\d+)nm', lambda m: f"{m.group(1)}nm"),
            (r'(\d+)um', lambda m: f"{m.group(1)}um"),
            (r'(\d+)micron', lambda m: f"{m.group(1)}um"),
            (r'130', lambda _: "130nm"),
            (r'180', lambda _: "180nm"),
            (r'28', lambda _: "28nm"),
            (r'65', lambda _: "65nm"),
            (r'45', lambda _: "45nm"),
            (r'90', lambda _: "90nm"),
        ]
        for pattern, formatter in node_patterns:
            m = re.search(pattern, name_lower)
            if m:
                return formatter(m)
        return "unknown"

    def _guess_tags(self, directory: Path) -> list[str]:
        """Guess tags for a PDK."""
        tags = []
        name_lower = directory.name.lower()
        if "bicmos" in name_lower or "sige" in name_lower:
            tags.append("bicmos")
        if "cmos" in name_lower:
            tags.append("cmos")
        if "soi" in name_lower:
            tags.append("soi")
        if "open" in name_lower:
            tags.append("open-source")
        return tags

    def _get_builtin_pdk_builders(self) -> dict[str, Callable[[], PDKInfo]]:
        """Return built-in PDK definitions."""
        return {
            "sky130": self._build_sky130,
            "ihp_sg13g2": self._build_ihp_sg13g2,
            "gf180mcu": self._build_gf180mcu,
        }

    def _build_sky130(self) -> PDKInfo:
        pdk = PDKInfo(
            name="sky130",
            display_name="SkyWater SKY130",
            foundry="SkyWater Technology",
            process="SKY130",
            node="130nm",
            version="1.0.0",
            description="SkyWater 130nm open-source CMOS process. "
                        "5 metal layers, 1.8V core / 3.3V I/O. "
                        "Comprehensive set of devices including low-Vt, high-Vt, "
                        "native, and thick-oxide options.",
            license="Apache-2.0",
            url="https://github.com/google/skywater-pdk",
            supply_voltage=1.8,
            temperature_range=(-40, 125),
            layers=[
                PDKLayer("nwell", 64, 20, "drawing", "#aaffaa"),
                PDKLayer("diff", 65, 20, "drawing", "#c8c846"),
                PDKLayer("poly", 66, 20, "drawing", "#ff0000"),
                PDKLayer("li1", 67, 20, "drawing", "#c8c8ff"),
                PDKLayer("met1", 68, 20, "drawing", "#5050ff", min_width=0.17, min_spacing=0.17),
                PDKLayer("met2", 69, 20, "drawing", "#ff50ff", min_width=0.17, min_spacing=0.17),
                PDKLayer("met3", 70, 20, "drawing", "#50ffff", min_width=0.17, min_spacing=0.17),
                PDKLayer("met4", 71, 20, "drawing", "#ffa050", min_width=0.17, min_spacing=0.17),
                PDKLayer("met5", 72, 20, "drawing", "#ffff50", min_width=0.17, min_spacing=0.17),
            ],
            devices=self._get_sky130_devices(),
            corners=[
                PDKCorner("tt", "Typical-Typical", 25, "tt"),
                PDKCorner("ff", "Fast-Fast", -40, "ff"),
                PDKCorner("ss", "Slow-Slow", 125, "ss"),
                PDKCorner("sf", "Slow-Fast", 25, "sf"),
                PDKCorner("fs", "Fast-Slow", 25, "fs"),
            ],
            is_builtin=True,
            tags=["cmos", "open-source", "mixed-signal"],
        )
        # Set path to existing sky130 PDK if available
        local_path = Path("C:/EDA/LumenCircuitStudio/external/ihp_pdk/ihp-sg13g2").parent.parent / "sky130"
        if not local_path.exists():
            local_path = Path("C:/EDA/ihp_pdk/ihp-sg13g2").parent.parent / "sky130"
        if local_path.exists():
            pdk.root_path = str(local_path)
            pdk.installed = True
        return pdk

    def _build_ihp_sg13g2(self) -> PDKInfo:
        cwd = os.getcwd()
        ihp_path = os.path.join(cwd, "external", "ihp_pdk", "ihp-sg13g2")
        if not os.path.isdir(ihp_path):
            ihp_path = os.path.join(cwd, "ihp_pdk", "ihp-sg13g2")
        installed = os.path.isdir(ihp_path)

        pdk = PDKInfo(
            name="ihp_sg13g2",
            display_name="IHP SG13G2",
            foundry="IHP Microelectronics",
            process="SG13G2",
            node="130nm",
            version="1.0.0",
            description="IHP 130nm SiGe BiCMOS open-source process. "
                        "RF/mmWave up to 250 GHz fT HBTs. "
                        "LV/HV CMOS, SiGe HBTs, high-value resistors, MIM caps.",
            license="Apache-2.0",
            url="https://github.com/IHP-GmbH/IHP-Open-PDK",
            root_path=ihp_path if installed else "",
            supply_voltage=1.2,
            temperature_range=(-40, 125),
            installed=installed,
            layers=[
                PDKLayer("Activ", 1, 0, "drawing", "#c8c846"),
                PDKLayer("GatPoly", 5, 0, "drawing", "#ff0000"),
                PDKLayer("NWell", 31, 0, "drawing", "#aaffaa"),
                PDKLayer("Metal1", 8, 0, "drawing", "#5050ff", min_width=0.19, min_spacing=0.19),
                PDKLayer("Metal2", 10, 0, "drawing", "#ff50ff", min_width=0.19, min_spacing=0.19),
                PDKLayer("Metal3", 30, 0, "drawing", "#50ffff", min_width=0.19, min_spacing=0.19),
                PDKLayer("Metal4", 50, 0, "drawing", "#ffa050"),
                PDKLayer("Metal5", 67, 0, "drawing", "#ffff50"),
                PDKLayer("TopMetal1", 53, 0, "drawing", "#aa88cc"),
                PDKLayer("TopMetal2", 54, 0, "drawing", "#88ccaa"),
            ],
            devices=self._get_ihp_devices(),
            corners=[
                PDKCorner("typ", "Typical", 27, "typ"),
                PDKCorner("fast", "Fast", -40, "fast"),
                PDKCorner("slow", "Slow", 125, "slow"),
            ],
            is_builtin=True,
            tags=["bicmos", "sige", "rf", "open-source"],
        )
        return pdk

    def _build_gf180mcu(self) -> PDKInfo:
        pdk = PDKInfo(
            name="gf180mcu",
            display_name="GlobalFoundries GF180MCU",
            foundry="GlobalFoundries",
            process="GF180MCU",
            node="180nm",
            version="1.0.0",
            description="GlobalFoundries 180nm MCU open-source process. "
                        "3.3V/5V/6V options, 5 metal layers, MIM caps.",
            license="Apache-2.0",
            url="https://github.com/google/gf180mcu-pdk",
            supply_voltage=3.3,
            temperature_range=(-40, 175),
            layers=[
                PDKLayer("nwell", 21, 0, "drawing", "#aaffaa"),
                PDKLayer("comp", 22, 0, "drawing", "#c8c846"),
                PDKLayer("poly2", 30, 0, "drawing", "#ff0000"),
                PDKLayer("metal1", 34, 0, "drawing", "#5050ff"),
                PDKLayer("metal2", 36, 0, "drawing", "#ff50ff"),
                PDKLayer("metal3", 42, 0, "drawing", "#50ffff"),
                PDKLayer("metal4", 46, 0, "drawing", "#ffa050"),
                PDKLayer("metal5", 81, 0, "drawing", "#ffff50"),
            ],
            devices=self._get_gf180_devices(),
            corners=[
                PDKCorner("typical", "Typical", 25, "typical"),
                PDKCorner("ff", "Fast-Fast", -40, "ff"),
                PDKCorner("ss", "Slow-Slow", 125, "ss"),
                PDKCorner("sf", "Slow-Fast", 25, "sf"),
                PDKCorner("fs", "Fast-Slow", 25, "fs"),
            ],
            is_builtin=True,
            tags=["cmos", "open-source", "mcu"],
        )
        return pdk

    # ── Built-in Device Definitions ────────────────────────────

    def _get_sky130_devices(self) -> list[PDKDevice]:
        """Define Sky130 built-in devices."""
        return [
            PDKDevice("sky130_fd_pr__nfet_01v8", DeviceCategory.MOS, "M",
                      "sky130_fd_pr__nfet_01v8", "1.8V NMOS",
                      pins=[PDKPin("D", PinDirection.INOUT, 20, -30),
                            PDKPin("G", PinDirection.INPUT, -20, 0),
                            PDKPin("S", PinDirection.INOUT, 20, 30),
                            PDKPin("B", PinDirection.INOUT, 40, 0)],
                      parameters=[PDKParameter("W", "0.42u", "Width", "m"),
                                  PDKParameter("L", "0.15u", "Length", "m"),
                                  PDKParameter("nf", "1", "Fingers"),
                                  PDKParameter("mult", "1", "Multiplier")],
                      constraints=[PDKConstraint("W", 0.15e-6, 100e-6, "m"),
                                   PDKConstraint("L", 0.15e-6, 10e-6, "m")],
                      priority=10),
            PDKDevice("sky130_fd_pr__pfet_01v8", DeviceCategory.MOS, "M",
                      "sky130_fd_pr__pfet_01v8", "1.8V PMOS",
                      pins=[PDKPin("D", PinDirection.INOUT, 20, 30),
                            PDKPin("G", PinDirection.INPUT, -20, 0),
                            PDKPin("S", PinDirection.INOUT, 20, -30),
                            PDKPin("B", PinDirection.INOUT, 40, 0)],
                      parameters=[PDKParameter("W", "0.55u", "Width", "m"),
                                  PDKParameter("L", "0.15u", "Length", "m"),
                                  PDKParameter("nf", "1", "Fingers"),
                                  PDKParameter("mult", "1", "Multiplier")],
                      constraints=[PDKConstraint("W", 0.15e-6, 100e-6, "m"),
                                   PDKConstraint("L", 0.15e-6, 10e-6, "m")],
                      priority=10),
            PDKDevice("sky130_fd_pr__nfet_01v8_lvt", DeviceCategory.MOS, "M",
                      "sky130_fd_pr__nfet_01v8_lvt", "1.8V Low-Vt NMOS",
                      pins=[PDKPin("D", PinDirection.INOUT, 20, -30),
                            PDKPin("G", PinDirection.INPUT, -20, 0),
                            PDKPin("S", PinDirection.INOUT, 20, 30),
                            PDKPin("B", PinDirection.INOUT, 40, 0)],
                      parameters=[PDKParameter("W", "0.42u", "Width", "m"),
                                  PDKParameter("L", "0.15u", "Length", "m"),
                                  PDKParameter("nf", "1", "Fingers")],
                      priority=8),
            PDKDevice("sky130_fd_pr__pfet_01v8_hvt", DeviceCategory.MOS, "M",
                      "sky130_fd_pr__pfet_01v8_hvt", "1.8V High-Vt PMOS",
                      pins=[PDKPin("D", PinDirection.INOUT, 20, 30),
                            PDKPin("G", PinDirection.INPUT, -20, 0),
                            PDKPin("S", PinDirection.INOUT, 20, -30),
                            PDKPin("B", PinDirection.INOUT, 40, 0)],
                      parameters=[PDKParameter("W", "0.55u", "Width", "m"),
                                  PDKParameter("L", "0.15u", "Length", "m"),
                                  PDKParameter("nf", "1", "Fingers")],
                      priority=8),
            PDKDevice("sky130_fd_pr__nfet_03v3_nvt", DeviceCategory.MOS, "M",
                      "sky130_fd_pr__nfet_03v3_nvt", "3.3V Native NMOS",
                      pins=[PDKPin("D", PinDirection.INOUT, 20, -30),
                            PDKPin("G", PinDirection.INPUT, -20, 0),
                            PDKPin("S", PinDirection.INOUT, 20, 30),
                            PDKPin("B", PinDirection.INOUT, 40, 0)],
                      parameters=[PDKParameter("W", "0.42u", "Width", "m"),
                                  PDKParameter("L", "0.5u", "Length", "m"),
                                  PDKParameter("nf", "1", "Fingers")],
                      priority=6),
            PDKDevice("sky130_fd_pr__res_generic_nd", DeviceCategory.RESISTOR, "R",
                      "sky130_fd_pr__res_generic_nd", "N-diffusion Resistor",
                      parameters=[PDKParameter("R", "1k", "Resistance", "ohm"),
                                  PDKParameter("W", "0.42u", "Width", "m"),
                                  PDKParameter("L", "1u", "Length", "m")],
                      priority=9),
            PDKDevice("sky130_fd_pr__res_high_po", DeviceCategory.RESISTOR, "R",
                      "sky130_fd_pr__res_high_po", "High-Resistance Poly Resistor",
                      parameters=[PDKParameter("R", "10k", "Resistance", "ohm"),
                                  PDKParameter("W", "0.35u", "Width", "m"),
                                  PDKParameter("L", "1u", "Length", "m")],
                      priority=9),
            PDKDevice("sky130_fd_pr__cap_mim_m3_1", DeviceCategory.CAPACITOR, "C",
                      "sky130_fd_pr__cap_mim_m3_1", "MIM Capacitor (M3-M4)",
                      parameters=[PDKParameter("C", "1p", "Capacitance", "F"),
                                  PDKParameter("W", "2u", "Width", "m"),
                                  PDKParameter("L", "2u", "Length", "m")],
                      priority=9),
            PDKDevice("sky130_fd_pr__diode_pw2nd_05v5", DeviceCategory.DIODE, "D",
                      "sky130_fd_pr__diode_pw2nd_05v5", "PW-ND Junction Diode",
                      parameters=[PDKParameter("area", "1p", "Area", "m^2")],
                      priority=7),
            PDKDevice("sky130_fd_pr__npn_05v5", DeviceCategory.BJT, "Q",
                      "sky130_fd_pr__npn_05v5", "5V NPN BJT",
                      parameters=[PDKParameter("mult", "1", "Multiplier")],
                      priority=7),
        ]

    def _get_ihp_devices(self) -> list[PDKDevice]:
        """Define IHP SG13G2 built-in devices."""
        return [
            PDKDevice("sg13_lv_nmos", DeviceCategory.MOS, "M",
                      "sg13_lv_nmos", "1.2V LV NMOS",
                      parameters=[PDKParameter("W", "0.5u", "Width", "m"),
                                  PDKParameter("L", "0.13u", "Length", "m"),
                                  PDKParameter("nf", "1", "Fingers")],
                      constraints=[PDKConstraint("W", 0.13e-6, 50e-6, "m"),
                                   PDKConstraint("L", 0.13e-6, 10e-6, "m")],
                      priority=10),
            PDKDevice("sg13_lv_pmos", DeviceCategory.MOS, "M",
                      "sg13_lv_pmos", "1.2V LV PMOS",
                      parameters=[PDKParameter("W", "0.5u", "Width", "m"),
                                  PDKParameter("L", "0.13u", "Length", "m"),
                                  PDKParameter("nf", "1", "Fingers")],
                      constraints=[PDKConstraint("W", 0.13e-6, 50e-6, "m"),
                                   PDKConstraint("L", 0.13e-6, 10e-6, "m")],
                      priority=10),
            PDKDevice("sg13_hv_nmos", DeviceCategory.MOS, "M",
                      "sg13_hv_nmos", "3.3V HV NMOS",
                      parameters=[PDKParameter("W", "1u", "Width", "m"),
                                  PDKParameter("L", "0.4u", "Length", "m"),
                                  PDKParameter("nf", "1", "Fingers")],
                      priority=7),
            PDKDevice("sg13_hv_pmos", DeviceCategory.MOS, "M",
                      "sg13_hv_pmos", "3.3V HV PMOS",
                      parameters=[PDKParameter("W", "1u", "Width", "m"),
                                  PDKParameter("L", "0.4u", "Length", "m"),
                                  PDKParameter("nf", "1", "Fingers")],
                      priority=7),
            PDKDevice("npn13G2", DeviceCategory.BJT, "Q",
                      "npn13G2", "SiGe HBT (fT=250GHz)",
                      parameters=[PDKParameter("le", "0.9u", "Emitter length", "m"),
                                  PDKParameter("we", "0.07u", "Emitter width", "m"),
                                  PDKParameter("mult", "1", "Multiplier")],
                      priority=10),
            PDKDevice("rsil", DeviceCategory.RESISTOR, "R",
                      "rsil", "Silicided Poly Resistor",
                      parameters=[PDKParameter("R", "1k", "Resistance", "ohm"),
                                  PDKParameter("W", "0.5u", "Width", "m"),
                                  PDKParameter("L", "2u", "Length", "m")],
                      priority=8),
            PDKDevice("rppd", DeviceCategory.RESISTOR, "R",
                      "rppd", "P+ Poly Resistor (High-R)",
                      parameters=[PDKParameter("R", "10k", "Resistance", "ohm"),
                                  PDKParameter("W", "0.5u", "Width", "m"),
                                  PDKParameter("L", "5u", "Length", "m")],
                      priority=8),
            PDKDevice("cmim", DeviceCategory.CAPACITOR, "C",
                      "cmim", "MIM Capacitor",
                      parameters=[PDKParameter("C", "1p", "Capacitance", "F"),
                                  PDKParameter("W", "5u", "Width", "m"),
                                  PDKParameter("L", "5u", "Length", "m")],
                      priority=8),
        ]

    def _get_gf180_devices(self) -> list[PDKDevice]:
        """Define GF180MCU built-in devices."""
        return [
            PDKDevice("nfet_03v3", DeviceCategory.MOS, "M",
                      "nfet_03v3", "3.3V NMOS",
                      parameters=[PDKParameter("W", "0.44u", "Width", "m"),
                                  PDKParameter("L", "0.28u", "Length", "m"),
                                  PDKParameter("nf", "1", "Fingers")],
                      priority=10),
            PDKDevice("pfet_03v3", DeviceCategory.MOS, "M",
                      "pfet_03v3", "3.3V PMOS",
                      parameters=[PDKParameter("W", "0.5u", "Width", "m"),
                                  PDKParameter("L", "0.28u", "Length", "m"),
                                  PDKParameter("nf", "1", "Fingers")],
                      priority=10),
            PDKDevice("nfet_05v0", DeviceCategory.MOS, "M",
                      "nfet_05v0", "5V NMOS",
                      parameters=[PDKParameter("W", "0.8u", "Width", "m"),
                                  PDKParameter("L", "0.6u", "Length", "m"),
                                  PDKParameter("nf", "1", "Fingers")],
                      priority=8),
            PDKDevice("pfet_05v0", DeviceCategory.MOS, "M",
                      "pfet_05v0", "5V PMOS",
                      parameters=[PDKParameter("W", "0.8u", "Width", "m"),
                                  PDKParameter("L", "0.6u", "Length", "m"),
                                  PDKParameter("nf", "1", "Fingers")],
                      priority=8),
            PDKDevice("nplus_u", DeviceCategory.RESISTOR, "R",
                      "nplus_u", "N+ Diffusion Resistor",
                      parameters=[PDKParameter("R", "1k", "Resistance", "ohm"),
                                  PDKParameter("W", "0.42u", "Width", "m"),
                                  PDKParameter("L", "2u", "Length", "m")],
                      priority=8),
            PDKDevice("pplus_u", DeviceCategory.RESISTOR, "R",
                      "pplus_u", "P+ Diffusion Resistor",
                      parameters=[PDKParameter("R", "1k", "Resistance", "ohm"),
                                  PDKParameter("W", "0.42u", "Width", "m"),
                                  PDKParameter("L", "2u", "Length", "m")],
                      priority=8),
            PDKDevice("mim_1p5fF", DeviceCategory.CAPACITOR, "C",
                      "mim_1p5fF", "MIM Capacitor (1.5 fF/µm²)",
                      parameters=[PDKParameter("C", "1p", "Capacitance", "F"),
                                  PDKParameter("W", "5u", "Width", "m"),
                                  PDKParameter("L", "5u", "Length", "m")],
                      priority=9),
            PDKDevice("np_3p3", DeviceCategory.DIODE, "D",
                      "np_3p3", "N+/P-well Diode 3.3V",
                      parameters=[PDKParameter("area", "1p", "Area", "m^2")],
                      priority=7),
        ]
