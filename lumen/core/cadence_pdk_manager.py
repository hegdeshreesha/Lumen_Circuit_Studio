"""
Lumen Circuit Studio — Cadence Virtuoso-style PDK Management System

Implements the exact PDK management workflow used by Cadence Virtuoso:
1. cds.lib — Library path definitions (DEFINE library_name path)
2. .lib files — Model library files with process corners (.LIB tt .MODEL ... .ENDS)
3. Technology library — Layer definitions, design rules, device parameters
4. CDF (Component Description Format) — Device callbacks, parameters, simulation views
5. PDK setup — Installation, path configuration, environment variables

This system allows users to:
- Download PDKs locally and point to them (like Cadence PDK install)
- Select model libraries (.lib files) for specific process corners
- Link symbols to models (like Cadence CDF)
- Create projects with proper library bindings
- Generate cds.lib files compatible with Cadence tools
"""
import json
import os
import re
import shutil
import hashlib
import subprocess
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from enum import Enum


# ═══════════════════════════════════════════════════════════════════
# 1. cds.lib — Library Definition (EXACT Cadence format)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class CDSLibEntry:
    """
    A single entry in cds.lib file.
    
    Cadence format:
        DEFINE library_name path
        SOFTINCLUDE /path/to/other/cds.lib
        INCLUDE /path/to/techfile
    """
    name: str
    path: str
    entry_type: str = "DEFINE"  # DEFINE, SOFTINCLUDE, INCLUDE
    comment: str = ""
    
    def to_cds_line(self) -> str:
        """Export to exact Cadence cds.lib format."""
        comment_str = f"  # {self.comment}" if self.comment else ""
        return f"{self.entry_type} {self.name} {self.path}{comment_str}"
    
    @classmethod
    def from_cds_line(cls, line: str) -> Optional['CDSLibEntry']:
        """Parse a line from cds.lib file."""
        line = line.strip()
        if not line or line.startswith('#'):
            return None
        
        # Remove inline comments
        if '#' in line:
            line = line.split('#')[0].strip()
        
        parts = line.split(None, 2)
        if len(parts) >= 3 and parts[0] in ('DEFINE', 'SOFTINCLUDE', 'INCLUDE'):
            return cls(
                name=parts[1],
                path=parts[2],
                entry_type=parts[0]
            )
        return cls.from_legacy_format(line)
    
    @classmethod
    def from_legacy_format(cls, line: str) -> Optional['CDSLibEntry']:
        """Handle legacy or alternative formats."""
        parts = line.split()
        if len(parts) >= 2:
            return cls(name=parts[0], path=parts[1])
        return None


class CDSLib:
    """
    Complete cds.lib file manager.
    
    Cadence Virtuoso uses cds.lib to define all available libraries.
    This class reads, writes, and manages cds.lib files in the exact
    Cadence format.
    
    Example cds.lib:
        # Lumen Circuit Studio Library Definitions
        DEFINE basic /usr/local/cadence/tools/dfII/etc/cdslib/basic
        DEFINE analogLib /usr/local/cadence/tools/dfII/etc/cdslib/artist/analogLib
        DEFINE my_tech_lib /home/user/techlib
        SOFTINCLUDE /home/user/custom_cds.lib
    """
    
    def __init__(self, filepath: str = ""):
        self.filepath = filepath
        self.entries: List[CDSLibEntry] = []
        self.header_comments: List[str] = []
        
        if filepath and os.path.isfile(filepath):
            self.load(filepath)
    
    def load(self, filepath: str):
        """Load cds.lib from file."""
        self.filepath = filepath
        self.entries = []
        self.header_comments = []
        
        with open(filepath, 'r') as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith('#'):
                    self.header_comments.append(stripped)
                else:
                    entry = CDSLibEntry.from_cds_line(line)
                    if entry:
                        self.entries.append(entry)
    
    def save(self, filepath: str = ""):
        """Save cds.lib to file in exact Cadence format."""
        path = filepath or self.filepath
        if not path:
            raise ValueError("No filepath specified")
        
        lines = []
        
        # Header
        if not self.header_comments:
            lines.append(f"# Lumen Circuit Studio Library Definitions")
            lines.append(f"# Generated: {datetime.now().isoformat()}")
            lines.append(f"")
        else:
            lines.extend(self.header_comments)
        
        # Entries
        for entry in self.entries:
            lines.append(entry.to_cds_line())
        
        lines.append("")
        
        with open(path, 'w') as f:
            f.write('\n'.join(lines))
    
    def add_library(self, name: str, path: str, 
                    entry_type: str = "DEFINE", comment: str = ""):
        """Add a library definition."""
        # Check for duplicates
        for entry in self.entries:
            if entry.name == name and entry.entry_type == "DEFINE":
                entry.path = path
                entry.comment = comment
                return
        self.entries.append(CDSLibEntry(name, path, entry_type, comment))
    
    def remove_library(self, name: str):
        """Remove a library definition."""
        self.entries = [e for e in self.entries if e.name != name]
    
    def find_library(self, name: str) -> Optional[CDSLibEntry]:
        """Find a library by name."""
        for entry in self.entries:
            if entry.name == name:
                return entry
        return None
    
    def get_library_path(self, name: str) -> Optional[str]:
        """Get the path for a library."""
        entry = self.find_library(name)
        return entry.path if entry else None
    
    def to_json(self) -> Dict:
        """Serialize to JSON."""
        return {
            "filepath": self.filepath,
            "entries": [asdict(e) for e in self.entries],
            "header": self.header_comments
        }


# ═══════════════════════════════════════════════════════════════════
# 2. .lib Model Library — Process Corner Management
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ModelCorner:
    """
    A process corner from a .lib file.
    
    Cadence .lib format:
        .LIB tt
        .MODEL nmos ...
        .MODEL pmos ...
        .ENDS tt
    """
    name: str
    description: str = ""
    temperature: float = 25.0
    voltage: float = 1.8
    models: List[Dict] = field(default_factory=list)  # [{name, type, params}]
    subcircuits: List[Dict] = field(default_factory=list)
    includes: List[str] = field(default_factory=list)
    is_default: bool = False


