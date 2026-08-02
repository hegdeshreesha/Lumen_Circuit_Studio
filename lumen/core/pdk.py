"""
Lumen Circuit Studio — PDK Registry & Management

Process Design Kit management system supporting open-source PDKs.
Handles technology files, device models, layer maps, and DRC/LVS rules.
"""
import os
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PDKDevice:
    """A device available in a PDK."""
    name: str
    category: str  # "MOSFET", "Resistor", "Capacitor", "Diode", "BJT", "Inductor"
    symbol: str  # Symbol name in primitives
    prefix: str  # SPICE prefix
    model: str  # SPICE model name
    description: str = ""
    parameters: dict = field(default_factory=dict)
    pins: list = field(default_factory=list)


@dataclass
class PDKLayer:
    """A layer in the technology stack."""
    name: str
    gds_number: int
    gds_datatype: int = 0
    purpose: str = "drawing"
    color: str = "#808080"
    description: str = ""


@dataclass
class PDKInfo:
    """Complete PDK definition."""
    name: str
    display_name: str
    foundry: str
    process: str
    node: str  # e.g. "130nm", "180nm"
    version: str = "1.0"
    description: str = ""
    license: str = "Apache-2.0"
    url: str = ""

    # Paths
    install_path: str = ""
    model_path: str = ""
    techfile_path: str = ""

    # Content
    corners: list = field(default_factory=list)
    devices: list = field(default_factory=list)
    layers: list = field(default_factory=list)
    supply_voltage: float = 1.8
    temperature_range: tuple = (-40, 125)

    # Status
    installed: bool = False


# ── Built-in PDK Definitions ─────────────────────────────────

