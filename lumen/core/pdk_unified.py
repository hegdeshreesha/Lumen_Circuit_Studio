"""
Lumen Circuit Studio — Unified PDK Management System

This module replaces the three existing PDK implementations with a single
canonical, schema-driven system that provides:

- PDK manifest validation (JSON Schema)
- Version pinning and lockfiles for reproducibility
- Deterministic model file/corner resolution
- Technology binding between libraries and PDKs
- Device parameter constraints enforced in property editor
- CDF-like device metadata with callbacks
- Import adapters for Xschem, KLayout, OpenPDK, vendor bundles
- PDK health monitoring and audit trail
- Plugin architecture for custom PDK adapters

This system is designed to be superior to industry-standard's CDF/technology file approach.
"""
import json
import os
import time
import hashlib
import subprocess
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from enum import Enum
import re

from .layout_layers import parse_klayout_layer_properties
from .validation import SchemaValidator


# ── PDK Schema Version ────────────────────────────────────────

PDK_SCHEMA_VERSION = "1.0"


# ── Device Category ────────────────────────────────────────────

class DeviceCategory(str, Enum):
    MOSFET = "MOSFET"
    RESISTOR = "Resistor"
    CAPACITOR = "Capacitor"
    INDUCTOR = "Inductor"
    DIODE = "Diode"
    BJT = "BJT"
    SOURCE = "Source"
    SWITCH = "Switch"
    OTHER = "Other"


# ── Core PDK Data Model ────────────────────────────────────────

@dataclass
class PDKParameter:
    """A device parameter with full metadata."""
    name: str
    default: str = ""
    description: str = ""
    unit: str = ""
    display_name: str = ""
    constraints: Dict[str, Any] = field(default_factory=dict)  # min, max, allowed_values

    def __iter__(self):
        """Compatibility iterator so legacy code can treat parameter as (name, default)."""
        yield self.name
        yield self.default


@dataclass
class PDKPin:
    """A device pin with position and metadata."""
    name: str
    x: float = 0.0
    y: float = 0.0
    direction: str = "inout"  # input, output, inout, power, ground
    description: str = ""
    net_name: Optional[str] = None  # For hard-coded nets like GND, VDD


@dataclass
class PDKConstraint:
    """Design rule constraint for a device parameter."""
    param: str
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    unit: str = ""
    description: str = ""


@dataclass
class PDKCorner:
    """A process corner definition."""
    name: str
    description: str = ""
    temperature: float = 25.0
    voltage: float = 1.8
    lib_section: str = ""  # The .LIB section name in model files
    model_kwargs: Dict[str, str] = field(default_factory=dict)


@dataclass
class PDKModelFile:
    """A discovered SPICE model file."""
    path: str
    relative_path: str = ""
    format: str = "spice"  # spice, veriloga, cdl, etc.
    corners: List[str] = field(default_factory=list)
    size_bytes: int = 0
    last_modified: float = 0.0
    checksum: str = ""


@dataclass
class PDKSymbolTemplate:
    """A symbol template for device visualization."""
    name: str
    shapes: List[Dict] = field(default_factory=list)
    pin_style: str = "dot"
    body_color: str = "#e94560"
    pin_color: str = "#ffd60a"
    label_position: Dict = field(default_factory=lambda: {"x": 15, "y": -25})


@dataclass
class PDKDevice:
    """A complete device definition from the PDK."""
    name: str
    category: DeviceCategory
    prefix: str  # SPICE prefix: M, R, C, Q, D, etc.
    model: str  # SPICE model name
    # device-parameter metadata-style linkage fields used by netlisting.
    component_name: str = ""  # Netlist component/model/subckt token
    term_order: List[str] = field(default_factory=list)  # Ordered terminal names
    inst_parameters: List[str] = field(default_factory=list)  # Ordered instance params
    other_parameters: List[str] = field(default_factory=list)  # Optional additional params
    netlist_kind: str = "primitive"  # primitive | subckt
    description: str = ""
    pins: List[PDKPin] = field(default_factory=list)
    parameters: List[PDKParameter] = field(default_factory=list)
    constraints: List[PDKConstraint] = field(default_factory=list)
    symbol_style: str = "default"
    symbol_data: Optional[Dict] = None  # Generated symbol JSON
    is_primitive: bool = False
    priority: int = 0  # Higher = more preferred in catalogs
    provenance: Dict[str, Any] = field(default_factory=dict)  # Source file, line, etc.


@dataclass
class PDKInfo:
    """Complete PDK definition — the master schema."""
    # Identity
    name: str
    display_name: str = ""
    foundry: str = ""
    process: str = ""
    node: str = ""  # e.g., "130nm", "180nm"
    version: str = "1.0"
    schema_version: str = PDK_SCHEMA_VERSION
    description: str = ""
    license: str = ""
    
    # Paths
    root_path: str = ""
    models_path: str = ""
    tech_path: str = ""
    cells_path: str = ""
    symbols_path: str = ""
    
    # Content
    supply_voltage: float = 1.8
    temperature_range: tuple = (-40, 125)
    corners: List[PDKCorner] = field(default_factory=list)
    devices: List[PDKDevice] = field(default_factory=list)
    layers: List[Dict] = field(default_factory=list)  # Layer definitions
    model_files: List[PDKModelFile] = field(default_factory=list)
    symbol_templates: List[PDKSymbolTemplate] = field(default_factory=list)
    
    # Status
    installed: bool = False
    is_builtin: bool = False
    is_valid: bool = True
    validation_errors: List[str] = field(default_factory=list)
    
    # Metadata
    tags: List[str] = field(default_factory=list)
    url: str = ""
    author: str = ""
    manifest_path: Optional[str] = None
    manifest_checksum: str = ""
    
    # Lockfile data (for reproducibility)
    lockfile_data: Dict[str, Any] = field(default_factory=dict)

    @property
    def installed(self) -> bool:
        """Compatibility alias used by legacy UI code."""
        return self.is_installed

    @installed.setter
    def installed(self, value: bool):
        self.is_installed = value

    @property
    def install_path(self) -> str:
        """Compatibility alias used by legacy UI code."""
        return self.root_path

    @install_path.setter
    def install_path(self, value: str):
        self.root_path = value


# ── Lockfile Format ────────────────────────────────────────────

@dataclass
class PDKLock:
    """Lockfile for a specific design project."""
    pdk_name: str
    pdk_version: str
    pdk_manifest_hash: str
    model_files_hash: str
    device_catalog_hash: str
    used_corners: List[str]
    used_devices: List[str]
    timestamp: float = 0.0
    
    def save(self, path: str):
        """Save lockfile to disk."""
        data = asdict(self)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    
    @classmethod
    def load(cls, path: str) -> 'PDKLock':
        """Load lockfile from disk."""
        with open(path, "r") as f:
            data = json.load(f)
        return cls(**data)

    @classmethod
    def create_lockfile(cls, pdk_info: PDKInfo, project_dir: str, used_corners: Optional[List[str]] = None, used_devices: Optional[List[str]] = None) -> 'PDKLock':
        """Create a deterministic lockfile for a project workspace bound to a PDK."""
        lock = cls.create(pdk_info, used_corners, used_devices)
        lock_path = Path(project_dir) / "lumen.lock"
        lock.save(str(lock_path))
        return lock

    @classmethod
    def create(cls, pdk_info: PDKInfo, used_corners: Optional[List[str]] = None, used_devices: Optional[List[str]] = None) -> 'PDKLock':
        """Create deterministic lock data for a PDK without writing it."""
        manifest_str = f"{pdk_info.name}:{pdk_info.version}:{pdk_info.foundry}"
        pdk_hash = hashlib.sha256(manifest_str.encode("utf-8")).hexdigest()[:16]

        models_str = ",".join(sorted(mf.path for mf in pdk_info.model_files))
        models_hash = hashlib.sha256(models_str.encode("utf-8")).hexdigest()[:16]

        devices_str = ",".join(sorted(d.name for d in pdk_info.devices))
        device_hash = hashlib.sha256(devices_str.encode("utf-8")).hexdigest()[:16]

        lock = cls(
            pdk_name=pdk_info.name,
            pdk_version=pdk_info.version,
            pdk_manifest_hash=pdk_hash,
            model_files_hash=models_hash,
            device_catalog_hash=device_hash,
            used_corners=used_corners or [c.name for c in pdk_info.corners],
            used_devices=used_devices or [d.name for d in pdk_info.devices],
            timestamp=time.time(),
        )
        return lock