@dataclass
class ModelLibrary:
    """
    A .lib model library file.
    
    In Cadence, you select model libraries for simulation:
    - Model libraries contain process-specific SPICE models
    - You include the .lib file and select a corner (TT, FF, SS, etc.)
    - Multiple .lib files can be stacked for different device types
    
    Example usage in netlist:
        .LIB /path/to/models.lib tt
        .LIB /path/to/resistors.lib typ
        .LIB /path/to/caps.lib typ
    """
    name: str
    filepath: str = ""
    format: str = "spice"  # spice, spectre, veriloga, cdl
    corners: List[ModelCorner] = field(default_factory=list)
    devices: List[Dict] = field(default_factory=list)
    checksum: str = ""
    size_bytes: int = 0
    last_modified: float = 0.0
    
    @classmethod
    def parse(cls, filepath: str) -> 'ModelLibrary':
        """
        Parse a .lib file to extract corners and models.
        
        Handles both Cadence .lib format and SPICE .lib format:
        
        SPICE format:
            .LIB tt
            .MODEL nmos nmos (level=49 ...)
            .ENDS tt
        
        Cadence .lib format:
            library(name) {
                delay_model : "cmos";
                cell(name) { ... }
            }
        """
        lib = cls(name=Path(filepath).stem, filepath=filepath)
        
        if not os.path.isfile(filepath):
            return lib
        
        try:
            stat = os.stat(filepath)
            lib.size_bytes = stat.st_size
            lib.last_modified = stat.st_mtime
            
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            lib.checksum = hashlib.md5(content.encode()).hexdigest()
        except:
            return lib
        
        # Detect format
        if content.strip().startswith('library('):
            lib.format = "cadence_lib"
            lib._parse_cadence_lib(content)
        else:
            lib.format = "spice"
            lib._parse_spice_lib(content)
        
        return lib
    
    def _parse_spice_lib(self, content: str):
        """Parse SPICE .lib format."""
        # Remove comments
        lines = []
        for line in content.split('\n'):
            stripped = line.strip()
            if stripped and not stripped.startswith('*') and not stripped.startswith('//'):
                lines.append(line)
        clean = '\n'.join(lines)
        
        current_corner = None
        corner_models = []
        corner_subckts = []
        corner_includes = []
        
        for line in clean.split('\n'):
            upper = line.strip().upper()
            
            if upper.startswith('.LIB '):
                # Save previous corner
                if current_corner:
                    self.corners.append(ModelCorner(
                        name=current_corner,
                        models=list(corner_models),
                        subcircuits=list(corner_subckts),
                        includes=list(corner_includes)
                    ))
                
                # Parse new corner
                match = re.match(r'\.LIB\s+"?([^"\s]+)"?\s+(\w+)', line)
                if match:
                    current_corner = match.group(2)
                else:
                    match = re.match(r'\.LIB\s+(\w+)', line)
                    if match:
                        current_corner = match.group(1)
                corner_models = []
                corner_subckts = []
                corner_includes = []
            
            elif upper.startswith('.MODEL '):
                match = re.match(r'\.MODEL\s+(\S+)\s+(\S+)', line)
                if match:
                    corner_models.append({
                        "name": match.group(1),
                        "type": match.group(2),
                        "corner": current_corner or "default"
                    })
                    # Also add to global device list
                    self.devices.append({
                        "name": match.group(1),
                        "type": match.group(2),
                        "corner": current_corner or "default",
                        "lib_file": self.filepath
                    })
            
            elif upper.startswith('.SUBCKT '):
                match = re.match(r'\.SUBCKT\s+(\S+)', line)
                if match:
                    corner_subckts.append(match.group(1))
                    self.devices.append({
                        "name": match.group(1),
                        "type": "SUBCKT",
                        "corner": current_corner or "default",
                        "lib_file": self.filepath
                    })
            
            elif upper.startswith('.INCLUDE ') or upper.startswith('.INC '):
                match = re.match(r'\.(?:INC|INCLUDE)\s+"?([^"\s]+)"?', line)
                if match:
                    corner_includes.append(match.group(1))
            
            elif upper.startswith('.ENDS') and current_corner:
                pass  # End of corner section
        
        # Save last corner
        if current_corner and not any(c.name == current_corner for c in self.corners):
            self.corners.append(ModelCorner(
                name=current_corner,
                models=list(corner_models),
                subcircuits=list(corner_subckts),
                includes=list(corner_includes)
            ))
        
        # If no corners found, create a default corner
        if not self.corners and self.devices:
            self.corners.append(ModelCorner(
                name="default",
                models=[d for d in self.devices if d.get("corner") == "default"],
                is_default=True
            ))
    
    def _parse_cadence_lib(self, content: str):
        """Parse Cadence .lib format (Liberty)."""
        # Extract library name
        match = re.match(r'library\s*\(\s*(\w+)\s*\)\s*{', content)
        if match:
            self.name = match.group(1)
        
        # Extract cells
        cell_pattern = re.compile(r'cell\s*\(\s*(\w+)\s*\)\s*{')
        for match in cell_pattern.finditer(content):
            self.devices.append({
                "name": match.group(1),
                "type": "cell",
                "corner": "default",
                "lib_file": self.filepath
            })
    
    def get_corner(self, name: str) -> Optional[ModelCorner]:
        """Get a specific corner by name."""
        for corner in self.corners:
            if corner.name == name:
                return corner
        return None
    
    def get_corner_names(self) -> List[str]:
        """Get all available corner names."""
        return [c.name for c in self.corners]
    
    def to_json(self) -> Dict:
        """Serialize to JSON."""
        return {
            "name": self.name,
            "filepath": self.filepath,
            "format": self.format,
            "corners": [asdict(c) for c in self.corners],
            "devices": self.devices,
            "checksum": self.checksum,
            "size_bytes": self.size_bytes
        }


# ═══════════════════════════════════════════════════════════════════
# 3. CDF (Component Description Format) — Device Metadata
# ═══════════════════════════════════════════════════════════════════

@dataclass
class CDFParameter:
    """
    A device parameter in CDF format.
    
    Cadence CDF parameters include:
    - name: Parameter name
    - defValue: Default value
    - description: Description
    - type: string, float, int, boolean
    - display: Display name in GUI
    - parseAsNumber: Whether to parse as number
    - callback: Python callback function name
    - callbackType: cdsSkill, python, etc.
    """
    name: str
    def_value: str = ""
    description: str = ""
    param_type: str = "string"  # string, float, int, boolean
    display_name: str = ""
    unit: str = ""
    parse_as_number: bool = False
    callback: str = ""
    callback_type: str = "python"
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    choices: List[str] = field(default_factory=list)
    
    def to_cdf_dict(self) -> Dict:
        """Export to CDF-compatible dict."""
        return {
            "name": self.name,
            "defValue": self.def_value,
            "description": self.description,
            "type": self.param_type,
            "display": self.display_name or self.name,
            "parseAsNumber": self.parse_as_number,
            "callback": self.callback,
            "callbackType": self.callback_type,
        }