def _sky130_pdk() -> PDKInfo:
    return PDKInfo(
        name="sky130",
        display_name="SkyWater SKY130",
        foundry="SkyWater Technology",
        process="SKY130",
        node="130nm",
        version="0.0.2",
        description="SkyWater 130nm open-source CMOS process. "
                    "5 metal layers, 1.8V core / 3.3V I/O.",
        license="Apache-2.0",
        url="https://github.com/google/skywater-pdk",
        supply_voltage=1.8,
        temperature_range=(-40, 125),
        corners=[
            {"name": "tt", "description": "Typical-Typical", "temp": 25},
            {"name": "ff", "description": "Fast-Fast", "temp": -40},
            {"name": "ss", "description": "Slow-Slow", "temp": 125},
            {"name": "sf", "description": "Slow-Fast", "temp": 25},
            {"name": "fs", "description": "Fast-Slow", "temp": 25},
        ],
        devices=[
            PDKDevice("sky130_fd_pr__nfet_01v8", "MOSFET", "nmos", "M",
                      "sky130_fd_pr__nfet_01v8", "1.8V NMOS",
                      {"W": "0.42u", "L": "0.15u", "nf": "1", "mult": "1"},
                      ["D", "G", "S", "B"]),
            PDKDevice("sky130_fd_pr__pfet_01v8", "MOSFET", "pmos", "M",
                      "sky130_fd_pr__pfet_01v8", "1.8V PMOS",
                      {"W": "0.55u", "L": "0.15u", "nf": "1", "mult": "1"},
                      ["D", "G", "S", "B"]),
            PDKDevice("sky130_fd_pr__nfet_01v8_lvt", "MOSFET", "nmos", "M",
                      "sky130_fd_pr__nfet_01v8_lvt", "1.8V Low-Vt NMOS",
                      {"W": "0.42u", "L": "0.15u", "nf": "1"},
                      ["D", "G", "S", "B"]),
            PDKDevice("sky130_fd_pr__pfet_01v8_hvt", "MOSFET", "pmos", "M",
                      "sky130_fd_pr__pfet_01v8_hvt", "1.8V High-Vt PMOS",
                      {"W": "0.55u", "L": "0.15u", "nf": "1"},
                      ["D", "G", "S", "B"]),
            PDKDevice("sky130_fd_pr__nfet_03v3_nvt", "MOSFET", "nmos", "M",
                      "sky130_fd_pr__nfet_03v3_nvt", "3.3V Native NMOS",
                      {"W": "0.42u", "L": "0.50u", "nf": "1"},
                      ["D", "G", "S", "B"]),
            PDKDevice("sky130_fd_pr__pfet_01v8_mvt", "MOSFET", "pmos", "M",
                      "sky130_fd_pr__pfet_01v8_mvt", "1.8V Medium-Vt PMOS",
                      {"W": "0.55u", "L": "0.15u", "nf": "1"},
                      ["D", "G", "S", "B"]),
            PDKDevice("sky130_fd_pr__res_generic_nd", "Resistor", "res", "R",
                      "sky130_fd_pr__res_generic_nd", "N-diffusion Resistor",
                      {"W": "0.42u", "L": "1u", "mult": "1"},
                      ["PLUS", "MINUS"]),
            PDKDevice("sky130_fd_pr__res_high_po", "Resistor", "res", "R",
                      "sky130_fd_pr__res_high_po", "High-Resistance Poly Resistor",
                      {"W": "0.35u", "L": "1u", "mult": "1"},
                      ["PLUS", "MINUS"]),
            PDKDevice("sky130_fd_pr__cap_mim_m3_1", "Capacitor", "cap", "C",
                      "sky130_fd_pr__cap_mim_m3_1", "MIM Capacitor (M3-M4)",
                      {"W": "2u", "L": "2u", "mult": "1"},
                      ["PLUS", "MINUS"]),
            PDKDevice("sky130_fd_pr__diode_pw2nd_05v5", "Diode", "diode", "D",
                      "sky130_fd_pr__diode_pw2nd_05v5", "PW-ND Junction Diode",
                      {"area": "1p", "pj": "4u"},
                      ["PLUS", "MINUS"]),
            PDKDevice("sky130_fd_pr__npn_05v5", "BJT", "npn", "Q",
                      "sky130_fd_pr__npn_05v5", "5V NPN BJT",
                      {"mult": "1"},
                      ["C", "B", "E"]),
        ],
        layers=[
            PDKLayer("diff", 65, 20, "drawing", "#c8c846"),
            PDKLayer("poly", 66, 20, "drawing", "#ff0000"),
            PDKLayer("nwell", 64, 20, "drawing", "#aaffaa"),
            PDKLayer("pwell", 64, 44, "drawing", "#ffaaaa"),
            PDKLayer("li1", 67, 20, "drawing", "#c8c8ff"),
            PDKLayer("met1", 68, 20, "drawing", "#5050ff"),
            PDKLayer("met2", 69, 20, "drawing", "#ff50ff"),
            PDKLayer("met3", 70, 20, "drawing", "#50ffff"),
            PDKLayer("met4", 71, 20, "drawing", "#ffa050"),
            PDKLayer("met5", 72, 20, "drawing", "#ffff50"),
        ],
    )