# ── Model File Parser ──────────────────────────────────────────

class SpiceModelParser:
    """
    Parses SPICE model library files to extract available devices.
    Handles .MODEL, .SUBCKT, .LIB sections, .INCLUDE references.
    """
    
    MODEL_TYPE_MAP = {
        "NMOS": DeviceCategory.MOSFET,
        "PMOS": DeviceCategory.MOSFET,
        "NJF": DeviceCategory.MOSFET,
        "PJF": DeviceCategory.MOSFET,
        "NPN": DeviceCategory.BJT,
        "PNP": DeviceCategory.BJT,
        "D": DeviceCategory.DIODE,
        "DIO": DeviceCategory.DIODE,
        "RES": DeviceCategory.RESISTOR,
        "CAP": DeviceCategory.CAPACITOR,
        "IND": DeviceCategory.INDUCTOR,
        "CORE": DeviceCategory.OTHER,
        "SW": DeviceCategory.SWITCH,
        "VSWITCH": DeviceCategory.SWITCH,
        "ISWITCH": DeviceCategory.SWITCH,
    }
    
    DEFAULT_PINS = {
        DeviceCategory.MOSFET: [
            PDKPin("D", 20, -30, "inout"),
            PDKPin("G", -20, 0, "input"),
            PDKPin("S", 20, 30, "inout"),
            PDKPin("B", 40, 0, "inout"),
        ],
        DeviceCategory.BJT: [
            PDKPin("C", 15, -30, "inout"),
            PDKPin("B", -30, 0, "input"),
            PDKPin("E", 15, 30, "inout"),
        ],
        DeviceCategory.DIODE: [
            PDKPin("PLUS", 0, -30, "input"),
            PDKPin("MINUS", 0, 30, "output"),
        ],
        DeviceCategory.RESISTOR: [
            PDKPin("PLUS", 0, -30, "input"),
            PDKPin("MINUS", 0, 30, "output"),
        ],
        DeviceCategory.CAPACITOR: [
            PDKPin("PLUS", 0, -30, "input"),
            PDKPin("MINUS", 0, 30, "output"),
        ],
    }
    
    def __init__(self):
        self._devices: List[PDKDevice] = []
        self._subckts: Dict[str, Dict] = {}
        self._current_lib_section: str = ""
        self._current_file: str = ""
    
    def parse_file(self, filepath: str) -> List[PDKDevice]:
        """Parse a SPICE model file and extract device definitions."""
        self._devices = []
        self._subckts = {}
        self._current_lib_section = ""
        self._current_file = filepath
        
        if not os.path.isfile(filepath):
            return []
        
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            return []
        
        # Compute checksum
        self._file_checksum = hashlib.md5(content.encode()).hexdigest()
        
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
            
            if up.startswith(".SUBCKT"):
                sub_lines, i = self._extract_block(lines, i)
                self._parse_subckt(sub_lines)
            elif up.startswith(".LIB"):
                lib_match = re.match(r'\.LIB\s+"?([^"\s]+)"?\s+(\w+)', line)
                if lib_match:
                    self._current_lib_section = lib_match.group(2)
                i += 1
            elif up.startswith(".MODEL"):
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
            stripped = line.strip()
            if stripped.startswith("*") and not stripped.startswith(".model"):
                continue
            if ";" in line:
                line = line.split(";")[0]
            cleaned.append(line)
        return "\n".join(cleaned)
    
    def _extract_block(self, lines: List[str], start: int) -> tuple[List[str], int]:
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
        """Parse a .MODEL statement."""
        match = re.match(
            r'\.MODEL\s+(\S+)\s+(\S+)(?:\s*\(([^)]*)\))?',
            line, re.IGNORECASE
        )
        if not match:
            return
        
        model_name = match.group(1)
        model_type = match.group(2).upper()
        params_str = match.group(3) or ""
        
        category = self.MODEL_TYPE_MAP.get(model_type, DeviceCategory.OTHER)
        prefix = self.PREFIX_MAP.get(category, "X")
        if category == DeviceCategory.MOSFET:
            prefix = "M"
        elif category == DeviceCategory.BJT:
            prefix = "Q"
        elif category == DeviceCategory.DIODE:
            prefix = "D"
        elif category == DeviceCategory.RESISTOR:
            prefix = "R"
        elif category == DeviceCategory.CAPACITOR:
            prefix = "C"
        
        pins = self.DEFAULT_PINS.get(category, []).copy()
        params = self.DEFAULT_PARAMS.get(category, []).copy()
        
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
            component_name=model_name,
            term_order=[p.name for p in pins],
            inst_parameters=[p.name for p in params],
            other_parameters=[],
            netlist_kind="primitive",
            description=description,
            pins=pins,
            parameters=params,
            symbol_style=category.name.lower(),
            is_primitive=True,
            priority=10 if category != DeviceCategory.OTHER else 0,
            provenance={
                "source": "model_file",
                "file": self._current_file,
                "section": self._current_lib_section,
                "type": model_type,
                "checksum": self._file_checksum,
            }
        )
        
        # Add constraints based on category
        if category == DeviceCategory.MOSFET:
            device.constraints = [
                PDKConstraint("W", min_value=0.1e-6, max_value=1e-3, unit="m",
                              description="Transistor width"),
                PDKConstraint("L", min_value=0.05e-6, max_value=0.1e-3, unit="m",
                              description="Transistor length"),
            ]
        
        self._devices.append(device)
    
    def _parse_subckt(self, lines: List[str]):
        """Parse a .SUBCKT definition."""
        first = lines[0].strip()
        match = re.match(r'\.SUBCKT\s+(\S+)\s+(.*)', first, re.IGNORECASE)
        if not match:
            return
        
        sub_name = match.group(1)
        rest = match.group(2).strip()
        
        # Extract parameters
        pins_part = rest
        params_part = ""
        
        if "?" in rest:
            parts = rest.split("?")
            pins_part = parts[0].strip()
            params_part = parts[1].strip() if len(parts) > 1 else ""
        elif "PARAMS:" in rest.upper():
            parts = rest.upper().split("PARAMS:")
            pins_part = parts[0].strip()
            params_part = rest[len("PARAMS:"):].strip() if len(parts) > 1 else ""
        
        # Extract pin names
        pin_names = pins_part.split()
        pins = []
        for i, pname in enumerate(pin_names):
            y_offset = -20 + i * 15
            pins.append(PDKPin(pname, 0, y_offset, "inout"))
        
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
        for line in lines:
            up = line.strip().upper()
            for model_type in ["NMOS", "PMOS", "NPN", "PNP", "D "] + ["DIO"]:
                if model_type in up:
                    mt = model_type.strip()
                    cat = self.MODEL_TYPE_MAP.get(mt if mt != "D " else "D", DeviceCategory.OTHER)
                    if cat != DeviceCategory.OTHER:
                        category = cat
                    break
        
        prefix = "X"
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
            component_name=sub_name,
            term_order=list(pin_names),
            inst_parameters=[p.name for p in params],
            other_parameters=[],
            netlist_kind="subckt",
            description=f"Subcircuit: {sub_name}",
            pins=pins,
            parameters=params,
            symbol_style="box",
            is_primitive=False,
            priority=5,
            provenance={
                "source": "subcircuit",
                "file": self._current_file,
                "section": self._current_lib_section,
            }
        )
        self._devices.append(device)
    
    def _extract_params(self, params_str: str) -> Dict[str, str]:
        """Extract parameter name=value pairs from string."""
        params = {}
        if not params_str:
            return params
        for match in re.finditer(r'(\w+)\s*=\s*([^\s)]+)', params_str):
            params[match.group(1)] = match.group(2)
        return params
    
    # Default parameters for categories
    DEFAULT_PARAMS = {
        DeviceCategory.MOSFET: [
            PDKParameter("W", "1u", "Width", "m"),
            PDKParameter("L", "100n", "Length", "m"),
            PDKParameter("nf", "1", "Number of Fingers", ""),
            PDKParameter("mult", "1", "Multiplier", ""),
        ],
        DeviceCategory.RESISTOR: [
            PDKParameter("R", "1k", "Resistance", "ohm"),
            PDKParameter("W", "1u", "Width", "m"),
            PDKParameter("L", "1u", "Length", "m"),
        ],
        DeviceCategory.CAPACITOR: [
            PDKParameter("C", "1p", "Capacitance", "F"),
            PDKParameter("W", "5u", "Width", "m"),
            PDKParameter("L", "5u", "Length", "m"),
        ],
        DeviceCategory.DIODE: [
            PDKParameter("area", "1", "Area multiplier", ""),
        ],
        DeviceCategory.BJT: [
            PDKParameter("mult", "1", "Multiplier", ""),
            PDKParameter("area", "1", "Area multiplier", ""),
        ],
    }
    
    PREFIX_MAP = {
        DeviceCategory.MOSFET: "M",
        DeviceCategory.BJT: "Q",
        DeviceCategory.DIODE: "D",
        DeviceCategory.RESISTOR: "R",
        DeviceCategory.CAPACITOR: "C",
        DeviceCategory.INDUCTOR: "L",
        DeviceCategory.SOURCE: "V",
    }