@dataclass
class CDFDevice:
    """
    A device definition in CDF format.
    
    In Cadence Virtuoso, CDF defines:
    - Which model file to use
    - Which symbol to display
    - What parameters the device has
    - What simulation views are available
    - Callbacks for parameter validation
    """
    name: str
    library: str = ""
    cell_name: str = ""
    view_name: str = "symbol"
    
    # Model binding
    model_name: str = ""
    model_library: str = ""  # Which .lib file to include
    model_corner: str = ""  # Which corner to use (TT, FF, SS, etc.)
    
    # SPICE info
    prefix: str = "M"  # M, R, C, Q, D, V, I
    spice_model_name: str = ""
    simulator: str = "ngspice"  # ngspice, spectre, hspice
    
    # Symbol
    symbol_name: str = ""
    symbol_library: str = ""
    
    # Parameters
    parameters: List[CDFParameter] = field(default_factory=list)
    
    # Simulation views
    sim_views: List[str] = field(default_factory=lambda: ["symbol", "spectre", "spice", "veriloga"])
    
    # Callbacks
    callbacks: Dict[str, str] = field(default_factory=dict)
    
    # Netlisting
    term_order: List[str] = field(default_factory=list)
    inst_parameters: List[str] = field(default_factory=list)
    netlist_template: str = "[@instName] [@pins] [@modelName] [@instParameters]"
    
    def format_netlist_line(self, inst_name: str, pin_nets: Dict[str, str], 
                            inst_params: Dict[str, str]) -> str:
        """
        Format a SPICE netlist line for this device using its template.
        
        Example template: "[@instName] [@pins] [@modelName] [@instParameters]"
        
        Args:
            inst_name: The instance name (e.g., M1, R1)
            pin_nets: Mapping of pin names to net names (e.g., {"D": "out", "G": "in"})
            inst_params: Instance parameters (e.g., {"W": "1u", "L": "0.1u"})
            
        Returns:
            A formatted SPICE netlist line.
        """
        # Prefix the name if it doesn't already have it
        full_name = inst_name
        if self.prefix and not inst_name.startswith(self.prefix):
            full_name = f"{self.prefix}{inst_name}"
        
        # Resolve pins
        nets = []
        # If term_order is empty, use the pin names from pin_nets in some order?
        # Ideally term_order is defined in CDF.
        order = self.term_order
        if not order:
            # Fallback: alphabetical if not specified
            order = sorted(pin_nets.keys())
            
        for p in order:
            nets.append(pin_nets.get(p, "0")) # Default to ground if missing
        pin_str = " ".join(nets)
        
        # Model Name
        model_name = self.spice_model_name or self.model_name
        
        # Parameters
        params = []
        for p_name in self.inst_parameters:
            val = inst_params.get(p_name, "")
            if not val:
                # Find default from CDF
                for cdf_p in self.parameters:
                    if cdf_p.name == p_name:
                        val = cdf_p.def_value
                        break
            if val:
                # SPICE parameters can be name=value or just value
                # Most modern SPICE uses name=value
                params.append(f"{p_name}={val}")
        param_str = " ".join(params)
        
        # Format template
        line = self.netlist_template
        line = line.replace("[@instName]", full_name)
        line = line.replace("[@pins]", pin_str)
        line = line.replace("[@modelName]", model_name)
        line = line.replace("[@instParameters]", param_str)
        
        return line.strip()
    
    def to_cdf_dict(self) -> Dict:
        """Export to CDF-compatible dict."""
        return {
            "name": self.name,
            "library": self.library,
            "cellName": self.cell_name or self.name,
            "viewName": self.view_name,
            "modelName": self.model_name,
            "modelLibrary": self.model_library,
            "modelCorner": self.model_corner,
            "prefix": self.prefix,
            "spiceModelName": self.spice_model_name or self.model_name,
            "simulator": self.simulator,
            "symbolName": self.symbol_name or self.name,
            "symbolLibrary": self.symbol_library,
            "parameters": [p.to_cdf_dict() for p in self.parameters],
            "simViews": self.sim_views,
            "callbacks": self.callbacks,
            "termOrder": self.term_order,
            "instParameters": self.inst_parameters,
            "netlistTemplate": self.netlist_template,
        }


class CDFDatabase:
    """
    CDF (Component Description Format) Database.
    
    In Cadence Virtuoso, CDF defines how devices behave:
    - What parameters they have
    - What model files they reference
    - What symbols they use
    - Callbacks for parameter validation
    
    This is the key component that links symbols to models.
    """
    
    def __init__(self):
        self.devices: Dict[str, CDFDevice] = {}
        self._callbacks: Dict[str, callable] = {}
    
    def register_device(self, device: CDFDevice):
        """Register a device in the CDF database."""
        self.devices[device.name] = device
    
    def get_device(self, name: str) -> Optional[CDFDevice]:
        """Get a device by name."""
        return self.devices.get(name)
    
    def register_callback(self, name: str, func: callable):
        """Register a Python callback function for parameter validation."""
        self._callbacks[name] = func
    
    def execute_callback(self, name: str, **kwargs) -> Any:
        """Execute a registered callback."""
        if name in self._callbacks:
            return self._callbacks[name](**kwargs)
        return None
    
    def to_json(self) -> Dict:
        """Serialize to JSON."""
        return {
            "devices": {
                name: device.to_cdf_dict() 
                for name, device in self.devices.items()
            }
        }
    
    def save(self, filepath: str):
        """Save CDF database to file."""
        with open(filepath, 'w') as f:
            json.dump(self.to_json(), f, indent=2)
    
    @classmethod
    def load(cls, filepath: str) -> 'CDFDatabase':
        """Load CDF database from file."""
        db = cls()
        if os.path.isfile(filepath):
            with open(filepath, 'r') as f:
                data = json.load(f)
            for name, device_data in data.get("devices", {}).items():
                params = [CDFParameter(**p) for p in device_data.get("parameters", [])]
                device = CDFDevice(
                    name=name,
                    library=device_data.get("library", ""),
                    cell_name=device_data.get("cellName", name),
                    model_name=device_data.get("modelName", ""),
                    model_library=device_data.get("modelLibrary", ""),
                    model_corner=device_data.get("modelCorner", ""),
                    prefix=device_data.get("prefix", "M"),
                    spice_model_name=device_data.get("spiceModelName", ""),
                    symbol_name=device_data.get("symbolName", name),
                    symbol_library=device_data.get("symbolLibrary", ""),
                    parameters=params,
                    sim_views=device_data.get("simViews", ["symbol", "spice"]),
                    term_order=device_data.get("termOrder", []),
                    inst_parameters=device_data.get("instParameters", []),
                    netlist_template=device_data.get("netlistTemplate", "[@instName] [@pins] [@modelName] [@instParameters]"),
                )
                db.devices[name] = device
        return db


# ═══════════════════════════════════════════════════════════════════
# 4. PDK Setup — Installation and Configuration
# ═══════════════════════════════════════════════════════════════════