def _ihp_open_pdk() -> PDKInfo:
    return PDKInfo(
        name="ihp_sg13g2",
        display_name="IHP SG13G2 (Open)",
        foundry="IHP Microelectronics",
        process="SG13G2",
        node="130nm",
        version="1.0",
        description="IHP 130nm SiGe BiCMOS open-source process. "
                    "Supports RF/mmWave up to 250 GHz fT HBTs.",
        license="Apache-2.0",
        url="https://github.com/IHP-GmbH/IHP-Open-PDK",
        supply_voltage=1.2,
        temperature_range=(-40, 125),
        corners=[
            {"name": "typ", "description": "Typical", "temp": 27},
            {"name": "fast", "description": "Fast", "temp": -40},
            {"name": "slow", "description": "Slow", "temp": 125},
        ],
        devices=[
            PDKDevice("sg13_lv_nmos", "MOSFET", "nmos", "M",
                      "sg13_lv_nmos", "1.2V LV NMOS",
                      {"W": "0.5u", "L": "0.13u", "nf": "1"},
                      ["D", "G", "S", "B"]),
            PDKDevice("sg13_lv_pmos", "MOSFET", "pmos", "M",
                      "sg13_lv_pmos", "1.2V LV PMOS",
                      {"W": "0.5u", "L": "0.13u", "nf": "1"},
                      ["D", "G", "S", "B"]),
            PDKDevice("sg13_hv_nmos", "MOSFET", "nmos", "M",
                      "sg13_hv_nmos", "3.3V HV NMOS",
                      {"W": "1u", "L": "0.4u", "nf": "1"},
                      ["D", "G", "S", "B"]),
            PDKDevice("sg13_hv_pmos", "MOSFET", "pmos", "M",
                      "sg13_hv_pmos", "3.3V HV PMOS",
                      {"W": "1u", "L": "0.4u", "nf": "1"},
                      ["D", "G", "S", "B"]),
            PDKDevice("npn13G2", "BJT", "npn", "Q",
                      "npn13G2", "SiGe HBT (fT=250GHz)",
                      {"le": "0.9u", "we": "0.07u", "mult": "1"},
                      ["C", "B", "E"]),
            PDKDevice("npn13G2v", "BJT", "npn", "Q",
                      "npn13G2v", "SiGe HBT Vertical",
                      {"le": "0.9u", "we": "0.07u", "mult": "1"},
                      ["C", "B", "E"]),
            PDKDevice("rsil", "Resistor", "res", "R",
                      "rsil", "Silicided Poly Resistor",
                      {"W": "0.5u", "L": "2u"},
                      ["PLUS", "MINUS"]),
            PDKDevice("rppd", "Resistor", "res", "R",
                      "rppd", "P+ Poly Resistor (High-R)",
                      {"W": "0.5u", "L": "5u"},
                      ["PLUS", "MINUS"]),
            PDKDevice("cmim", "Capacitor", "cap", "C",
                      "cmim", "MIM Capacitor",
                      {"W": "5u", "L": "5u"},
                      ["PLUS", "MINUS"]),
        ],
        layers=[
            PDKLayer("Activ", 1, 0, "drawing", "#c8c846"),
            PDKLayer("GatPoly", 5, 0, "drawing", "#ff0000"),
            PDKLayer("NWell", 31, 0, "drawing", "#aaffaa"),
            PDKLayer("Metal1", 8, 0, "drawing", "#5050ff"),
            PDKLayer("Metal2", 10, 0, "drawing", "#ff50ff"),
            PDKLayer("Metal3", 30, 0, "drawing", "#50ffff"),
            PDKLayer("Metal4", 50, 0, "drawing", "#ffa050"),
            PDKLayer("Metal5", 67, 0, "drawing", "#ffff50"),
            PDKLayer("TopMetal1", 53, 0, "drawing", "#aa88cc"),
            PDKLayer("TopMetal2", 54, 0, "drawing", "#88ccaa"),
        ],
    )


