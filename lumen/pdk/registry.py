"""
LumenStudio - Unified PDK Registry

Discovers and manages multiple PDKs from filesystem paths.
Supports IHP SG13G2, SkyWater SKY130, GF180MCU, and custom PDKs.
"""
import os
import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict
from enum import Enum


class DeviceCategory(Enum):
    MOSFET = "MOSFET"
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
class PDKPin:
    """A device pin definition."""
    name: str
    direction: PinDirection = PinDirection.INOUT
    x: float = 0.0
    y: float = 0.0
    description: str = ""


@dataclass
class PDKParameter:
    """A parameter for a device."""
    name: str
    default: str = ""
    description: str = ""
    unit: str = ""
    display_name: str = ""


@dataclass
class PDKConstraint:
    """Design rule constraint for a device."""
    param: str
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    unit: str = ""
    description: str = ""


@dataclass
class PDKDevice:
    """A device available in a PDK."""
    name: str
    category: DeviceCategory = DeviceCategory.OTHER
    prefix: str = "X"
    model: str = ""
    description: str = ""
    pins: List[PDKPin] = field(default_factory=list)
    parameters: List[PDKParameter] = field(default_factory=list)
    constraints: List[PDKConstraint] = field(default_factory=list)
    symbol_name: str = ""
    library: str = ""


@dataclass
class PDKLayer:
    """A layer in the technology stack."""
    name: str
    gds_number: int = 0
    gds_datatype: int = 0
    purpose: str = "drawing"
    color: str = "#808080"
    description: str = ""


@dataclass
class PDKCorner:
    """A process corner definition."""
    name: str
    description: str = ""
    temperature: float = 25.0
    voltage: float = 1.8
    lib_section: str = ""


@dataclass
class PDKInfo:
    """Complete PDK definition."""
    name: str
    display_name: str = ""
    foundry: str = ""
    process: str = ""
    node: str = ""
    version: str = "1.0"
    description: str = ""
    license: str = ""
    
    root_path: str = ""
    models_path: str = ""
    tech_path: str = ""
    symbols_path: str = ""
    
    devices: List[PDKDevice] = field(default_factory=list)
    layers: List[PDKLayer] = field(default_factory=list)
    corners: List[PDKCorner] = field(default_factory=list)
    
    is_installed: bool = False
    is_builtin: bool = False