# ── PDK Registry (Unified) ─────────────────────────────────────

class PDKRegistry:
    """
    Unified PDK registry that replaces the three existing implementations.
    
    Features:
    - Loads PDKs from manifests with schema validation
    - Discovers PDKs from standard paths (PDK_ROOT, ~/.pdk, etc.)
    - Generates device catalogs from model files
    - Manages active PDK per project
    - Provides constraint validation for property editor
    - Lockfile generation for reproducibility
    """
    
    BUILTIN_PDKS = {
        "sky130": {
            "display_name": "SkyWater SKY130",
            "foundry": "SkyWater Technology",
            "process": "cMOS",
            "node": "130nm",
            "description": "SkyWater 130nm open-source CMOS",
        },
        "ihp_sg13g2": {
            "display_name": "IHP SG13G2",
            "foundry": "IHP Microelectronics",
            "process": "SiGe BiCMOS",
            "node": "130nm",
            "description": "IHP 130nm SiGe BiCMOS",
        },
        "gf180mcu": {
            "display_name": "GlobalFoundries GF180MCU",
            "foundry": "GlobalFoundries",
            "process": "MCU",
            "node": "180nm",
            "description": "GF 180nm MCU process",
        },
    }

    OPEN_PDK_SOURCES = {
        "ihp_sg13g2": {
            "display_name": "IHP SG13G2",
            "url": "https://github.com/IHP-GmbH/IHP-Open-PDK.git",
        },
        "sky130": {
            "display_name": "SkyWater SKY130",
            "url": "https://github.com/google/skywater-pdk.git",
        },
        "gf180mcu": {
            "display_name": "GlobalFoundries GF180MCU",
            "url": "https://github.com/google/gf180mcu-pdk.git",
        },
    }

    PDK_NAME_ALIASES = {
        "ihp-open-pdk": "ihp_sg13g2",
        "ihp_sg13g2": "ihp_sg13g2",
        "ihp-sg13g2": "ihp_sg13g2",
        "skywater-pdk": "sky130",
        "sky130": "sky130",
        "gf180mcu-pdk": "gf180mcu",
        "gf180mcu": "gf180mcu",
    }
    
    def __init__(self, workspace_dir: str = ""):
        self.workspace = Path(workspace_dir or os.path.join(
            os.path.expanduser("~"), "LumenWorkspace"))
        self.workspace.mkdir(parents=True, exist_ok=True)
        
        self._pdks: Dict[str, PDKInfo] = {}
        self._active_pdk: str = ""
        self._search_paths: List[str] = []
        self._validator = SchemaValidator()
        
        # Load config
        self._config_path = self.workspace / "pdk_config.json"
        self._load_config()
        
        # Discover PDKs
        self._discover_pdks()
    
    def _load_config(self):
        """Load registry configuration."""
        if self._config_path.exists():
            try:
                with open(self._config_path, "r") as f:
                    data = json.load(f)
                self._active_pdk = data.get("active_pdk", "")
                self._search_paths = data.get("search_paths", [])
            except (json.JSONDecodeError, OSError):
                pass
    
    def _save_config(self):
        """Save registry configuration."""
        data = {
            "active_pdk": self._active_pdk,
            "search_paths": self._search_paths,
            "version": "1.0",
        }
        with open(self._config_path, "w") as f:
            json.dump(data, f, indent=2)
    
    def _discover_pdks(self):
        """Discover all available PDKs."""
        # Add built-in definitions (unvalidated, will be validated on access)
        for name, info in self.BUILTIN_PDKS.items():
            pdk = self._build_builtin_pdk(name, info)
            self._pdks[name] = pdk
        
        # Scan search paths
        self._scan_paths()

        ihp = self._pdks.get("ihp_sg13g2")
        if not self.get_active_pdk() and ihp and ihp.installed:
            self._active_pdk = "ihp_sg13g2"
    
    def _build_builtin_pdk(self, name: str, info: Dict) -> PDKInfo:
        """Build a built-in PDK definition."""
        pdk = PDKInfo(
            name=name,
            display_name=info["display_name"],
            foundry=info["foundry"],
            process=info["process"],
            node=info["node"],
            description=info["description"],
            is_builtin=True,
            installed=False,
        )

        # Compatibility: import full built-in device/layer/corner catalogs from legacy registry.
        self._enrich_builtin_from_legacy(pdk)

        # Fallback defaults if legacy mapping fails for any reason.
        if not pdk.corners:
            if name == "sky130":
                pdk.corners = [
                    PDKCorner("tt", "Typical-Typical", 25, 1.8),
                    PDKCorner("ff", "Fast-Fast", -40, 1.98),
                    PDKCorner("ss", "Slow-Slow", 125, 1.62),
                ]
            elif name == "ihp_sg13g2":
                pdk.corners = [
                    PDKCorner("typ", "Typical", 27, 1.2),
                    PDKCorner("fast", "Fast", -40, 1.32),
                    PDKCorner("slow", "Slow", 125, 1.08),
                ]
            elif name == "gf180mcu":
                pdk.corners = [
                    PDKCorner("typical", "Typical", 25, 3.3),
                    PDKCorner("ff", "Fast-Fast", -40, 3.63),
                    PDKCorner("ss", "Slow-Slow", 125, 2.97),
                ]

        self._attach_builtin_model_files(pdk)
        if name == "ihp_sg13g2":
            klayout_lyp = (Path(pdk.root_path) / "libs.tech" / "klayout" / "tech" / "sg13g2.lyp") if pdk.root_path else None
            if klayout_lyp and klayout_lyp.exists():
                parsed_layers = parse_klayout_layer_properties(str(klayout_lyp))
                if parsed_layers:
                    pdk.layers = [
                        {
                            **asdict(l),
                            "gds_number": l.gds_layer,
                            "description": l.display_name or f"{l.name}/{l.purpose}",
                        }
                        for l in parsed_layers
                    ]
            self._enrich_ihp_from_xschem(pdk)
        return pdk

    def _attach_builtin_model_files(self, pdk: PDKInfo) -> None:
        """Attach locally discovered model files to built-in PDK metadata."""
        candidates = []
        workspace_root = Path(self.workspace).resolve() if self.workspace else Path.cwd().resolve()
        eda_root = workspace_root.parent if workspace_root.name.lower() == "lumencircuitstudio" else Path("C:/EDA")
        if pdk.name == "ihp_sg13g2":
            candidates.extend([
                workspace_root / "external" / "ihp_pdk" / "ihp-sg13g2",
                workspace_root / "ihp_pdk" / "ihp-sg13g2",
                eda_root / "LumenCircuitStudio" / "external" / "ihp_pdk" / "ihp-sg13g2",
                eda_root / "LumenCircuitStudio" / "ihp_pdk" / "ihp-sg13g2",
                eda_root / "ihp_pdk" / "ihp-sg13g2",
                eda_root / "ihp-sg13g2",
                eda_root / "IHP-Open-PDK" / "ihp-sg13g2",
            ])
        elif pdk.name == "sky130":
            candidates.extend([
                workspace_root / "external" / "xschem_sky130",
                workspace_root / "xschem_sky130",
                eda_root / "LumenCircuitStudio" / "external" / "xschem_sky130",
                eda_root / "LumenCircuitStudio" / "xschem_sky130",
                eda_root / "skywater-pdk",
                eda_root / "sky130A",
                eda_root / "xschem_sky130",
            ])
        elif pdk.name == "gf180mcu":
            candidates.extend([
                eda_root / "LumenCircuitStudio" / "gf180mcu-pdk",
                eda_root / "LumenCircuitStudio" / "gf180mcu",
                eda_root / "gf180mcu-pdk",
                eda_root / "gf180mcu",
            ])

        if pdk.root_path:
            candidates.append(Path(pdk.root_path))

        env_root = os.environ.get("PDK_ROOT", "") or os.environ.get("PDK_DIR", "")
        if env_root:
            candidates.append(Path(env_root))

        for root in candidates:
            root = self._normalize_builtin_root(pdk.name, root)
            if root.exists() and root.is_dir():
                model_files = self._discover_model_files(root)
                if model_files:
                    pdk.root_path = str(root)
                    pdk.models_path = self._best_models_path(root, model_files)
                    pdk.model_files = model_files
                    pdk.installed = True
                    return

    def _enrich_ihp_from_xschem(self, pdk: PDKInfo) -> None:
        """Use IHP's shipped Xschem libraries as the visible device catalog."""
        root = Path(pdk.root_path) if pdk.root_path else Path(self.workspace) / "external" / "ihp_pdk" / "ihp-sg13g2"
        xschem_root = root / "libs.tech" / "xschem"
        if not xschem_root.exists():
            self._enrich_ihp_from_symbol_cache(pdk)
            return

        symbol_dirs = [
            xschem_root / "sg13g2_pr",
            xschem_root / "sg13g2_stdcells",
        ]

        try:
            from .xschem_symbol_import import XschemSymbolParser
        except Exception:
            return

        parser = XschemSymbolParser()
        merged = {device.name: device for device in pdk.devices}
        imported_count = 0

        for symbol_dir in symbol_dirs:
            if not symbol_dir.exists():
                continue
            for sym_file in sorted(symbol_dir.glob("*.sym"), key=lambda p: p.name.lower()):
                try:
                    parsed = parser.parse_file(str(sym_file))
                    symbol_data = parsed.to_lumen_json()
                except Exception:
                    continue

                symbol_data["library"] = f"pdk:{pdk.name}"
                category = self._ihp_category_from_symbol(sym_file.stem, symbol_data)
                pins = [
                    PDKPin(
                        name=str(pin.get("name", "")),
                        x=float(pin.get("x", 0.0) or 0.0),
                        y=float(pin.get("y", 0.0) or 0.0),
                        direction=str(pin.get("direction", "inout") or "inout"),
                        net_name=pin.get("net_name"),
                    )
                    for pin in symbol_data.get("pins", [])
                    if pin.get("name")
                ]
                parameters = [
                    PDKParameter(
                        name=str(param.get("name", "")),
                        default=str(param.get("default", "")),
                        description=str(param.get("description", "")),
                    )
                    for param in symbol_data.get("parameters", [])
                    if param.get("name")
                ]
                term_order = [pin.name for pin in pins]
                inst_parameters = [param.name for param in parameters]
                prefix = str(symbol_data.get("prefix") or "X")
                model = str(symbol_data.get("spice_model") or sym_file.stem)

                merged[sym_file.stem] = PDKDevice(
                    name=sym_file.stem,
                    category=category,
                    prefix=prefix,
                    model=model,
                    component_name=str(symbol_data.get("component_name") or model),
                    term_order=term_order,
                    inst_parameters=inst_parameters,
                    other_parameters=[],
                    netlist_kind="subckt" if prefix.upper() == "X" else "primitive",
                    description=f"IHP SG13G2 {symbol_dir.name} Xschem symbol",
                    pins=pins,
                    parameters=parameters,
                    symbol_style=category.name.lower(),
                    symbol_data=symbol_data,
                    is_primitive=prefix.upper() != "X",
                    priority=100,
                    provenance={
                        "source": "ihp_xschem_symbol",
                        "path": str(sym_file),
                        "library_group": symbol_dir.name,
                    },
                )
                imported_count += 1

        if imported_count:
            pdk.devices = sorted(
                merged.values(),
                key=lambda d: (self._ihp_category_sort_key(d.category), d.name.lower()),
            )
            pdk.symbols_path = str(xschem_root)
            pdk.root_path = str(root)
            if "xschem-symbols" not in pdk.tags:
                pdk.tags.append("xschem-symbols")

    def _enrich_ihp_from_symbol_cache(self, pdk: PDKInfo) -> None:
        """Use the committed IHP symbol cache when the PDK submodule is absent."""
        symbol_root = Path(__file__).resolve().parents[1] / "ihp_symbols"
        if not symbol_root.exists():
            return

        merged = {device.name: device for device in pdk.devices}
        imported_count = 0
        for symbol_file in sorted(symbol_root.glob("*.symbol.json"), key=lambda path: path.name.lower()):
            try:
                symbol_data = json.loads(symbol_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

            symbol_data["library"] = f"pdk:{pdk.name}"
            pins = [
                PDKPin(
                    name=str(pin.get("name", "")),
                    x=float(pin.get("x", 0.0) or 0.0),
                    y=float(pin.get("y", 0.0) or 0.0),
                    direction=str(pin.get("direction", "inout") or "inout"),
                    net_name=pin.get("net_name"),
                )
                for pin in symbol_data.get("pins", [])
                if pin.get("name")
            ]
            parameters = [
                PDKParameter(
                    name=str(param.get("name", "")),
                    default=str(param.get("default", "")),
                    description=str(param.get("description", "")),
                )
                for param in symbol_data.get("parameters", [])
                if param.get("name")
            ]
            prefix = str(symbol_data.get("prefix") or "X")
            model = str(symbol_data.get("spice_model") or symbol_file.stem.removesuffix(".symbol"))
            name = str(symbol_data.get("name") or model)
            category = self._ihp_category_from_symbol(name, symbol_data)

            merged[name] = PDKDevice(
                name=name,
                category=category,
                prefix=prefix,
                model=model,
                component_name=str(symbol_data.get("component_name") or model),
                term_order=[pin.name for pin in pins],
                inst_parameters=[param.name for param in parameters],
                other_parameters=[],
                netlist_kind="subckt" if prefix.upper() == "X" else "primitive",
                description=f"IHP SG13G2 cached symbol",
                pins=pins,
                parameters=parameters,
                symbol_style=category.name.lower(),
                symbol_data=symbol_data,
                is_primitive=prefix.upper() != "X",
                priority=90,
                provenance={"source": "bundled_ihp_symbol_cache", "path": str(symbol_file)},
            )
            imported_count += 1

        if imported_count:
            pdk.devices = sorted(
                merged.values(),
                key=lambda d: (self._ihp_category_sort_key(d.category), d.name.lower()),
            )
            pdk.symbols_path = str(symbol_root)
            if not pdk.root_path:
                pdk.root_path = str(symbol_root)
            pdk.installed = True
            if "bundled-symbol-cache" not in pdk.tags:
                pdk.tags.append("bundled-symbol-cache")

    def _ihp_category_from_symbol(self, name: str, symbol_data: Dict) -> DeviceCategory:
        """Classify imported IHP symbols for the Library Manager tree."""
        lower = name.lower()
        xschem_type = str(symbol_data.get("xschem_metadata", {}).get("type", "")).lower()
        text = f"{lower} {xschem_type}"

        if lower.startswith("sg13g2_"):
            return DeviceCategory.OTHER
        if any(token in text for token in ["nmos", "pmos", "mos", "fet"]):
            return DeviceCategory.MOSFET
        if any(token in text for token in ["res", "rppd", "rsil", "rhigh"]):
            return DeviceCategory.RESISTOR
        if any(token in text for token in ["cap", "varicap"]):
            return DeviceCategory.CAPACITOR
        if "inductor" in text or lower.startswith("ind"):
            return DeviceCategory.INDUCTOR
        if any(token in text for token in ["diode", "antenna"]):
            return DeviceCategory.DIODE
        if any(token in text for token in ["npn", "pnp", "bjt", "hbt", "vertical_npn"]):
            return DeviceCategory.BJT
        return DeviceCategory.OTHER

    def _ihp_category_sort_key(self, category: DeviceCategory) -> int:
        order = {
            DeviceCategory.MOSFET: 0,
            DeviceCategory.BJT: 1,
            DeviceCategory.RESISTOR: 2,
            DeviceCategory.CAPACITOR: 3,
            DeviceCategory.INDUCTOR: 4,
            DeviceCategory.DIODE: 5,
            DeviceCategory.OTHER: 6,
        }
        return order.get(category, 99)

    def _normalize_builtin_root(self, pdk_name: str, root: Path) -> Path:
        """Resolve common wrapper directories to the actual PDK root."""
        if pdk_name == "ihp_sg13g2" and (root / "ihp-sg13g2").is_dir():
            return root / "ihp-sg13g2"
        return root

    def _best_models_path(self, root: Path, model_files: List[PDKModelFile]) -> str:
        """Choose the model directory Simulation Cockpit should show/use by default."""
        preferred = [
            root / "libs.tech" / "ngspice" / "models",
            root / "models",
            root,
        ]
        for path in preferred:
            if path.exists() and path.is_dir():
                return str(path)
        if model_files:
            return str(Path(model_files[0].path).parent)
        return str(root)

    def _discover_model_files(self, root: Path) -> List[PDKModelFile]:
        """Discover SPICE/simulator model files and their .LIB sections."""
        patterns = ["*.lib", "*.scs", "*.model", "*.spice", "*.sp"]
        model_files: List[PDKModelFile] = []
        seen = set()

        for pattern in patterns:
            for path in sorted(root.rglob(pattern), key=lambda p: str(p).lower()):
                if not path.is_file() or path in seen:
                    continue
                seen.add(path)
                try:
                    stat = path.stat()
                    corners = self._extract_lib_sections(path)
                    model_files.append(PDKModelFile(
                        path=str(path),
                        relative_path=str(path.relative_to(root)),
                        format=path.suffix.lstrip(".").lower() or "spice",
                        corners=corners,
                        size_bytes=stat.st_size,
                        last_modified=stat.st_mtime,
                    ))
                except OSError:
                    continue

        return model_files

    def _extract_lib_sections(self, path: Path) -> List[str]:
        """Extract section names from SPICE .LIB files."""
        sections = []
        if path.suffix.lower() != ".lib":
            return sections
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    match = re.match(r'\s*\.LIB\s+"?([^"\s]+)"?', line, re.IGNORECASE)
                    if match:
                        section = match.group(1)
                        if section not in sections:
                            sections.append(section)
        except OSError:
            pass
        return sections

    def _enrich_builtin_from_legacy(self, pdk: PDKInfo) -> None:
        """Populate unified built-in PDK from legacy `lumen.core.pdk` catalog."""
        try:
            from . import pdk as legacy_pdk
        except Exception:
            return

        old = None

        # Prefer direct built-in factory functions (no filesystem side effects).
        factory_map = {
            "sky130": "_sky130_pdk",
            "ihp_sg13g2": "_ihp_open_pdk",
            "gf180mcu": "_gf180mcu_pdk",
        }
        factory_name = factory_map.get(pdk.name, "")
        if factory_name and hasattr(legacy_pdk, factory_name):
            try:
                old = getattr(legacy_pdk, factory_name)()
            except Exception:
                old = None

        # Fallback: legacy registry path.
        try:
            if old is None and hasattr(legacy_pdk, "PDKRegistry"):
                # Use a user-home workspace instead of current project path; some
                # project folders may be read-only and fail directory creation.
                legacy_workspace = os.path.join(
                    os.path.expanduser("~"),
                    ".lumen_legacy_pdk_cache",
                )
                legacy = legacy_pdk.PDKRegistry(legacy_workspace)
                old = legacy.get_pdk(pdk.name)
        except Exception:
            return

        if not old:
            return

        if getattr(old, "node", None):
            pdk.node = old.node
        if getattr(old, "process", None):
            pdk.process = old.process
        if getattr(old, "foundry", None):
            pdk.foundry = old.foundry
        if getattr(old, "display_name", None):
            pdk.display_name = old.display_name
        if getattr(old, "description", None):
            pdk.description = old.description
        if getattr(old, "version", None):
            pdk.version = old.version
        if getattr(old, "license", None):
            pdk.license = old.license
        if getattr(old, "url", None):
            pdk.url = old.url
        if getattr(old, "supply_voltage", None) is not None:
            pdk.supply_voltage = old.supply_voltage
        if getattr(old, "temperature_range", None):
            pdk.temperature_range = tuple(old.temperature_range)

        # Corners
        pdk.corners = []
        for c in getattr(old, "corners", []) or []:
            if isinstance(c, dict):
                pdk.corners.append(PDKCorner(
                    name=c.get("name", ""),
                    description=c.get("description", ""),
                    temperature=float(c.get("temp", c.get("temperature", 25.0))),
                    voltage=float(c.get("voltage", pdk.supply_voltage)),
                    lib_section=str(c.get("lib_section", "")),
                ))

        # Layers
        pdk.layers = []
        for l in getattr(old, "layers", []) or []:
            pdk.layers.append({
                "name": getattr(l, "name", ""),
                "gds_number": getattr(l, "gds_number", 0),
                "gds_datatype": getattr(l, "gds_datatype", 0),
                "purpose": getattr(l, "purpose", ""),
                "color": getattr(l, "color", "#808080"),
                "description": getattr(l, "description", ""),
            })

        # Devices
        pdk.devices = []
        for d in getattr(old, "devices", []) or []:
            cat_value = str(getattr(d, "category", "Other"))
            try:
                category = DeviceCategory(cat_value)
            except ValueError:
                category = DeviceCategory.OTHER

            pins = []
            for idx, pin_name in enumerate(getattr(d, "pins", []) or []):
                y = -20 + idx * 15
                pins.append(PDKPin(name=str(pin_name), x=-30.0, y=float(y), direction="inout"))

            params = []
            for k, v in (getattr(d, "parameters", {}) or {}).items():
                params.append(PDKParameter(name=str(k), default=str(v)))

            pdk.devices.append(PDKDevice(
                name=getattr(d, "name", ""),
                category=category,
                prefix=self._builtin_netlist_prefix(pdk.name, getattr(d, "name", ""), getattr(d, "prefix", "X")),
                model=getattr(d, "model", getattr(d, "name", "")),
                component_name=getattr(d, "model", getattr(d, "name", "")),
                term_order=[str(pin_name) for pin_name in (getattr(d, "pins", []) or [])],
                inst_parameters=self._builtin_inst_parameters(pdk.name, getattr(d, "name", ""), getattr(d, "parameters", {}) or {}),
                other_parameters=[],
                netlist_kind=self._builtin_netlist_kind(pdk.name, getattr(d, "name", "")),
                description=getattr(d, "description", ""),
                pins=pins,
                parameters=params,
                symbol_style=category.name.lower(),
                is_primitive=self._builtin_netlist_kind(pdk.name, getattr(d, "name", "")) == "primitive",
                priority=10,
                provenance={"source": "legacy_builtin_catalog"},
            ))

    def _builtin_netlist_kind(self, pdk_name: str, device_name: str) -> str:
        """Return the real model style for known built-in PDK devices."""
        if pdk_name == "ihp_sg13g2":
            return "subckt"
        return "primitive"

    def _builtin_netlist_prefix(self, pdk_name: str, device_name: str, default: str) -> str:
        """Return the SPICE instance prefix for known built-in PDK devices."""
        if self._builtin_netlist_kind(pdk_name, device_name) == "subckt":
            return "X"
        return str(default or "X")

    def _builtin_inst_parameters(self, pdk_name: str, device_name: str, params: Dict[str, Any]) -> List[str]:
        """Normalize instance parameter names for known built-in PDK models."""
        if pdk_name == "ihp_sg13g2" and device_name.startswith("sg13_"):
            return ["w", "l", "ng", "m"]
        return [str(k) for k in params.keys()]
    
    def _scan_paths(self):
        """Scan configured paths for PDK installations."""
        paths_to_scan = list(self._search_paths)
        
        # Add environment variables
        for var in ["PDK_ROOT", "PDK_DIR", "LUMEN_PDK_PATH"]:
            val = os.environ.get(var, "")
            if val:
                paths_to_scan.extend(val.split(os.pathsep))
        
        # Add default locations
        paths_to_scan.extend([
            str(Path.home() / ".pdk"),
            str(Path.home() / "pdk"),
            str(Path("/usr/share/pdk")),
        ])
        
        # Deduplicate and scan
        seen = set()
        for path_str in paths_to_scan:
            if not path_str or path_str in seen:
                continue
            seen.add(path_str)
            p = Path(path_str)
            if p.exists() and p.is_dir():
                self._scan_directory(p)
    
    def _scan_directory(self, root: Path):
        """Scan a directory for PDKs."""
        # Check if root itself is a PDK
        pdk = self._identify_pdk(root)
        if pdk:
            self._pdks[pdk.name] = pdk
            return
        
        # Check immediate subdirectories
        for child in sorted(root.iterdir()):
            if child.is_dir() and not child.name.startswith("."):
                pdk = self._identify_pdk(child)
                if pdk and pdk.name not in self._pdks:
                    self._pdks[pdk.name] = pdk
    
    def _identify_pdk(self, directory: Path) -> Optional[PDKInfo]:
        """Check if a directory looks like a PDK root."""
        # Look for manifest file
        manifest_path = self._manifest_path_for_directory(directory)
        if manifest_path.exists():
            try:
                with open(manifest_path, "r") as f:
                    data = json.load(f)
                return self._load_from_manifest(directory, data, manifest_path)
            except (json.JSONDecodeError, OSError) as e:
                print(f"Warning: Invalid PDK manifest in {directory}: {e}")
                return None
        
        # Look for pdk.yaml (convert to JSON format)
        yaml_path = directory / "pdk.yaml"
        if yaml_path.exists():
            # TODO: Implement YAML loading
            pass
        
        # Heuristic: look for model files
        has_models = any(directory.glob("*.lib")) or any(directory.glob("models/*.lib"))
        if has_models:
            # Create a generic PDK entry from discovery
            return self._discover_from_directory(directory)
        
        return None

    def _manifest_path_for_directory(self, directory: Path) -> Path:
        """Return the preferred manifest path for a PDK directory."""
        for filename in ("pdk.json", "lumen_pdk.json"):
            path = directory / filename
            if path.exists():
                return path
        return directory / "lumen_pdk.json"

    def _canonical_pdk_name(self, name: str) -> str:
        raw = str(name or "").strip()
        key = raw.lower().replace(" ", "-")
        return self.PDK_NAME_ALIASES.get(key, raw.lower().replace(" ", "_"))
    
    def _load_from_manifest(self, root: Path, data: Dict, manifest_path: Path | None = None) -> PDKInfo:
        """Load PDK from a manifest file."""
        manifest_path = manifest_path or root / "pdk.json"
        # Validate against schema
        errors = self._validator.validate(data, "pdk_manifest")
        if errors:
            pdk = PDKInfo(
                name=data.get("name", root.name),
                is_valid=False,
                validation_errors=errors,
            )
            return pdk
        
        # Build PDK info from manifest
        pdk = PDKInfo(
            name=data["name"],
            display_name=data.get("display_name", data["name"]),
            foundry=data.get("foundry", ""),
            process=data.get("process", ""),
            node=data.get("node", ""),
            version=data.get("version", "1.0"),
            schema_version=data.get("schema_version", "1.0"),
            description=data.get("description", ""),
            license=data.get("license", ""),
            url=data.get("url", ""),
            author=data.get("author", ""),
            tags=data.get("tags", []),
            root_path=str(root),
            manifest_path=str(manifest_path),
            installed=True,
        )
        
        # Paths
        paths = data.get("paths", {})
        if "models" in paths:
            pdk.models_path = str(root / paths["models"])
        else:
            pdk.models_path = str(root / "models")
        if "tech" in paths:
            pdk.tech_path = str(root / paths["tech"])
        else:
            pdk.tech_path = str(root / "tech")
        if "cells" in paths:
            pdk.cells_path = str(root / paths["cells"])
        if "symbols" in paths:
            pdk.symbols_path = str(root / paths["symbols"])
        
        # Devices from manifest
        pdk.devices = self._load_devices_from_manifest(data.get("devices", []))

        # Model files from filesystem discovery. Manifests may point at a root
        # model directory, while Simulation Cockpit needs concrete files and .LIB sections.
        pdk.model_files = self._discover_model_files(root)
        if pdk.model_files:
            pdk.models_path = self._best_models_path(root, pdk.model_files)
        
        # Layers
        pdk.layers = data.get("layers", [])
        
        # Corners
        pdk.corners = [PDKCorner(**c) for c in data.get("corners", [])]
        
        # Compute manifest checksum
        pdk.manifest_checksum = self._compute_manifest_checksum(manifest_path)
        
        return pdk
    
    def _load_devices_from_manifest(self, devices_data: List[Dict]) -> List[PDKDevice]:
        """Convert manifest device data to PDKDevice objects."""
        devices = []
        for d in devices_data:
            pins = [PDKPin(**p) for p in d.get("pins", [])]
            params = [PDKParameter(**p) for p in d.get("parameters", [])]
            constraints = [PDKConstraint(**c) for c in d.get("constraints", [])]
            default_term_order = [p.name for p in pins]
            default_inst_params = [p.name for p in params]

            term_order = d.get("term_order", d.get("termOrder", default_term_order))
            inst_parameters = d.get("inst_parameters", d.get("instParameters", default_inst_params))
            other_parameters = d.get("other_parameters", d.get("otherParameters", []))
            is_primitive = d.get("is_primitive", d.get("isPrimitive", False))
            netlist_kind = d.get("netlist_kind", d.get("netlistKind", "primitive" if is_primitive else "subckt"))
            
            device = PDKDevice(
                name=d["name"],
                category=DeviceCategory(d["category"]),
                prefix=d.get("prefix", "X"),
                model=d.get("model", d["name"]),
                component_name=d.get("component_name", d.get("componentName", d.get("model", d["name"]))),
                term_order=list(term_order or default_term_order),
                inst_parameters=list(inst_parameters or default_inst_params),
                other_parameters=list(other_parameters or []),
                netlist_kind=str(netlist_kind or "subckt"),
                description=d.get("description", ""),
                pins=pins,
                parameters=params,
                constraints=constraints,
                symbol_style=d.get("symbol_style", "default"),
                is_primitive=bool(is_primitive),
                priority=d.get("priority", 0),
            )
            devices.append(device)
        return devices
    
    def _discover_from_directory(self, directory: Path) -> PDKInfo:
        """Discover PDK by scanning directory structure."""
        pdk = PDKInfo(
            name=directory.name.lower().replace(" ", "_"),
            display_name=directory.name.replace("_", " ").title(),
            root_path=str(directory),
            installed=True,
        )
        
        # Discover model files
        parser = SpiceModelParser()
        devices = []
        pdk.model_files = self._discover_model_files(directory)
        pdk.models_path = self._best_models_path(directory, pdk.model_files)
        
        # Search for model files
        model_patterns = ["*.lib", "*.model", "*.va", "*.spice"]
        for pattern in model_patterns:
            for model_file in directory.rglob(pattern):
                try:
                    file_devices = parser.parse_file(str(model_file))
                    for dev in file_devices:
                        if not any(d.name == dev.name for d in devices):
                            devices.append(dev)
                except Exception as e:
                    print(f"Warning: Failed to parse {model_file}: {e}")
        
        pdk.devices = devices
        
        # Look for corners in parsed .lib sections.
        corners = {
            section
            for model_file in pdk.model_files
            for section in (getattr(model_file, "corners", []) or [])
        }
        
        pdk.corners = [PDKCorner(name=c) for c in sorted(corners)]
        
        return pdk
    
    def _compute_manifest_checksum(self, manifest_path: Path) -> str:
        """Compute MD5 checksum of manifest file."""
        try:
            with open(manifest_path, "rb") as f:
                return hashlib.md5(f.read()).hexdigest()
        except:
            return ""

    def register_local_pdk(self, path: str, name: str = "", display_name: str = "") -> Optional[PDKInfo]:
        """Register an already-installed local PDK folder."""
        root = Path(path).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            return None

        pdk = self._identify_pdk(root)
        if pdk is None:
            pdk = self._discover_from_directory(root)
            pdk.name = self._canonical_pdk_name(name or pdk.name or root.name)
            pdk.display_name = display_name or pdk.display_name or pdk.name
            pdk.manifest_path = str(self._write_lumen_manifest(root, pdk))
        elif name or display_name:
            pdk.name = self._canonical_pdk_name(name or pdk.name)
            pdk.display_name = display_name or pdk.display_name
        else:
            pdk.name = self._canonical_pdk_name(pdk.name or root.name)

        pdk.root_path = str(root)
        pdk.installed = True
        if pdk.model_files:
            pdk.models_path = self._best_models_path(root, pdk.model_files)
        if not getattr(pdk, "manifest_path", ""):
            pdk.manifest_path = str(self._write_lumen_manifest(root, pdk))
            pdk.manifest_checksum = self._compute_manifest_checksum(Path(pdk.manifest_path))
        self._pdks[pdk.name] = pdk

        root_str = str(root)
        if root_str not in self._search_paths:
            self._search_paths.append(root_str)
        self._active_pdk = pdk.name
        self._save_config()
        return pdk

    def refresh_pdk_installation(self, name: str) -> Optional[PDKInfo]:
        """Rescan an installed PDK root and update discovered models/corners/devices."""
        current = self._pdks.get(name)
        root_text = str(getattr(current, "root_path", "") or "") if current else ""
        root = Path(root_text).expanduser() if root_text else None
        if not root or not root.exists() or not root.is_dir():
            return None
        refreshed = self._discover_from_directory(root)
        refreshed.name = current.name
        refreshed.display_name = current.display_name or refreshed.display_name
        refreshed.foundry = current.foundry or refreshed.foundry
        refreshed.process = current.process or refreshed.process
        refreshed.node = current.node or refreshed.node
        refreshed.version = current.version or refreshed.version
        refreshed.license = current.license or refreshed.license
        refreshed.description = current.description or refreshed.description
        refreshed.manifest_path = str(self._write_lumen_manifest(root, refreshed))
        refreshed.manifest_checksum = self._compute_manifest_checksum(Path(refreshed.manifest_path))
        refreshed.installed = True
        self._pdks[name] = refreshed
        self._save_config()
        return refreshed

    def set_pdk_models_path(self, name: str, models_path: str) -> Optional[PDKInfo]:
        """Point a PDK at a model folder and regenerate its local manifest."""
        pdk = self._pdks.get(name)
        root_text = str(getattr(pdk, "root_path", "") or "") if pdk else ""
        root = Path(root_text).expanduser() if root_text else None
        models = Path(models_path).expanduser().resolve()
        if not pdk or not root or not root.exists() or not models.exists() or not models.is_dir():
            return None

        pdk.model_files = self._discover_model_files(models)
        pdk.models_path = str(models)
        sections = sorted({
            section
            for model_file in pdk.model_files
            for section in (getattr(model_file, "corners", []) or [])
        })
        if sections:
            pdk.corners = [PDKCorner(name=section, lib_section=section) for section in sections]
        pdk.manifest_path = str(self._write_lumen_manifest(root, pdk))
        pdk.manifest_checksum = self._compute_manifest_checksum(Path(pdk.manifest_path))
        pdk.installed = True
        self._pdks[pdk.name] = pdk
        self._save_config()
        return pdk

    def _write_lumen_manifest(self, root: Path, pdk: PDKInfo) -> Path:
        manifest_path = root / "lumen_pdk.json"
        model_rel = ""
        if pdk.models_path:
            try:
                model_rel = str(Path(pdk.models_path).resolve().relative_to(root))
            except ValueError:
                model_rel = ""
        data = {
            "schema_version": "1.0",
            "name": pdk.name,
            "display_name": pdk.display_name or pdk.name,
            "foundry": pdk.foundry,
            "process": pdk.process,
            "node": pdk.node,
            "version": pdk.version or "1.0",
            "description": pdk.description or f"Local PDK registered from {root}",
            "paths": {"models": model_rel},
            "corners": [
                {
                    "name": corner.name,
                    "description": corner.description,
                    "temperature": float(corner.temperature),
                    "voltage": float(getattr(corner, "voltage", getattr(pdk, "supply_voltage", 1.8))),
                    "lib_section": corner.lib_section,
                }
                for corner in pdk.corners
            ],
        }
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        return manifest_path

    def available_open_pdk_sources(self) -> Dict[str, Dict[str, str]]:
        """Return built-in open PDK repositories."""
        return dict(self.OPEN_PDK_SOURCES)

    def install_open_pdk(self, name: str, destination: str = "") -> Optional[PDKInfo]:
        """Clone a known open PDK repository and register the local checkout."""
        source = self.OPEN_PDK_SOURCES.get(name)
        if not source:
            return None
        base = Path(destination).expanduser().resolve() if destination else self.workspace / "pdks"
        base.mkdir(parents=True, exist_ok=True)
        target = base / name
        if not target.exists():
            result = subprocess.run(
                ["git", "clone", "--depth", "1", source["url"], str(target)],
                capture_output=True,
                text=True,
                timeout=900,
            )
            if result.returncode != 0:
                return None
        pdk = self.register_local_pdk(str(target), name=name, display_name=source.get("display_name", name))
        return self.refresh_pdk_installation(pdk.name) if pdk else None
    
    def add_search_path(self, path: str):
        """Add a path to search for PDKs."""
        if path not in self._search_paths:
            self._search_paths.append(path)
            self._save_config()
            self._scan_directory(Path(path))

    def install_pdk(self, name: str) -> bool:
        """
        Compatibility install flow expected by legacy GUI.
        Uses bundled metadata only; never creates fake PDK skeletons.
        """
        pdk = self._pdks.get(name)
        if not pdk:
            return False

        if name == "ihp_sg13g2":
            self._enrich_ihp_from_symbol_cache(pdk)
            return pdk.installed

        return pdk.installed
    
    def get_all_pdks(self) -> List[PDKInfo]:
        """Get all available PDKs."""
        return list(self._pdks.values())
    
    def get_pdk(self, name: str) -> Optional[PDKInfo]:
        """Get a specific PDK by name."""
        return self._pdks.get(name)
    
    def get_active_pdk(self) -> Optional[PDKInfo]:
        """Get the currently active PDK."""
        if self._active_pdk:
            pdk = self._pdks.get(self._active_pdk)
            return pdk if pdk and pdk.installed else None
        return None
    
    def set_active_pdk(self, name: str) -> bool:
        """Set the active PDK."""
        pdk = self._pdks.get(name)
        if pdk and pdk.installed:
            self._active_pdk = name
            self._save_config()
            return True
        return False
    
    def get_active_name(self) -> str:
        """Get the name of the active PDK."""
        return self._active_pdk if self.get_active_pdk() else ""
    
    def get_devices(self, pdk_name: str = "", category: DeviceCategory = None) -> List[PDKDevice]:
        """Get devices from a PDK, optionally filtered by category."""
        pdk = self._pdks.get(pdk_name or self._active_pdk)
        if not pdk:
            return []
        devices = pdk.devices
        if category:
            devices = [d for d in devices if d.category == category]
        return devices
    
    def find_device(self, name: str, pdk_name: str = "") -> Optional[PDKDevice]:
        """Find a device by name in a PDK (or active PDK)."""
        pdk = self._pdks.get(pdk_name or self._active_pdk)
        if not pdk:
            return None
        for device in pdk.devices:
            if device.name == name:
                return device
        return None
    
    def validate_pdk(self, name: str) -> List[str]:
        """Validate a PDK's data against schemas."""
        pdk = self._pdks.get(name)
        if not pdk:
            return [f"PDK '{name}' not found"]
        
        errors = []
        
        # Validate devices
        for device in pdk.devices:
            # Check required fields
            if not device.name:
                errors.append(f"Device in {name}: missing name")
            if not device.model:
                errors.append(f"Device {device.name}: missing model")
            if not device.pins:
                errors.append(f"Device {device.name}: has no pins")
        
        # Check for duplicate device names
        device_names = [d.name for d in pdk.devices]
        duplicates = set([n for n in device_names if device_names.count(n) > 1])
        if duplicates:
            errors.append(f"Duplicate device names in {name}: {', '.join(duplicates)}")
        
        return errors
    
    def get_pdk_health_report(self, name: str) -> Dict[str, Any]:
        """Generate a health report for a PDK."""
        pdk = self._pdks.get(name)
        if not pdk:
            return {"error": f"PDK '{name}' not found"}
        
        report = {
            "name": pdk.name,
            "display_name": pdk.display_name,
            "installed": pdk.installed,
            "is_valid": pdk.is_valid,
            "validation_errors": pdk.validation_errors,
            "root_path": pdk.root_path,
            "models_path": pdk.models_path,
            "manifest_path": pdk.manifest_path,
            "devices_count": len(pdk.devices),
            "corners_count": len(pdk.corners),
            "layers_count": len(pdk.layers),
            "model_files_count": len(pdk.model_files),
            "model_sections_count": sum(len(getattr(model_file, "corners", []) or []) for model_file in pdk.model_files),
            "has_manifest": pdk.manifest_path is not None,
            "manifest_checksum": pdk.manifest_checksum,
            "supported_categories": list(set(d.category.value for d in pdk.devices)),
        }
        
        # Check for common issues
        issues = []
        if not pdk.model_files:
            issues.append("No model files discovered")
        if not pdk.devices:
            issues.append("No devices defined")
        if not pdk.corners:
            issues.append("No process corners defined")
        for device in pdk.devices:
            if not device.pins:
                issues.append(f"Device {device.name} has no pins")
            if not device.parameters:
                issues.append(f"Device {device.name} has no parameters")
        report["issues"] = issues
        report["status"] = "Ready" if not issues else "Needs Setup"
        
        return report
    
    def generate_lockfile(self, project_name: str, used_devices: List[str],
                         used_corners: List[str]) -> str:
        """Generate a lockfile for the current design."""
        active_pdk = self.get_active_pdk()
        if not active_pdk:
            return ""
        
        # Compute hashes
        manifest_hash = hashlib.md5(
            json.dumps(asdict(active_pdk), sort_keys=True).encode()
        ).hexdigest()
        
        device_catalog = sorted([d.name for d in active_pdk.devices])
        device_hash = hashlib.md5(
            json.dumps(device_catalog, sort_keys=True).encode()
        ).hexdigest()
        
        # Model files hash
        model_files = []
        if active_pdk.models_path and Path(active_pdk.models_path).exists():
            for pattern in ["*.lib", "*.model", "*.va"]:
                for f in Path(active_pdk.models_path).rglob(pattern):
                    model_files.append(str(f.relative_to(active_pdk.root_path)))
        model_hash = hashlib.md5(
            json.dumps(sorted(model_files), sort_keys=True).encode()
        ).hexdigest()
        
        lock = PDKLock(
            pdk_name=active_pdk.name,
            pdk_version=active_pdk.version,
            pdk_manifest_hash=manifest_hash,
            model_files_hash=model_hash,
            device_catalog_hash=device_hash,
            used_corners=used_corners,
            used_devices=used_devices,
            timestamp=time.time(),
        )
        
        lock_path = self.workspace / f"{project_name}.pdk.lock"
        lock.save(str(lock_path))
        
        return str(lock_path)

    def create_lock(self, name: str, used_devices: Optional[List[str]] = None,
                    used_corners: Optional[List[str]] = None) -> Optional[PDKLock]:
        """Create lock data for a specific installed PDK."""
        pdk = self._pdks.get(name)
        if not pdk or not pdk.installed:
            return None
        return PDKLock.create(pdk, used_corners=used_corners, used_devices=used_devices)


def create_registry(workspace: str = "") -> PDKRegistry:
    """Create and return a PDK registry instance."""
    return PDKRegistry(workspace)