def _gf180mcu_pdk() -> PDKInfo:
    return PDKInfo(
        name="gf180mcu",
        display_name="GlobalFoundries GF180MCU",
        foundry="GlobalFoundries",
        process="GF180MCU",
        node="180nm",
        version="1.0",
        description="GlobalFoundries 180nm MCU open-source process. "
                    "3.3V/5V/6V options, 5 metal layers.",
        license="Apache-2.0",
        url="https://github.com/google/gf180mcu-pdk",
        supply_voltage=3.3,
        temperature_range=(-40, 175),
        corners=[
            {"name": "typical", "description": "Typical", "temp": 25},
            {"name": "ff", "description": "Fast-Fast", "temp": -40},
            {"name": "ss", "description": "Slow-Slow", "temp": 125},
            {"name": "sf", "description": "Slow-Fast", "temp": 25},
            {"name": "fs", "description": "Fast-Slow", "temp": 25},
        ],
        devices=[
            PDKDevice("nfet_03v3", "MOSFET", "nmos", "M",
                      "nfet_03v3", "3.3V NMOS",
                      {"W": "0.44u", "L": "0.28u", "nf": "1", "mult": "1"},
                      ["D", "G", "S", "B"]),
            PDKDevice("pfet_03v3", "MOSFET", "pmos", "M",
                      "pfet_03v3", "3.3V PMOS",
                      {"W": "0.5u", "L": "0.28u", "nf": "1", "mult": "1"},
                      ["D", "G", "S", "B"]),
            PDKDevice("nfet_05v0", "MOSFET", "nmos", "M",
                      "nfet_05v0", "5V NMOS",
                      {"W": "0.8u", "L": "0.6u", "nf": "1"},
                      ["D", "G", "S", "B"]),
            PDKDevice("pfet_05v0", "MOSFET", "pmos", "M",
                      "pfet_05v0", "5V PMOS",
                      {"W": "0.8u", "L": "0.6u", "nf": "1"},
                      ["D", "G", "S", "B"]),
            PDKDevice("nfet_06v0", "MOSFET", "nmos", "M",
                      "nfet_06v0", "6V NMOS",
                      {"W": "1u", "L": "0.7u", "nf": "1"},
                      ["D", "G", "S", "B"]),
            PDKDevice("pfet_06v0", "MOSFET", "pmos", "M",
                      "pfet_06v0", "6V PMOS",
                      {"W": "1u", "L": "0.7u", "nf": "1"},
                      ["D", "G", "S", "B"]),
            PDKDevice("nplus_u", "Resistor", "res", "R",
                      "nplus_u", "N+ Diffusion Resistor",
                      {"W": "0.42u", "L": "2u"},
                      ["PLUS", "MINUS"]),
            PDKDevice("pplus_u", "Resistor", "res", "R",
                      "pplus_u", "P+ Diffusion Resistor",
                      {"W": "0.42u", "L": "2u"},
                      ["PLUS", "MINUS"]),
            PDKDevice("rm1", "Resistor", "res", "R",
                      "rm1", "Metal1 Resistor",
                      {"W": "0.5u", "L": "5u"},
                      ["PLUS", "MINUS"]),
            PDKDevice("mim_1p5fF", "Capacitor", "cap", "C",
                      "mim_1p5fF", "MIM Capacitor (1.5 fF/µm²)",
                      {"W": "5u", "L": "5u"},
                      ["PLUS", "MINUS"]),
            PDKDevice("np_3p3", "Diode", "diode", "D",
                      "np_3p3", "N+/P-well Diode 3.3V",
                      {"area": "1p", "pj": "4u"},
                      ["PLUS", "MINUS"]),
        ],
        layers=[
            PDKLayer("comp", 22, 0, "drawing", "#c8c846"),
            PDKLayer("poly2", 30, 0, "drawing", "#ff0000"),
            PDKLayer("nwell", 21, 0, "drawing", "#aaffaa"),
            PDKLayer("metal1", 34, 0, "drawing", "#5050ff"),
            PDKLayer("metal2", 36, 0, "drawing", "#ff50ff"),
            PDKLayer("metal3", 42, 0, "drawing", "#50ffff"),
            PDKLayer("metal4", 46, 0, "drawing", "#ffa050"),
            PDKLayer("metal5", 81, 0, "drawing", "#ffff50"),
        ],
    )


# ── PDK Registry ──────────────────────────────────────────────