class PDKRegistry:
    """
    Central registry for PDK management.
    
    Discovers PDKs from:
    - Built-in definitions (Sky130, IHP SG13G2, GF180MCU)
    - User-specified paths (via add_path)
    - Environment variables (PDK_ROOT)
    """
    
    BUILTIN_PDKS = {
        "sky130": {
            "display_name": "SkyWater SKY130",
            "foundry": "SkyWater Technology",
            "node": "130nm",
            "description": "SkyWater 130nm open-source CMOS process",
        },
        "ihp_sg13g2": {
            "display_name": "IHP SG13G2",
            "foundry": "IHP Microelectronics", 
            "node": "130nm",
            "description": "IHP 130nm SiGe BiCMOS process",
        },
        "gf180mcu": {
            "display_name": "GlobalFoundries GF180MCU",
            "foundry": "GlobalFoundries",
            "node": "180nm",
            "description": "GF 180nm MCU process",
        },
    }
    
    def __init__(self, workspace_dir: str = ""):
        self.workspace = workspace_dir or os.path.join(
            os.path.expanduser("~"), "LumenWorkspace")
        os.makedirs(self.workspace, exist_ok=True)
        
        self._pdks: Dict[str, PDKInfo] = {}
        self._active_pdk: str = ""
        self._search_paths: List[str] = []
        
        self._load_config()
        self._discover_pdks()
    
    def _load_config(self):
        """Load registry configuration."""
        config_path = os.path.join(self.workspace, "pdk_config.json")
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                data = json.load(f)
                self._active_pdk = data.get("active_pdk", "")
                self._search_paths = data.get("search_paths", [])
    
    def _save_config(self):
        """Save registry configuration."""
        config_path = os.path.join(self.workspace, "pdk_config.json")
        data = {
            "active_pdk": self._active_pdk,
            "search_paths": self._search_paths,
        }
        with open(config_path, "w") as f:
            json.dump(data, f, indent=2)
    
    def _discover_pdks(self):
        """Discover all available PDKs."""
        # Add builtin definitions
        for name, info in self.BUILTIN_PDKS.items():
            pdk = PDKInfo(
                name=name,
                display_name=info["display_name"],
                foundry=info["foundry"],
                node=info["node"],
                description=info["description"],
                is_builtin=True,
            )
            self._pdks[name] = pdk
        
        # Scan search paths for installed PDKs
        for path in self._search_paths:
            if os.path.exists(path):
                self._scan_pdk_path(path)
        
        # Check environment variable
        pdk_root = os.environ.get("PDK_ROOT", "")
        if pdk_root and os.path.exists(pdk_root):
            self._scan_pdk_path(pdk_root)
    
    def _scan_pdk_path(self, path: str):
        """Scan a directory for PDKs."""
        path_obj = Path(path)
        
        # Check if path itself is a PDK
        pdk_info = self._identify_pdk(path_obj)
        if pdk_info:
            self._pdks[pdk_info.name] = pdk_info
            return
        
        # Scan subdirectories
        if path_obj.is_dir():
            for child in sorted(path_obj.iterdir()):
                if child.is_dir() and not child.name.startswith("."):
                    pdk_info = self._identify_pdk(child)
                    if pdk_info and pdk_info.name not in self._pdks:
                        self._pdks[pdk_info.name] = pdk_info
    
    def _identify_pdk(self, path: Path) -> Optional[PDKInfo]:
        """Identify if a directory is a PDK."""
        # Look for PDK markers
        markers = ["pdk.yaml", "pdk.json", "manifest.json", "tech.json", ".pdk_root"]
        has_marker = any((path / m).exists() for m in markers)
        
        # Check for model files
        has_models = any(path.glob("*.lib")) or any(path.glob("models/*.lib"))
        
        if not has_marker and not has_models:
            return None
        
        # Try to load PDK info
        pdk_json = path / "pdk.json"
        if pdk_json.exists():
            try:
                with open(pdk_json, "r") as f:
                    data = json.load(f)
                return self._pdk_from_json(path, data)
            except:
                pass
        
        # IHP PDK detection
        if "ihp" in path.name.lower() or "sg13g2" in path.name.lower():
            return self._create_ihp_pdk(path)
        
        # SkyWater detection
        if "sky130" in path.name.lower():
            return self._create_sky130_pdk(path)
        
        # GF180 detection
        if "gf180" in path.name.lower():
            return self._create_gf180_pdk(path)
        
        # Generic PDK
        return PDKInfo(
            name=path.name.lower().replace(" ", "_"),
            display_name=path.name.replace("_", " ").title(),
            root_path=str(path),
            is_installed=True,
        )
    
    def _pdk_from_json(self, path: Path, data: dict) -> PDKInfo:
        """Create PDK from pdk.json."""
        devices = []
        for d in data.get("devices", []):
            dev = PDKDevice(
                name=d.get("name", ""),
                category=DeviceCategory(d.get("category", "Other")),
                prefix=d.get("prefix", "X"),
                model=d.get("model", ""),
                description=d.get("description", ""),
            )
            devices.append(dev)
        
        layers = []
        for l in data.get("layers", []):
            layer = PDKLayer(
                name=l.get("name", ""),
                gds_number=l.get("gds", 0),
                gds_datatype=l.get("datatype", 0),
                color=l.get("color", "#808080"),
            )
            layers.append(layer)
        
        corners = []
        for c in data.get("corners", []):
            corner = PDKCorner(
                name=c.get("name", ""),
                description=c.get("description", ""),
                temperature=c.get("temperature", 25.0),
            )
            corners.append(corner)
        
        return PDKInfo(
            name=data.get("name", path.name),
            display_name=data.get("display_name", path.name.title()),
            foundry=data.get("foundry", ""),
            node=data.get("node", ""),
            description=data.get("description", ""),
            root_path=str(path),
            models_path=str(path / "models") if (path / "models").exists() else "",
            tech_path=str(path / "tech") if (path / "tech").exists() else "",
            symbols_path=str(path / "symbols") if (path / "symbols").exists() else "",
            devices=devices,
            layers=layers,
            corners=corners,
            is_installed=True,
        )
    
    def _create_ihp_pdk(self, path: Path) -> PDKInfo:
        """Create IHP SG13G2 PDK definition."""
        models_path = path / "libs.tech" / "ngspice" / "models"
        symbols_path = path / "libs.tech" / "xschem" / "sym"
        
        pdk = PDKInfo(
            name="ihp_sg13g2",
            display_name="IHP SG13G2",
            foundry="IHP Microelectronics",
            process="SG13G2",
            node="130nm",
            version="1.0",
            description="IHP 130nm SiGe BiCMOS process with HBT, MOS, passive devices",
            root_path=str(path),
            models_path=str(models_path) if models_path.exists() else "",
            tech_path=str(path / "libs.tech"),
            symbols_path=str(symbols_path) if symbols_path.exists() else "",
            is_installed=True,
            corners=[
                PDKCorner("tt", "Typical-Typical", 25.0, 1.2),
                PDKCorner("ff", "Fast-Fast", -40, 1.32),
                PDKCorner("ss", "Slow-Slow", 125, 1.08),
                PDKCorner("sf", "Slow-Fast", 25, 1.2),
                PDKCorner("fs", "Fast-Slow", 25, 1.2),
            ],
        )
        
        # Load devices from models
        pdk.devices = self._load_ihp_devices(models_path)
        
        return pdk
    
    def _load_ihp_devices(self, models_path: Path) -> List[PDKDevice]:
        """Load device definitions from IHP model files."""
        devices = []
        
        # MOSFET devices
        devices.extend([
            PDKDevice(
                name="sg13_lv_nmos",
                category=DeviceCategory.MOSFET,
                prefix="M",
                model="sg13_lv_nmos",
                description="1.2V Low-Voltage NMOS",
                pins=[PDKPin("D"), PDKPin("G"), PDKPin("S"), PDKPin("B")],
                parameters=[
                    PDKParameter("W", "0.5u", "Width"),
                    PDKParameter("L", "0.13u", "Length"),
                    PDKParameter("nf", "1", "Number of fingers"),
                ],
                symbol_name="nmos_symbol",
            ),
            PDKDevice(
                name="sg13_lv_pmos",
                category=DeviceCategory.MOSFET,
                prefix="M",
                model="sg13_lv_pmos",
                description="1.2V Low-Voltage PMOS",
                pins=[PDKPin("D"), PDKPin("G"), PDKPin("S"), PDKPin("B")],
                parameters=[
                    PDKParameter("W", "0.5u", "Width"),
                    PDKParameter("L", "0.13u", "Length"),
                    PDKParameter("nf", "1", "Number of fingers"),
                ],
                symbol_name="pmos_symbol",
            ),
            PDKDevice(
                name="sg13_hv_nmos",
                category=DeviceCategory.MOSFET,
                prefix="M",
                model="sg13_hv_nmos",
                description="3.3V High-Voltage NMOS",
                pins=[PDKPin("D"), PDKPin("G"), PDKPin("S"), PDKPin("B")],
                parameters=[
                    PDKParameter("W", "1u", "Width"),
                    PDKParameter("L", "0.4u", "Length"),
                ],
                symbol_name="nmos_hv_symbol",
            ),
            PDKDevice(
                name="sg13_hv_pmos",
                category=DeviceCategory.MOSFET,
                prefix="M",
                model="sg13_hv_pmos",
                description="3.3V High-Voltage PMOS",
                pins=[PDKPin("D"), PDKPin("G"), PDKPin("S"), PDKPin("B")],
                parameters=[
                    PDKParameter("W", "1u", "Width"),
                    PDKParameter("L", "0.4u", "Length"),
                ],
                symbol_name="pmos_hv_symbol",
            ),
        ])
        
        # HBT (BJT)
        devices.extend([
            PDKDevice(
                name="npn13g2",
                category=DeviceCategory.BJT,
                prefix="Q",
                model="npn13g2",
                description="SiGe HBT (fT=250GHz)",
                pins=[PDKPin("C"), PDKPin("B"), PDKPin("E")],
                parameters=[
                    PDKParameter("le", "0.9u", "Emitter length"),
                    PDKParameter("we", "0.07u", "Emitter width"),
                    PDKParameter("mult", "1", "Multiplier"),
                ],
                symbol_name="npn_symbol",
            ),
            PDKDevice(
                name="npn13g2v",
                category=DeviceCategory.BJT,
                prefix="Q",
                model="npn13g2v",
                description="SiGe HBT Vertical",
                pins=[PDKPin("C"), PDKPin("B"), PDKPin("E")],
                parameters=[
                    PDKParameter("le", "0.9u", "Emitter length"),
                    PDKParameter("mult", "1", "Multiplier"),
                ],
                symbol_name="npn_symbol",
            ),
        ])
        
        # Resistors
        devices.extend([
            PDKDevice(
                name="rsil",
                category=DeviceCategory.RESISTOR,
                prefix="R",
                model="rsil",
                description="Silicided Poly Resistor",
                pins=[PDKPin("PLUS"), PDKPin("MINUS")],
                parameters=[
                    PDKParameter("R", "1k", "Resistance"),
                    PDKParameter("W", "0.5u", "Width"),
                    PDKParameter("L", "2u", "Length"),
                ],
                symbol_name="res_symbol",
            ),
            PDKDevice(
                name="rppd",
                category=DeviceCategory.RESISTOR,
                prefix="R",
                model="rppd",
                description="P+ Poly Resistor (High-R)",
                pins=[PDKPin("PLUS"), PDKPin("MINUS")],
                parameters=[
                    PDKParameter("R", "10k", "Resistance"),
                    PDKParameter("W", "0.5u", "Width"),
                    PDKParameter("L", "5u", "Length"),
                ],
                symbol_name="res_symbol",
            ),
            PDKDevice(
                name="rhig",
                category=DeviceCategory.RESISTOR,
                prefix="R",
                model="rhig",
                description="High-Resistance Poly Resistor",
                pins=[PDKPin("PLUS"), PDKPin("MINUS")],
                parameters=[
                    PDKParameter("R", "100k", "Resistance"),
                    PDKParameter("W", "0.35u", "Width"),
                    PDKParameter("L", "10u", "Length"),
                ],
                symbol_name="res_symbol",
            ),
        ])
        
        # Capacitors
        devices.extend([
            PDKDevice(
                name="cmim",
                category=DeviceCategory.CAPACITOR,
                prefix="C",
                model="cmim",
                description="MIM Capacitor",
                pins=[PDKPin("PLUS"), PDKPin("MINUS")],
                parameters=[
                    PDKParameter("C", "1p", "Capacitance"),
                    PDKParameter("W", "5u", "Width"),
                    PDKParameter("L", "5u", "Length"),
                ],
                symbol_name="cap_symbol",
            ),
            PDKDevice(
                name="cap_mos",
                category=DeviceCategory.CAPACITOR,
                prefix="C",
                model="cap_mos",
                description="MOS Varactor",
                pins=[PDKPin("PLUS"), PDKPin("MINUS")],
                parameters=[
                    PDKParameter("C", "1p", "Capacitance"),
                ],
                symbol_name="cap_symbol",
            ),
        ])
        
        # Diodes
        devices.extend([
            PDKDevice(
                name="diode_pn",
                category=DeviceCategory.DIODE,
                prefix="D",
                model="diode_pn",
                description="PN Junction Diode",
                pins=[PDKPin("PLUS"), PDKPin("MINUS")],
                parameters=[
                    PDKParameter("area", "1", "Area"),
                ],
                symbol_name="diode_symbol",
            ),
            PDKDevice(
                name="diode_schottky",
                category=DeviceCategory.DIODE,
                prefix="D",
                model="diode_schottky",
                description="Schottky Diode",
                pins=[PDKPin("PLUS"), PDKPin("MINUS")],
                parameters=[
                    PDKParameter("area", "1", "Area"),
                ],
                symbol_name="diode_symbol",
            ),
        ])
        
        return devices
    
    def _create_sky130_pdk(self, path: Path) -> PDKInfo:
        """Create SkyWater SKY130 PDK definition."""
        return PDKInfo(
            name="sky130",
            display_name="SkyWater SKY130",
            foundry="SkyWater Technology",
            process="SKY130",
            node="130nm",
            version="1.0",
            description="SkyWater 130nm open-source CMOS process",
            root_path=str(path),
            is_installed=True,
            corners=[
                PDKCorner("tt", "Typical-Typical", 25.0, 1.8),
                PDKCorner("ff", "Fast-Fast", -40, 1.98),
                PDKCorner("ss", "Slow-Slow", 125, 1.62),
            ],
        )
    
    def _create_gf180_pdk(self, path: Path) -> PDKInfo:
        """Create GF180MCU PDK definition."""
        return PDKInfo(
            name="gf180mcu",
            display_name="GlobalFoundries GF180MCU",
            foundry="GlobalFoundries",
            process="GF180MCU",
            node="180nm",
            version="1.0",
            description="GF 180nm MCU process",
            root_path=str(path),
            is_installed=True,
            corners=[
                PDKCorner("typical", "Typical", 25.0, 3.3),
                PDKCorner("ff", "Fast-Fast", -40, 3.63),
                PDKCorner("ss", "Slow-Slow", 125, 2.97),
            ],
        )
    
    def add_search_path(self, path: str):
        """Add a path to search for PDKs."""
        if path not in self._search_paths:
            self._search_paths.append(path)
            self._save_config()
            self._scan_pdk_path(path)
    
    def get_all_pdks(self) -> List[PDKInfo]:
        """Get all available PDKs."""
        return list(self._pdks.values())
    
    def get_pdk(self, name: str) -> Optional[PDKInfo]:
        """Get a specific PDK by name."""
        return self._pdks.get(name)
    
    def get_active_pdk(self) -> Optional[PDKInfo]:
        """Get the currently active PDK."""
        if self._active_pdk:
            return self._pdks.get(self._active_pdk)
        return None
    
    def set_active_pdk(self, name: str) -> bool:
        """Set the active PDK."""
        if name in self._pdks:
            self._active_pdk = name
            self._save_config()
            return True
        return False
    
    def get_devices(self, pdk_name: str = "", category: DeviceCategory = None) -> List[PDKDevice]:
        """Get devices from a PDK, optionally filtered by category."""
        pdk = self._pdks.get(pdk_name or self._active_pdk)
        if not pdk:
            return []
        
        devices = pdk.devices
        if category:
            devices = [d for d in devices if d.category == category]
        return devices
    
    def find_device(self, name: str) -> Optional[PDKDevice]:
        """Find a device by name in active PDK."""
        pdk = self.get_active_pdk()
        if not pdk:
            return None
        for device in pdk.devices:
            if device.name == name:
                return device
        return None


def create_registry(workspace: str = "") -> PDKRegistry:
    """Create and return a PDK registry instance."""
    return PDKRegistry(workspace)