@dataclass
class PDKSetupConfig:
    """
    PDK setup configuration.
    
    In Cadence, PDK setup typically involves:
    1. Setting PDK_DIR environment variable
    2. Running a setup script (e.g., pdkSetup.csh)
    3. Configuring cds.lib to include PDK libraries
    4. Setting up technology library
    
    This class captures all that configuration.
    """
    pdk_name: str
    display_name: str = ""
    foundry: str = ""
    node: str = ""
    version: str = "1.0"
    
    # Installation
    install_path: str = ""
    models_path: str = ""
    symbols_path: str = ""
    tech_path: str = ""
    
    # Model libraries (.lib files)
    model_libraries: List[ModelLibrary] = field(default_factory=list)
    
    # CDF database
    cdf_database: Optional[CDFDatabase] = None
    
    # Environment variables to set
    env_vars: Dict[str, str] = field(default_factory=dict)
    
    # Technology library
    tech_lib_name: str = ""
    layers: List[Dict] = field(default_factory=list)
    
    # Available corners
    corners: List[str] = field(default_factory=list)
    
    # Default corner
    default_corner: str = "tt"
    
    # Setup script content (for generating setup scripts)
    setup_script: str = ""


class CadencePDKManager:
    """
    Complete PDK manager that mirrors Cadence Virtuoso's workflow.
    
    How Cadence Virtuoso handles PDKs:
    1. PDK is installed to a directory (e.g., /cadence/PDK/tsmcN65)
    2. cds.lib is configured with DEFINE statements pointing to PDK libs
    3. Model libraries (.lib files) are selected for simulation
    4. CDF defines device parameters and links symbols to models
    5. Technology library defines layers and design rules
    
    This manager implements the exact same workflow.
    
    Usage:
        manager = CadencePDKManager()
        
        # 1. Install/register a PDK (like running PDK setup script)
        manager.install_pdk("sky130", "/path/to/skywater-pdk")
        
        # 2. Select model libraries (like choosing .lib files in ADE)
        manager.select_model_library("sky130", "path/to/models.lib")
        
        # 3. Set active corner (like choosing TT/FF/SS in simulation)
        manager.set_active_corner("sky130", "tt")
        
        # 4. Generate cds.lib (like Cadence library manager)
        manager.generate_cds_lib("my_project", "./project")
        
        # 5. Get device with CDF (like placing a device in schematic)
        device = manager.get_device_cdf("sky130", "nmos")
    """
    
    # Known PDK sources
    KNOWN_PDKS = {
        "sky130": {
            "display_name": "SkyWater SKY130",
            "foundry": "SkyWater Technology",
            "node": "130nm",
            "url": "https://github.com/google/skywater-pdk",
            "default_corners": ["tt", "ff", "ss", "sf", "fs"],
            "default_voltage": 1.8,
        },
        "ihp_sg13g2": {
            "display_name": "IHP SG13G2",
            "foundry": "IHP Microelectronics",
            "node": "130nm",
            "url": "https://github.com/IHP-GmbH/IHP-Open-PDK",
            "default_corners": ["typ", "fast", "slow"],
            "default_voltage": 1.2,
        },
        "gf180mcu": {
            "display_name": "GlobalFoundries GF180MCU",
            "foundry": "GlobalFoundries",
            "node": "180nm",
            "url": "https://github.com/google/gf180mcu-pdk",
            "default_corners": ["typical", "ff", "ss"],
            "default_voltage": 3.3,
        },
    }
    
    def __init__(self, workspace_dir: str = ""):
        self.workspace = Path(workspace_dir or os.path.join(
            os.path.expanduser("~"), ".lumen"))
        self.workspace.mkdir(parents=True, exist_ok=True)
        
        # PDK installations
        self._pdks: Dict[str, PDKSetupConfig] = {}
        
        # Active configuration per project
        self._active_pdk: str = ""
        self._active_corner: str = "tt"
        self._active_model_libs: List[str] = []
        
        # CDF database
        self.cdf = CDFDatabase()
        
        # Library definitions
        self.cds_lib = CDSLib()
        
        # Config path
        self._config_path = self.workspace / "cadence_pdk_config.json"
        self._load_config()
        
        # Register built-in CDF devices
        self._register_builtin_cdf()
    
    def _load_config(self):
        """Load configuration from disk."""
        if self._config_path.exists():
            try:
                with open(self._config_path, 'r') as f:
                    data = json.load(f)
                self._active_pdk = data.get("active_pdk", "")
                self._active_corner = data.get("active_corner", "tt")
                self._active_model_libs = data.get("active_model_libs", [])
                
                # Load PDK configs
                for pdk_data in data.get("pdks", []):
                    # Convert model_libraries from dicts back to ModelLibrary objects
                    libs_data = pdk_data.pop("model_libraries", [])
                    config = PDKSetupConfig(**pdk_data)
                    for lib_data in libs_data:
                        corners_data = lib_data.pop("corners", [])
                        lib = ModelLibrary(**lib_data)
                        for c_data in corners_data:
                            lib.corners.append(ModelCorner(**c_data))
                        config.model_libraries.append(lib)
                    self._pdks[config.pdk_name] = config
                
                # Load CDF
                cdf_path = data.get("cdf_path", "")
                if cdf_path and os.path.isfile(cdf_path):
                    self.cdf = CDFDatabase.load(cdf_path)
                
                # Load cds.lib
                cds_path = data.get("cds_lib_path", "")
                if cds_path and os.path.isfile(cds_path):
                    self.cds_lib.load(cds_path)
            except:
                pass
    
    def _save_config(self):
        """Save configuration to disk."""
        # Save CDF
        cdf_path = str(self.workspace / "cdf_database.json")
        self.cdf.save(cdf_path)
        
        # Save cds.lib
        cds_path = str(self.workspace / "cds.lib")
        self.cds_lib.save(cds_path)
        
        data = {
            "active_pdk": self._active_pdk,
            "active_corner": self._active_corner,
            "active_model_libs": self._active_model_libs,
            "pdks": [asdict(p) for p in self._pdks.values()],
            "cdf_path": cdf_path,
            "cds_lib_path": cds_path,
        }
        with open(self._config_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    def _register_builtin_cdf(self):
        """Register built-in CDF devices for all PDKs."""
        # SkyWater devices
        sky130_devices = {
            "nmos": CDFDevice("sky130_nmos", "skywater_primitives", prefix="M", 
                             spice_model_name="nfet_01v8", model_name="nfet_01v8",
                             term_order=["D", "G", "S", "B"],
                             inst_parameters=["W", "L", "nf", "m", "ad", "as", "pd", "ps", "nrd", "nrs"],
                             parameters=[
                                 CDFParameter("W", "1u", "Width", "float", "Width", "m", True),
                                 CDFParameter("L", "0.15u", "Length", "float", "Length", "m", True),
                                 CDFParameter("nf", "1", "Number of Fingers", "int", "Fingers", "", True),
                                 CDFParameter("m", "1", "Multiplier", "int", "Multiplier", "", True),
                                 CDFParameter("ad", "", "Drain Area", "float", "Drain Area", "m²", True),
                                 CDFParameter("as", "", "Source Area", "float", "Source Area", "m²", True),
                                 CDFParameter("pd", "", "Drain Perimeter", "float", "Drain Perim", "m", True),
                                 CDFParameter("ps", "", "Source Perimeter", "float", "Source Perim", "m", True),
                                 CDFParameter("nrd", "", "Drain Resistance", "float", "Drain R", "", True),
                                 CDFParameter("nrs", "", "Source Resistance", "float", "Source R", "", True),
                             ]),
            "pmos": CDFDevice("sky130_pmos", "skywater_primitives", prefix="M",
                             spice_model_name="pfet_01v8", model_name="pfet_01v8",
                             term_order=["D", "G", "S", "B"],
                             inst_parameters=["W", "L", "nf", "m", "ad", "as", "pd", "ps", "nrd", "nrs"],
                             parameters=[
                                 CDFParameter("W", "1u", "Width", "float", "Width", "m", True),
                                 CDFParameter("L", "0.15u", "Length", "float", "Length", "m", True),
                                 CDFParameter("nf", "1", "Number of Fingers", "int", "Fingers", "", True),
                                 CDFParameter("m", "1", "Multiplier", "int", "Multiplier", "", True),
                                 CDFParameter("ad", "", "Drain Area", "float", "Drain Area", "m²", True),
                                 CDFParameter("as", "", "Source Area", "float", "Source Area", "m²", True),
                             ]),
            "res": CDFDevice("res", "skywater_primitives", prefix="R",
                            spice_model_name="res_generic_po", model_name="res_generic_po",
                            parameters=[
                                CDFParameter("R", "1k", "Resistance", "float", "Resistance", "ohm", True),
                                CDFParameter("W", "1u", "Width", "float", "Width", "m", True),
                                CDFParameter("L", "1u", "Length", "float", "Length", "m", True),
                                CDFParameter("m", "1", "Multiplier", "int", "Multiplier", "", True),
                            ]),
            "cap": CDFDevice("cap", "skywater_primitives", prefix="C",
                            spice_model_name="cap_mim", model_name="cap_mim",
                            parameters=[
                                CDFParameter("C", "1p", "Capacitance", "float", "Capacitance", "F", True),
                                CDFParameter("W", "5u", "Width", "float", "Width", "m", True),
                                CDFParameter("L", "5u", "Length", "float", "Length", "m", True),
                            ]),
            "diode": CDFDevice("diode", "skywater_primitives", prefix="D",
                              spice_model_name="diode", model_name="diode",
                              parameters=[
                                  CDFParameter("area", "1", "Area Multiplier", "float", "Area", "", True),
                              ]),
            "vsource": CDFDevice("vsource", "skywater_primitives", prefix="V",
                                spice_model_name="V", model_name="V",
                                parameters=[
                                    CDFParameter("DC", "1.8", "DC Voltage", "float", "DC", "V", True),
                                    CDFParameter("AC", "", "AC Amplitude", "float", "AC", "V", True),
                                ]),
            "isource": CDFDevice("isource", "skywater_primitives", prefix="I",
                                spice_model_name="I", model_name="I",
                                parameters=[
                                    CDFParameter("DC", "1u", "DC Current", "float", "DC", "A", True),
                                ]),
            "gnd": CDFDevice("gnd", "skywater_primitives", prefix="V",
                            spice_model_name="V", model_name="V",
                            parameters=[
                                CDFParameter("DC", "0", "DC Voltage", "float", "DC", "V", True),
                            ]),
            "vdd": CDFDevice("vdd", "skywater_primitives", prefix="V",
                            spice_model_name="V", model_name="V",
                            parameters=[
                                CDFParameter("DC", "1.8", "DC Voltage", "float", "DC", "V", True),
                            ]),
            "npn": CDFDevice("npn", "skywater_primitives", prefix="Q",
                            spice_model_name="npn", model_name="npn",
                            parameters=[
                                CDFParameter("m", "1", "Multiplier", "int", "Multiplier", "", True),
                                CDFParameter("area", "1", "Area Multiplier", "float", "Area", "", True),
                            ]),
        }
        
        # IHP devices
        ihp_devices = {
            "sg13_lv_nmos": CDFDevice("sg13_lv_nmos", "ihp_primitives", prefix="M",
                                      spice_model_name="sg13_lv_nmos", model_name="sg13_lv_nmos",
                                      term_order=["D", "G", "S", "B"],
                                      inst_parameters=["w", "l", "ng", "m"],
                                      parameters=[
                                          CDFParameter("w", "0.15u", "Width", "float", "Width", "m", True),
                                          CDFParameter("l", "0.13u", "Length", "float", "Length", "m", True),
                                          CDFParameter("ng", "1", "Gate Fingers", "int", "Fingers", "", True),
                                          CDFParameter("m", "1", "Multiplier", "int", "Multiplier", "", True),
                                      ]),
            "sg13_lv_pmos": CDFDevice("sg13_lv_pmos", "ihp_primitives", prefix="M",
                                      spice_model_name="sg13_lv_pmos", model_name="sg13_lv_pmos",
                                      term_order=["D", "G", "S", "B"],
                                      inst_parameters=["w", "l", "ng", "m"],
                                      parameters=[
                                          CDFParameter("w", "0.15u", "Width", "float", "Width", "m", True),
                                          CDFParameter("l", "0.13u", "Length", "float", "Length", "m", True),
                                          CDFParameter("ng", "1", "Gate Fingers", "int", "Fingers", "", True),
                                          CDFParameter("m", "1", "Multiplier", "int", "Multiplier", "", True),
                                      ]),
            "cap_cmim": CDFDevice("cap_cmim", "ihp_primitives", prefix="C",
                                  spice_model_name="cap_cmim", model_name="cap_cmim",
                                  parameters=[
                                      CDFParameter("C", "1p", "Capacitance", "float", "Capacitance", "F", True),
                                  ]),
            "rppd": CDFDevice("rppd", "ihp_primitives", prefix="R",
                             spice_model_name="rppd", model_name="rppd",
                             parameters=[
                                 CDFParameter("W", "1", "Width", "float", "Width", "um", True),
                                 CDFParameter("L", "1", "Length", "float", "Length", "um", True),
                                 CDFParameter("m", "1", "Multiplier", "int", "Multiplier", "", True),
                             ]),
            "npn13G2": CDFDevice("npn13G2", "ihp_primitives", prefix="Q",
                                 spice_model_name="npn13G2", model_name="npn13G2",
                                 parameters=[
                                     CDFParameter("m", "1", "Multiplier", "int", "Multiplier", "", True),
                                     CDFParameter("area", "1", "Area", "float", "Area", "", True),
                                 ]),
        }
        
        # GF180MCU devices
        gf_devices = {
            "nmos": CDFDevice("gf180mcu_nmos", "gf180mcu_primitives", prefix="M",
                             spice_model_name="n_18_3p3", model_name="n_18_3p3",
                             term_order=["D", "G", "S", "B"],
                             inst_parameters=["W", "L", "nf", "m"],
                             parameters=[
                                 CDFParameter("W", "1u", "Width", "float", "Width", "m", True),
                                 CDFParameter("L", "180n", "Length", "float", "Length", "m", True),
                                 CDFParameter("nf", "1", "Fingers", "int", "Fingers", "", True),
                                 CDFParameter("m", "1", "Multiplier", "int", "Multiplier", "", True),
                             ]),
            "pmos": CDFDevice("gf180mcu_pmos", "gf180mcu_primitives", prefix="M",
                             spice_model_name="p_18_3p3", model_name="p_18_3p3",
                             term_order=["D", "G", "S", "B"],
                             inst_parameters=["W", "L", "nf", "m"],
                             parameters=[
                                 CDFParameter("W", "1u", "Width", "float", "Width", "m", True),
                                 CDFParameter("L", "180n", "Length", "float", "Length", "m", True),
                                 CDFParameter("nf", "1", "Fingers", "int", "Fingers", "", True),
                                 CDFParameter("m", "1", "Multiplier", "int", "Multiplier", "", True),
                             ]),
            "res": CDFDevice("res", "gf180mcu_primitives", prefix="R",
                            spice_model_name="res_n_std", model_name="res_n_std",
                            parameters=[
                                CDFParameter("R", "1k", "Resistance", "float", "Resistance", "ohm", True),
                                CDFParameter("W", "1u", "Width", "float", "Width", "m", True),
                                CDFParameter("L", "1u", "Length", "float", "Length", "m", True),
                            ]),
            "cap": CDFDevice("cap", "gf180mcu_primitives", prefix="C",
                            spice_model_name="cap_mim", model_name="cap_mim",
                            parameters=[
                                CDFParameter("C", "1p", "Capacitance", "float", "Capacitance", "F", True),
                            ]),
            "diode": CDFDevice("diode", "gf180mcu_primitives", prefix="D",
                              spice_model_name="diode", model_name="diode",
                              parameters=[
                                  CDFParameter("area", "1", "Area", "float", "Area", "", True),
                              ]),
        }
        
        # Register all devices
        for name, device in sky130_devices.items():
            self.cdf.register_device(device)
        for name, device in ihp_devices.items():
            self.cdf.register_device(device)
        for name, device in gf_devices.items():
            self.cdf.register_device(device)
    
    # ── PDK Installation ────────────────────────────────────────
    
    def install_pdk(self, name: str, path: str, 
                    display_name: str = "") -> bool:
        """
        Install/register a PDK.
        
        This is equivalent to running a Cadence PDK setup script.
        It:
        1. Registers the PDK path
        2. Scans for .lib model files
        3. Discovers available devices
        4. Sets up CDF entries
        5. Configures cds.lib entries
        
        Args:
            name: PDK name (e.g., 'sky130', 'ihp_sg13g2', 'gf180mcu')
            path: Path to PDK root directory
            display_name: Optional display name
        
        Returns:
            True if successful
        """
        p = Path(path)
        if not p.exists() or not p.is_dir():
            print(f"Error: Invalid PDK path: {path}")
            return False
        
        # Get PDK info
        info = self.KNOWN_PDKS.get(name, {})
        if not display_name:
            display_name = info.get("display_name", name)
        
        # Create PDK config
        config = PDKSetupConfig(
            pdk_name=name,
            display_name=display_name,
            foundry=info.get("foundry", ""),
            node=info.get("node", ""),
            install_path=str(p.absolute()),
            models_path=str(p.absolute()),
            symbols_path=str(p.absolute()),
            corners=info.get("default_corners", ["tt"]),
            default_corner=info.get("default_corners", ["tt"])[0] if info.get("default_corners") else "tt",
        )
        
        # Scan for .lib model files
        print(f"Scanning for model libraries in {path}...")
        lib_files_found = 0
        for lib_path in p.rglob("*.lib"):
            try:
                model_lib = ModelLibrary.parse(str(lib_path))
                if model_lib.corners or model_lib.devices:
                    config.model_libraries.append(model_lib)
                    lib_files_found += 1
                    print(f"  Found: {lib_path.relative_to(p)} "
                          f"({len(model_lib.corners)} corners, "
                          f"{len(model_lib.devices)} devices)")
            except Exception as e:
                print(f"  Warning: Could not parse {lib_path}: {e}")
        
        print(f"  Total: {lib_files_found} .lib files found")
        
        # Add to cds.lib
        self.cds_lib.add_library(
            name=name,
            path=str(p.absolute()),
            comment=f"{display_name} PDK"
        )
        
        # Store config
        self._pdks[name] = config
        self._save_config()
        
        return True
    
    def get_installed_pdks(self) -> Dict[str, PDKSetupConfig]:
        """Get all installed PDKs."""
        # Verify paths still exist
        verified = {}
        for name, config in self._pdks.items():
            if config.install_path and os.path.isdir(config.install_path):
                verified[name] = config
        return verified
    
    def is_installed(self, name: str) -> bool:
        """Check if a PDK is installed."""
        config = self._pdks.get(name)
        if config is None:
            return False
        if not config.install_path:
            return False
        return os.path.isdir(config.install_path)
    
    # ── Model Library Selection ─────────────────────────────────
    
    def get_model_libraries(self, pdk_name: str) -> List[ModelLibrary]:
        """Get all model libraries for a PDK."""
        config = self._pdks.get(pdk_name)
        if not config:
            return []
        return config.model_libraries
    
    def get_available_corners(self, pdk_name: str) -> List[str]:
        """Get all available process corners from model libraries."""
        corners = set()
        config = self._pdks.get(pdk_name)
        if config:
            for lib in config.model_libraries:
                for corner in lib.corners:
                    corners.add(corner.name)
        return sorted(corners)
    
    def select_model_library(self, pdk_name: str, 
                              lib_path: str) -> bool:
        """
        Select a model library for use.
        
        In Cadence Virtuoso, you select model libraries in ADE (Analog Design
        Environment) by choosing .lib files and their corners.
        
        This is equivalent to:
            .LIB /path/to/models.lib tt
        """
        config = self._pdks.get(pdk_name)
        if not config:
            return False
        
        # Parse the .lib file
        model_lib = ModelLibrary.parse(lib_path)
        if not model_lib.corners and not model_lib.devices:
            print(f"Warning: No models found in {lib_path}")
        
        # Add or update
        for i, existing in enumerate(config.model_libraries):
            if existing.filepath == lib_path:
                config.model_libraries[i] = model_lib
                self._save_config()
                return True
        
        config.model_libraries.append(model_lib)
        self._save_config()
        return True
    
    def set_active_corner(self, pdk_name: str, corner: str) -> bool:
        """
        Set the active process corner.
        
        In Cadence Virtuoso, you select the corner in ADE:
        - tt (typical-typical)
        - ff (fast-fast)  
        - ss (slow-slow)
        - etc.
        
        This determines which .LIB section is used in simulation.
        """
        available = self.get_available_corners(pdk_name)
        if corner in available or not available:
            self._active_corner = corner
            self._save_config()
            return True
        print(f"Warning: Corner '{corner}' not found in available corners: {available}")
        return False
    
    def get_active_corner(self) -> str:
        """Get the active process corner."""
        return self._active_corner
    
    def set_active_pdk(self, name: str) -> bool:
        """Set the active PDK."""
        if self.is_installed(name):
            self._active_pdk = name
            self._save_config()
            return True
        return False
    
    def get_active_pdk(self) -> Optional[str]:
        """Get the active PDK name."""
        return self._active_pdk if self._active_pdk else None
    
    # ── Device and CDF Management ───────────────────────────────
    
    def get_device_cdf(self, pdk_name: str, device_name: str) -> Optional[CDFDevice]:
        """
        Get the CDF definition for a device.
        
        In Cadence Virtuoso, CDF defines:
        - What parameters the device has
        - What model it references
        - What symbol it uses
        - Callbacks for parameter validation
        
        This is how you link a symbol to its SPICE model.
        """
        # Try exact match first
        device = self.cdf.get_device(device_name)
        if device:
            return device
        
        # Try PDK-specific prefix
        prefixed = f"{pdk_name}_{device_name}"
        device = self.cdf.get_device(prefixed)
        if device:
            return device
        
        # Try to find from model libraries
        config = self._pdks.get(pdk_name)
        if config:
            for lib in config.model_libraries:
                for dev in lib.devices:
                    if dev.get("name") == device_name:
                        # Create CDF device from model
                        return CDFDevice(
                            name=device_name,
                            library=f"{pdk_name}_primitives",
                            model_name=dev.get("name", device_name),
                            model_library=lib.filepath,
                            model_corner=self._active_corner,
                            prefix=self._get_prefix_for_type(dev.get("type", "")),
                            spice_model_name=dev.get("name", device_name),
                        )
        
        return None
    
    def _get_prefix_for_type(self, model_type: str) -> str:
        """Get SPICE prefix for a model type."""
        type_upper = model_type.upper()
        if type_upper in ("NMOS", "PMOS", "NMOS1", "PMOS1", "NCH", "PCH"):
            return "M"
        elif type_upper in ("NPN", "PNP", "NPN1", "PNP1"):
            return "Q"
        elif type_upper in ("D", "DIO", "DIODE"):
            return "D"
        elif type_upper in ("R", "RES", "RESISTOR"):
            return "R"
        elif type_upper in ("C", "CAP", "CAPACITOR"):
            return "C"
        elif type_upper in ("L", "IND", "INDUCTOR"):
            return "L"
        elif type_upper in ("V", "VSOURCE"):
            return "V"
        elif type_upper in ("I", "ISOURCE"):
            return "I"
        return "X"
    
    def get_all_devices(self, pdk_name: str = "") -> List[Dict]:
        """
        Get all available devices from model libraries.
        
        This is equivalent to browsing the Cadence library manager
        to see what devices are available in a PDK.
        """
        name = pdk_name or self._active_pdk
        if not name:
            return []
        
        devices = []
        config = self._pdks.get(name)
        if config:
            for lib in config.model_libraries:
                for dev in lib.devices:
                    devices.append({
                        **dev,
                        "lib_file": lib.filepath,
                        "pdk": name,
                        "corner": self._active_corner,
                    })
        
        # Also add CDF devices
        for dev_name, device in self.cdf.devices.items():
            if device.library.startswith(name) or not pdk_name:
                devices.append({
                    "name": dev_name,
                    "type": "CDF",
                    "model": device.spice_model_name,
                    "prefix": device.prefix,
                    "pdk": name,
                    "lib_file": device.model_library or "",
                    "corner": device.model_corner or self._active_corner,
                })
        
        return devices
    
    # ── Netlist Generation ──────────────────────────────────────
    
    def generate_netlist_header(self, pdk_name: str = "") -> str:
        """
        Generate the SPICE netlist header with model library includes.
        
        This is equivalent to what Cadence Virtuoso generates when
        you run a simulation - it includes the .lib files with the
        selected corner.
        
        Example output:
            .LIB /path/to/sky130/models.lib tt
            .LIB /path/to/sky130/resistors.lib tt
            .LIB /path/to/sky130/capacitors.lib tt
        """
        name = pdk_name or self._active_pdk
        if not name:
            return ""
        
        config = self._pdks.get(name)
        if not config:
            return ""
        
        lines = [
            f"* Lumen Circuit Studio - PDK: {config.display_name}",
            f"* Corner: {self._active_corner}",
            f"* Generated: {datetime.now().isoformat()}",
            f"",
        ]
        
        for lib in config.model_libraries:
            if lib.filepath and os.path.isfile(lib.filepath):
                lines.append(f".LIB {lib.filepath} {self._active_corner}")
        
        lines.append("")
        return '\n'.join(lines)
    
    # ── Project and Library Management ──────────────────────────
    
    def generate_cds_lib(self, project_name: str, 
                          project_dir: str,
                          pdk_name: str = "") -> str:
        """
        Generate a cds.lib file for a project.
        
        This is equivalent to creating a new library in Cadence
        Library Manager and attaching a technology library.
        
        The generated cds.lib will contain:
        - DEFINE statements for the PDK libraries
        - DEFINE statement for the project design library
        - References to model libraries
        
        Args:
            project_name: Name of the project
            project_dir: Directory to create the project
            pdk_name: PDK to bind (uses active PDK if not specified)
        
        Returns:
            Path to the generated cds.lib file
        """
        pdk = pdk_name or self._active_pdk
        if not pdk:
            raise ValueError("No PDK specified or active")
        
        config = self._pdks.get(pdk)
        if not config:
            raise ValueError(f"PDK '{pdk}' is not installed")
        
        project_root = Path(project_dir) / project_name
        project_root.mkdir(parents=True, exist_ok=True)
        
        # Create cds.lib
        cds = CDSLib()
        
        # Add PDK library
        cds.add_library(
            name=pdk,
            path=config.install_path,
            comment=f"{config.display_name} PDK"
        )
        
        # Add design library
        design_path = str(project_root / "design")
        Path(design_path).mkdir(exist_ok=True)
        cds.add_library(
            name=project_name,
            path=design_path,
            comment=f"{project_name} design library"
        )
        
        # Add model libraries
        for lib in config.model_libraries:
            if lib.filepath:
                lib_name = f"{pdk}_models_{lib.name}"
                cds.add_library(
                    name=lib_name,
                    path=os.path.dirname(lib.filepath),
                    comment=f"{lib.name} model library ({len(lib.corners)} corners)"
                )
        
        # Save cds.lib
        cds_path = str(project_root / "cds.lib")
        cds.save(cds_path)
        
        # Also save project config
        project_config = {
            "project_name": project_name,
            "pdk": pdk,
            "active_corner": self._active_corner,
            "model_libraries": [
                {
                    "name": lib.name,
                    "path": lib.filepath,
                    "corners": lib.get_corner_names(),
                }
                for lib in config.model_libraries
            ],
            "cds_lib_path": cds_path,
            "created_at": datetime.now().isoformat(),
        }
        
        with open(project_root / "project.json", 'w') as f:
            json.dump(project_config, f, indent=2)
        
        return cds_path
    
    def get_health_report(self, pdk_name: str) -> Dict[str, Any]:
        """Generate a health report for a PDK installation."""
        name = pdk_name or self._active_pdk
        if not name:
            return {"error": "No PDK specified"}
        
        config = self._pdks.get(name)
        if not config:
            return {"error": f"PDK '{name}' not installed"}
        
        # Count devices and corners
        total_devices = 0
        all_corners = set()
        lib_details = []
        
        for lib in config.model_libraries:
            total_devices += len(lib.devices)
            for corner in lib.corners:
                all_corners.add(corner.name)
            lib_details.append({
                "name": lib.name,
                "path": lib.filepath,
                "format": lib.format,
                "corners": lib.get_corner_names(),
                "devices": len(lib.devices),
                "size_bytes": lib.size_bytes,
            })
        
        return {
            "name": name,
            "display_name": config.display_name,
            "foundry": config.foundry,
            "node": config.node,
            "installed": True,
            "install_path": config.install_path,
            "model_libraries_count": len(config.model_libraries),
            "total_devices": total_devices,
            "available_corners": sorted(all_corners),
            "active_corner": self._active_corner,
            "cdf_devices": len([d for d in self.cdf.devices if d.startswith(name) or True]),
            "lib_details": lib_details,
        }
    
    def to_json(self) -> Dict:
        """Serialize manager state to JSON."""
        return {
            "active_pdk": self._active_pdk,
            "active_corner": self._active_corner,
            "installed_pdks": {
                name: {
                    "display_name": config.display_name,
                    "foundry": config.foundry,
                    "node": config.node,
                    "install_path": config.install_path,
                    "model_libraries": len(config.model_libraries),
                    "corners": config.corners,
                }
                for name, config in self._pdks.items()
            },
            "cdf_devices": list(self.cdf.devices.keys()),
            "cds_lib_entries": [
                asdict(e) for e in self.cds_lib.entries
            ],
        }


# ═══════════════════════════════════════════════════════════════════
# Convenience Functions
# ═══════════════════════════════════════════════════════════════════

def create_manager(workspace: str = "") -> CadencePDKManager:
    """Create a Cadence-style PDK manager."""
    return CadencePDKManager(workspace)


if __name__ == "__main__":
    import sys
    
    print("Lumen Circuit Studio — Cadence-style PDK Manager")
    print("=" * 60)
    
    manager = CadencePDKManager()
    
    if len(sys.argv) > 1 and sys.argv[1] == "install":
        name = sys.argv[2] if len(sys.argv) > 2 else ""
        path = sys.argv[3] if len(sys.argv) > 3 else ""
        
        if name and path:
            success = manager.install_pdk(name, path)
            if success:
                print(f"\nPDK '{name}' installed successfully!")
                report = manager.get_health_report(name)
                print(f"  Model libraries: {report['model_libraries_count']}")
                print(f"  Total devices: {report['total_devices']}")
                print(f"  Available corners: {report['available_corners']}")
                print(f"  CDF devices: {report['cdf_devices']}")
                
                # Set as active
                manager.set_active_pdk(name)
                print(f"\n  Set as active PDK")
                
                # Generate cds.lib
                cds_path = manager.generate_cds_lib("test_project", ".")
                print(f"  Generated cds.lib: {cds_path}")
            else:
                print(f"Failed to install PDK '{name}'")
    
    elif len(sys.argv) > 1 and sys.argv[1] == "status":
        installed = manager.get_installed_pdks()
        if installed:
            print("\nInstalled PDKs:")
            for name, config in installed.items():
                print(f"  {name}: {config.display_name}")
                print(f"    Path: {config.install_path}")
                print(f"    Model libs: {len(config.model_libraries)}")
                print(f"    Corners: {config.corners}")
        else:
            print("\nNo PDKs installed. Use 'install' command.")
        
        print(f"\nActive PDK: {manager.get_active_pdk() or 'None'}")
        print(f"Active corner: {manager.get_active_corner()}")
        print(f"CDF devices: {len(manager.cdf.devices)}")
    
    elif len(sys.argv) > 1 and sys.argv[1] == "corners":
        name = sys.argv[2] if len(sys.argv) > 2 else manager.get_active_pdk()
        if name:
            corners = manager.get_available_corners(name)
            print(f"\nAvailable corners for {name}:")
            for c in corners:
                print(f"  - {c}")
        else:
            print("No PDK specified or active")
    
    elif len(sys.argv) > 1 and sys.argv[1] == "devices":
        name = sys.argv[2] if len(sys.argv) > 2 else manager.get_active_pdk()
        if name:
            devices = manager.get_all_devices(name)
            print(f"\nDevices in {name} ({len(devices)} total):")
            for d in devices[:20]:  # Show first 20
                print(f"  {d.get('name', '?'):20s} type={d.get('type', '?'):10s} prefix={d.get('prefix', '?')}")
            if len(devices) > 20:
                print(f"  ... and {len(devices) - 20} more")
        else:
            print("No PDK specified or active")
    
    else:
        print("\nUsage:")
        print("  python cadence_pdk_manager.py install <pdk_name> <path>")
        print("  python cadence_pdk_manager.py status")
        print("  python cadence_pdk_manager.py corners [pdk_name]")
        print("  python cadence_pdk_manager.py devices [pdk_name]")