class PDKRegistry:
    """Central registry for all available PDKs."""

    def __init__(self, workspace: str = ""):
        self.workspace = workspace or os.path.join(
            os.path.expanduser("~"), "LumenWorkspace")
        self._pdk_dir = os.path.join(self.workspace, "pdks")
        os.makedirs(self._pdk_dir, exist_ok=True)

        self._pdks: dict[str, PDKInfo] = {}
        self._active_pdk: str = ""
        self._load_builtin_pdks()
        self._load_config()

    def _load_builtin_pdks(self):
        self._pdks["sky130"] = _sky130_pdk()
        self._pdks["ihp_sg13g2"] = _ihp_open_pdk()
        self._pdks["gf180mcu"] = _gf180mcu_pdk()
        # Check installation status
        for name, pdk in self._pdks.items():
            pdk_path = os.path.join(self._pdk_dir, name)
            pdk.install_path = pdk_path
            pdk.installed = os.path.isdir(pdk_path)

    def _load_config(self):
        cfg_path = os.path.join(self._pdk_dir, "config.json")
        if os.path.isfile(cfg_path):
            with open(cfg_path) as f:
                cfg = json.load(f)
            self._active_pdk = cfg.get("active", "")

    def _save_config(self):
        cfg_path = os.path.join(self._pdk_dir, "config.json")
        with open(cfg_path, "w") as f:
            json.dump({"active": self._active_pdk}, f, indent=2)

    def get_all_pdks(self) -> list[PDKInfo]:
        return list(self._pdks.values())

    def get_pdk(self, name: str) -> PDKInfo | None:
        return self._pdks.get(name)

    def get_active_pdk(self) -> PDKInfo | None:
        if self._active_pdk:
            return self._pdks.get(self._active_pdk)
        return None

    def set_active_pdk(self, name: str):
        if name in self._pdks:
            self._active_pdk = name
            self._save_config()

    def get_active_name(self) -> str:
        return self._active_pdk

    def install_pdk(self, name: str) -> bool:
        """Create the PDK directory structure (stub install)."""
        pdk = self._pdks.get(name)
        if not pdk:
            return False
        pdk_path = os.path.join(self._pdk_dir, name)
        os.makedirs(pdk_path, exist_ok=True)
        os.makedirs(os.path.join(pdk_path, "models"), exist_ok=True)
        os.makedirs(os.path.join(pdk_path, "tech"), exist_ok=True)
        os.makedirs(os.path.join(pdk_path, "cells"), exist_ok=True)
        # Write device catalog
        dev_list = []
        for d in pdk.devices:
            dev_list.append({
                "name": d.name, "category": d.category,
                "model": d.model, "prefix": d.prefix,
                "description": d.description,
                "parameters": d.parameters, "pins": d.pins,
            })
        with open(os.path.join(pdk_path, "devices.json"), "w") as f:
            json.dump(dev_list, f, indent=2)
        # Write layer map
        layer_list = []
        for l in pdk.layers:
            layer_list.append({
                "name": l.name, "gds": l.gds_number,
                "datatype": l.gds_datatype, "purpose": l.purpose,
                "color": l.color, "description": l.description,
            })
        with open(os.path.join(pdk_path, "layers.json"), "w") as f:
            json.dump(layer_list, f, indent=2)
        # Write corners
        with open(os.path.join(pdk_path, "corners.json"), "w") as f:
            json.dump(pdk.corners, f, indent=2)
        # Write tech info
        with open(os.path.join(pdk_path, "tech.json"), "w") as f:
            json.dump({
                "name": pdk.name, "display_name": pdk.display_name,
                "foundry": pdk.foundry, "node": pdk.node,
                "supply_voltage": pdk.supply_voltage,
                "temp_range": list(pdk.temperature_range),
            }, f, indent=2)
        pdk.installed = True
        pdk.install_path = pdk_path
        return True

    def get_pdk_devices(self, name: str, category: str = "") -> list[PDKDevice]:
        """Get devices from a PDK, optionally filtered by category."""
        pdk = self._pdks.get(name)
        if not pdk:
            return []
        if category:
            return [d for d in pdk.devices if d.category == category]
        return list(pdk.devices)


# ── Symbol Generation ─────────────────────────────────────────

def generate_symbol_data(device: PDKDevice, pdk_name: str = "") -> dict:
    """Generate a schematic symbol dict for a PDK device."""
    category = device.category
    if hasattr(category, "value"):
        category = category.value
    if category == "MOSFET":
        return _gen_mosfet_symbol(device, pdk_name)
    elif category == "Resistor":
        return _gen_resistor_symbol(device, pdk_name)
    elif category == "Capacitor":
        return _gen_capacitor_symbol(device, pdk_name)
    elif category == "Diode":
        return _gen_diode_symbol(device, pdk_name)
    elif category == "BJT":
        return _gen_bjt_symbol(device, pdk_name)
    elif category == "Inductor":
        return _gen_inductor_symbol(device, pdk_name)
    else:
        return _gen_generic_symbol(device, pdk_name)


def _base_symbol(device, pdk_name):
    # Support both legacy dict params and newer list[PDKParameter]-style params.
    params = []
    raw_params = getattr(device, "parameters", {})
    if isinstance(raw_params, dict):
        params = [{"name": k, "default": v} for k, v in raw_params.items()]
    elif isinstance(raw_params, list):
        for p in raw_params:
            if isinstance(p, dict):
                pname = p.get("name", "")
                pdefault = p.get("default", "")
            else:
                pname = getattr(p, "name", "")
                pdefault = getattr(p, "default", "")
            if pname:
                params.append({"name": pname, "default": pdefault})
    return {
        "type": "symbol",
        "name": device.name,
        "library": f"pdk:{pdk_name}" if pdk_name else "pdk:",
        "prefix": device.prefix,
        "model": device.model,
        "description": device.description,
        "parameters": params,
        "shapes": [],
        "pins": [],
        "label": {"text": f"@name\\n{device.name}", "x": 15, "y": -25},
    }


def _gen_mosfet_symbol(dev, pdk_name):
    s = _base_symbol(dev, pdk_name)
    symbol_name = str(getattr(dev, "symbol", "")).lower()
    dev_name = str(getattr(dev, "name", "")).lower()
    is_pmos = ("pmos" in symbol_name) or ("pfet" in dev_name) or ("pmos" in dev_name)
    
    # custom IC editor MOSFET (4-Terminal)
    # Channel and gate
    s["shapes"] = [
        {"type": "line", "x1": 0, "y1": -15, "x2": 0, "y2": 15},     # channel
        {"type": "line", "x1": -10, "y1": -15, "x2": -10, "y2": 15}, # gate bar
        {"type": "line", "x1": 0, "y1": -15, "x2": 0, "y2": -30},    # drain lead
        {"type": "line", "x1": 0, "y1": 15, "x2": 0, "y2": 30},      # source lead
        {"type": "line", "x1": 0, "y1": 0, "x2": 30, "y2": 0},       # bulk lead
    ]

    if is_pmos:
        # Gate with inversion circle
        s["shapes"].append({"type": "circle", "cx": -13, "cy": 0, "r": 3})
        s["shapes"].append({"type": "line", "x1": -30, "y1": 0, "x2": -16, "y2": 0})
        # Arrow on source pointing UP (into channel)
        s["shapes"].append({"type": "polygon", "points": [[-4, 23], [4, 23], [0, 15]]})
    else:
        # Gate direct connection
        s["shapes"].append({"type": "line", "x1": -30, "y1": 0, "x2": -10, "y2": 0})
        # Arrow on source pointing DOWN (out of channel)
        s["shapes"].append({"type": "polygon", "points": [[-4, 15], [4, 15], [0, 23]]})

    s["pins"] = [
        {"name": "D", "x": 0, "y": -30},
        {"name": "G", "x": -30, "y": 0},
        {"name": "S", "x": 0, "y": 30},
        {"name": "B", "x": 30, "y": 0},
    ]
    return s


def _gen_resistor_symbol(dev, pdk_name):
    s = _base_symbol(dev, pdk_name)
    # custom IC editor zigzag resistor
    s["shapes"] = [
        {"type": "line", "x1": 0, "y1": -30, "x2": 0, "y2": -16},
        {"type": "polyline", "points": [
            [0, -16], [8, -12], [-8, -4], [8, 4], [-8, 12], [0, 16]]},
        {"type": "line", "x1": 0, "y1": 16, "x2": 0, "y2": 30},
    ]
    s["pins"] = [
        {"name": "PLUS", "x": 0, "y": -30},
        {"name": "MINUS", "x": 0, "y": 30},
    ]
    return s


def _gen_capacitor_symbol(dev, pdk_name):
    s = _base_symbol(dev, pdk_name)
    # custom IC editor parallel plate capacitor
    s["shapes"] = [
        {"type": "line", "x1": 0, "y1": -30, "x2": 0, "y2": -4},
        {"type": "line", "x1": -12, "y1": -4, "x2": 12, "y2": -4},   # top plate
        {"type": "line", "x1": -12, "y1": 4, "x2": 12, "y2": 4},     # bottom plate
        {"type": "line", "x1": 0, "y1": 4, "x2": 0, "y2": 30},
    ]
    s["pins"] = [
        {"name": "PLUS", "x": 0, "y": -30},
        {"name": "MINUS", "x": 0, "y": 30},
    ]
    return s


def _gen_diode_symbol(dev, pdk_name):
    s = _base_symbol(dev, pdk_name)
    # custom IC editor diode
    s["shapes"] = [
        {"type": "line", "x1": 0, "y1": -30, "x2": 0, "y2": -8},
        {"type": "polygon", "points": [[-10, -8], [10, -8], [0, 8]]},  # triangle (anode)
        {"type": "line", "x1": -10, "y1": 8, "x2": 10, "y2": 8},      # bar (cathode)
        {"type": "line", "x1": 0, "y1": 8, "x2": 0, "y2": 30},
    ]
    s["pins"] = [
        {"name": "PLUS", "x": 0, "y": -30},
        {"name": "MINUS", "x": 0, "y": 30},
    ]
    return s


def _gen_bjt_symbol(dev, pdk_name):
    s = _base_symbol(dev, pdk_name)
    symbol_name = str(getattr(dev, "symbol", "")).lower()
    dev_name = str(getattr(dev, "name", "")).lower()
    is_pnp = ("pnp" in symbol_name) or ("pnp" in dev_name)
    # custom IC editor BJT
    s["shapes"] = [
        {"type": "line", "x1": -10, "y1": -15, "x2": -10, "y2": 15},  # base bar
        {"type": "line", "x1": -30, "y1": 0, "x2": -10, "y2": 0},     # base lead
        {"type": "line", "x1": -10, "y1": -8, "x2": 15, "y2": -25},   # collector diagonal
        {"type": "line", "x1": 15, "y1": -25, "x2": 15, "y2": -30},   # collector lead
        {"type": "line", "x1": -10, "y1": 8, "x2": 15, "y2": 25},     # emitter diagonal
        {"type": "line", "x1": 15, "y1": 25, "x2": 15, "y2": 30},     # emitter lead
    ]
    
    if not is_pnp:
        # NPN Arrow pointing out
        s["shapes"].append({"type": "polygon", "points": [[3, 17], [12, 26], [14, 15]]})
    else:
        # PNP Arrow pointing in
        s["shapes"].append({"type": "polygon", "points": [[-7, 10], [5, 4], [2, 16]]})

    s["pins"] = [
        {"name": "C", "x": 15, "y": -30},
        {"name": "B", "x": -30, "y": 0},
        {"name": "E", "x": 15, "y": 30},
    ]
    return s


def _gen_inductor_symbol(dev, pdk_name):
    s = _base_symbol(dev, pdk_name)
    # custom IC editor inductor (3 loops)
    s["shapes"] = [
        {"type": "line", "x1": 0, "y1": -30, "x2": 0, "y2": -15},
        {"type": "arc", "cx": 0, "cy": -10, "rx": 5, "ry": 5, "start": -90, "span": 180},
        {"type": "arc", "cx": 0, "cy": 0, "rx": 5, "ry": 5, "start": -90, "span": 180},
        {"type": "arc", "cx": 0, "cy": 10, "rx": 5, "ry": 5, "start": -90, "span": 180},
        {"type": "line", "x1": 0, "y1": 15, "x2": 0, "y2": 30},
    ]
    s["pins"] = [
        {"name": "PLUS", "x": 0, "y": -30},
        {"name": "MINUS", "x": 0, "y": 30},
    ]
    return s


def _gen_generic_symbol(dev, pdk_name):
    s = _base_symbol(dev, pdk_name)
    s["shapes"] = [
        {"type": "rect", "x": -20, "y": -20, "w": 40, "h": 40},
    ]
    y = -15
    for pin_name in dev.pins:
        s["pins"].append({"name": pin_name, "x": -30, "y": y})
        s["shapes"].append({"type": "line", "x1": -30, "y1": y, "x2": -20, "y2": y})
        y += 15
    return s
