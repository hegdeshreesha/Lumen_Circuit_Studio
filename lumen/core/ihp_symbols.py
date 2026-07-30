"""
Lumen Circuit Studio — IHP SG13G2 PDK Symbol Generator

Generates symbols that match the IHP SG13G2 PDK device details:
https://github.com/IHP-GmbH/IHP-Open-PDK

Based on official Xschem .sym files from the IHP PDK distribution:
- sg13_lv_nmos.sym, sg13_lv_pmos.sym (MOSFETs)
- Other primitive devices from libs.tech/xschem/sg13g2_pr/
"""
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class IHPSymbolGenerator:
    """Generate IHP SG13G2-compliant symbols matching official PDK references."""

    _LAYOUT_CELLS = {
        "sg13_lv_nmos": ("nmos", {}), "sg13_lv_pmos": ("pmos", {}),
        "sg13_hv_nmos": ("nmosHV", {}), "sg13_hv_pmos": ("pmosHV", {}),
        "sg13_lv_rf_nmos": ("rfnmos", {"rfmode": 1}),
        "sg13_lv_rf_pmos": ("rfpmos", {"rfmode": 1}),
        "sg13_hv_rf_nmos": ("rfnmosHV", {"rfmode": 1}),
        "sg13_hv_rf_pmos": ("rfpmosHV", {"rfmode": 1}),
        "cap_cmim": ("cmim", {}), "cap_rfcmim": ("rfcmim", {}),
        "rppd": ("rppd", {}), "rhigh": ("rhigh", {}), "rsil": ("rsil", {}),
        "npn13G2": ("npn13G2", {}), "npn13G2l": ("npn13G2L", {}),
        "npn13G2v": ("npn13G2V", {}),
    }

    def _layout_binding(self, name: str, parameters: list[str]) -> Dict[str, Any]:
        pcell, forced = self._LAYOUT_CELLS[name]
        binding = {
            "technology": "sg13g2", "library": "SG13_dev", "pcell": pcell,
            "parameter_map": {key: key for key in parameters if key != "m"},
            "forced_parameters": forced,
        }
        if "m" in parameters:
            binding["multiplicity_parameter"] = "m"
        return binding
    
    def generate_nmos(self, name: str = "sg13_lv_nmos", model: str = "sg13_lv_nmos") -> Dict[str, Any]:
        """
        Generate LV NMOS symbol matching IHP official sg13_lv_nmos.sym.
        
        Reference Xschem layout:
        - Vertical body line at x=7.5 from y=-22.5 to y=22.5
        - Gate connection from left: (-20,0) to (2,0)
        - Drain at top-right: (20,-30) to (20,-17.5) + horizontal (7.5,-17.5) to (20,-17.5)
        - Source at bottom-right: (20,17.5) to (20,30) + horizontal (7.5,17.5) to (20,17.5)
        """
        symbol = {
            "type": "symbol",
            "name": name,
            "library": "ihp_primitives",
            "prefix": "M",
            "spice_model": model,
            "pins": [
                {"name": "D", "x": 20, "y": -30, "direction": "inout"},
                {"name": "G", "x": -20, "y": 0, "direction": "input"},
                {"name": "S", "x": 20, "y": 30, "direction": "inout"},
                {"name": "B", "x": 20, "y": 0, "direction": "inout"},
            ],
            "shapes": [
                # Vertical body line
                {"type": "line", "x1": 7.5, "y1": -22.5, "x2": 7.5, "y2": 22.5},
                # Gate connection
                {"type": "line", "x1": -20, "y1": 0, "x2": 2, "y2": 0},
                # Drain vertical connection
                {"type": "line", "x1": 20, "y1": -30, "x2": 20, "y2": -17.5},
                # Source vertical connection
                {"type": "line", "x1": 20, "y1": 17.5, "x2": 20, "y2": 30},
                # Inner body line
                {"type": "line", "x1": 2.5, "y1": -15, "x2": 2.5, "y2": 15},
                # Drain horizontal
                {"type": "line", "x1": 7.5, "y1": -17.5, "x2": 20, "y2": -17.5},
                # Source horizontal
                {"type": "line", "x1": 7.5, "y1": 17.5, "x2": 20, "y2": 17.5},
                # NMOS arrow (pointing into device at source)
                {"type": "polygon", "points": [[15, 20], [20, 17.5], [15, 15]]},
                # Bulk connection marker
                {"type": "polygon", "points": [[20, 2.5], [15, 0], [20, -2.5]]},
            ],
            "parameters": [
                {"name": "w", "default": "1.0u" if "_rf_" in name else ("0.3u" if "_hv_" in name else "0.15u"), "description": "Width"},
                {"name": "l", "default": "0.72u" if "_rf_" in name else ("0.4u" if "_hv_" in name else "0.13u"), "description": "Length"},
                {"name": "ng", "default": "1", "description": "Number of gate fingers"},
                {"name": "m", "default": "1", "description": "Multiplier"},
            ] + ([{"name": "rfmode", "default": "1", "description": "RF PCell mode"}] if "_rf_" in name else []),
            "layout": self._layout_binding(name, ["w", "l", "ng", "m"] + (["rfmode"] if "_rf_" in name else [])),
            "label": {"text": "@name", "x": 5, "y": -30}
        }
        return symbol
    
    def generate_pmos(self, name: str = "sg13_lv_pmos", model: str = "sg13_lv_pmos") -> Dict[str, Any]:
        """
        Generate LV PMOS symbol matching IHP official sg13_lv_pmos.sym.
        
        Reference Xschem layout:
        - Same as NMOS but D and S are SWAPPED
        - Source at top-right, Drain at bottom-right
        """
        symbol = {
            "type": "symbol",
            "name": name,
            "library": "ihp_primitives",
            "prefix": "M",
            "spice_model": model,
            "pins": [
                {"name": "D", "x": 20, "y": 30, "direction": "inout"},
                {"name": "G", "x": -20, "y": 0, "direction": "input"},
                {"name": "S", "x": 20, "y": -30, "direction": "inout"},
                {"name": "B", "x": 20, "y": 0, "direction": "inout"},
            ],
            "shapes": [
                # Vertical body line
                {"type": "line", "x1": 7.5, "y1": -22.5, "x2": 7.5, "y2": 22.5},
                # Gate connection
                {"type": "line", "x1": -20, "y1": 0, "x2": 2, "y2": 0},
                # Drain vertical connection (bottom-right)
                {"type": "line", "x1": 20, "y1": 30, "x2": 20, "y2": 17.5},
                # Source vertical connection (top-right)
                {"type": "line", "x1": 20, "y1": -30, "x2": 20, "y2": -17.5},
                # Inner body line
                {"type": "line", "x1": 2.5, "y1": -15, "x2": 2.5, "y2": 15},
                # Drain horizontal (bottom)
                {"type": "line", "x1": 7.5, "y1": 17.5, "x2": 20, "y2": 17.5},
                # Source horizontal (top)
                {"type": "line", "x1": 7.5, "y1": -17.5, "x2": 20, "y2": -17.5},
                # PMOS arrow (pointing out of device at source)
                {"type": "polygon", "points": [[12.5, -20], [7.5, -17.5], [12.5, -15]]},
                # Bulk connection marker
                {"type": "polygon", "points": [[15, 0], [20, 2.5], [15, -2.5]]},
            ],
            "parameters": [
                {"name": "w", "default": "1.0u" if "_rf_" in name else ("0.3u" if "_hv_" in name else "0.15u"), "description": "Width"},
                {"name": "l", "default": "0.72u" if "_rf_" in name else ("0.45u" if "_hv_" in name else "0.13u"), "description": "Length"},
                {"name": "ng", "default": "1", "description": "Number of gate fingers"},
                {"name": "m", "default": "1", "description": "Multiplier"},
            ] + ([{"name": "rfmode", "default": "1", "description": "RF PCell mode"}] if "_rf_" in name else []),
            "layout": self._layout_binding(name, ["w", "l", "ng", "m"] + (["rfmode"] if "_rf_" in name else [])),
            "label": {"text": "@name", "x": 5, "y": -30}
        }
        return symbol
    
    def generate_hv_nmos(self, name: str = "sg13_hv_nmos", model: str = "sg13_hv_nmos") -> Dict[str, Any]:
        """Generate HV NMOS symbol."""
        return self.generate_nmos(name, model)
    
    def generate_hv_pmos(self, name: str = "sg13_hv_pmos", model: str = "sg13_hv_pmos") -> Dict[str, Any]:
        """Generate HV PMOS symbol."""
        return self.generate_pmos(name, model)
    
    def generate_capacitor(self, name: str = "cap_cmim", model: str = "cap_cmim") -> Dict[str, Any]:
        """Generate MIM capacitor symbol."""
        is_rf = name == "cap_rfcmim"
        symbol = {
            "type": "symbol",
            "name": name,
            "library": "ihp_primitives",
            "prefix": "C",
            "spice_model": model,
            "pins": [
                {"name": "c0", "x": 0, "y": -30, "direction": "inout"},
                {"name": "c1", "x": 0, "y": 30, "direction": "inout"},
            ] + ([{"name": "bn", "x": -30, "y": 0, "direction": "inout"}] if is_rf else []),
            "shapes": [
                # Top plate
                {"type": "line", "x1": -15, "y1": -10, "x2": 15, "y2": -10},
                # Bottom plate
                {"type": "line", "x1": -12, "y1": 10, "x2": 12, "y2": 10},
                # Lead lines
                {"type": "line", "x1": 0, "y1": -30, "x2": 0, "y2": -10},
                {"type": "line", "x1": 0, "y1": 10, "x2": 0, "y2": 30},
            ],
            "parameters": [
                {"name": "w", "default": "10.0e-6" if is_rf else "7.0e-6", "description": "Width"},
                {"name": "l", "default": "10.0e-6" if is_rf else "7.0e-6", "description": "Length"},
            ] + ([{"name": "wfeed", "default": "5.0e-6", "description": "RF feed width"}]
                 if is_rf else [{"name": "m", "default": "1", "description": "Multiplier"}]),
            "layout": self._layout_binding(name, ["w", "l", "wfeed"] if is_rf else ["w", "l", "m"]),
            "label": {"text": "@name\\n@w / @l", "x": 20, "y": 0}
        }
        return symbol
    
    def generate_resistor(self, name: str = "rppd", model: str = "rppd") -> Dict[str, Any]:
        """Generate IHP PPd resistor symbol with zigzag."""
        symbol = {
            "type": "symbol",
            "name": name,
            "library": "ihp_primitives",
            "prefix": "R",
            "spice_model": model,
            "pins": [
                {"name": "P", "x": 0, "y": -30, "direction": "inout"},
                {"name": "M", "x": 0, "y": 30, "direction": "inout"},
            ],
            "shapes": [
                {"type": "line", "x1": 0, "y1": -30, "x2": 0, "y2": -20},
                {"type": "line", "x1": 0, "y1": -20, "x2": -7.5, "y2": -17.5},
                {"type": "line", "x1": -7.5, "y1": -17.5, "x2": 7.5, "y2": -12.5},
                {"type": "line", "x1": 7.5, "y1": -12.5, "x2": -7.5, "y2": -7.5},
                {"type": "line", "x1": -7.5, "y1": -7.5, "x2": 7.5, "y2": -2.5},
                {"type": "line", "x1": 7.5, "y1": -2.5, "x2": -7.5, "y2": 2.5},
                {"type": "line", "x1": -7.5, "y1": 2.5, "x2": 7.5, "y2": 7.5},
                {"type": "line", "x1": 7.5, "y1": 7.5, "x2": -7.5, "y2": 12.5},
                {"type": "line", "x1": -7.5, "y1": 12.5, "x2": 7.5, "y2": 17.5},
                {"type": "line", "x1": 7.5, "y1": 17.5, "x2": 0, "y2": 20},
                {"type": "line", "x1": 0, "y1": 20, "x2": 0, "y2": 30},
            ],
            "parameters": [
                {"name": "w", "default": "0.5e-6", "description": "Width"},
                {"name": "l", "default": "0.96e-6" if name == "rhigh" else "0.5e-6", "description": "Length"},
                {"name": "m", "default": "1", "description": "Multiplier"},
            ] + ([{"name": "b", "default": "0", "description": "Bends"}] if name in {"rppd", "rhigh"} else []),
            "layout": self._layout_binding(name, ["w", "l", "m"] + (["b"] if name in {"rppd", "rhigh"} else [])),
            "label": {"text": "@name", "x": 15, "y": 0}
        }
        return symbol
    
    def generate_diode(self, name: str = "diode", model: str = "diode") -> Dict[str, Any]:
        """Generate a basic diode symbol."""
        symbol = {
            "type": "symbol",
            "name": name,
            "library": "ihp_primitives",
            "prefix": "D",
            "spice_model": model,
            "pins": [
                {"name": "ANODE", "x": 0, "y": -30, "direction": "inout"},
                {"name": "CATHODE", "x": 0, "y": 30, "direction": "inout"},
            ],
            "shapes": [
                {"type": "line", "x1": 0, "y1": -30, "x2": 0, "y2": -5},
                {"type": "line", "x1": 0, "y1": 5, "x2": 0, "y2": 30},
                {"type": "polygon", "points": [[0, -5], [10, 5], [-10, 5]]},
                {"type": "line", "x1": -10, "y1": -5, "x2": -10, "y2": 5},
            ],
            "parameters": [
                {"name": "model", "default": "D", "description": "Model name"},
                {"name": "area", "default": "1", "description": "Area multiplier"},
            ],
            "label": {"text": "@name", "x": 15, "y": 0}
        }
        return symbol
    
    def generate_npn(self, name: str = "npn13G2", model: str = "npn13G2") -> Dict[str, Any]:
        """Generate IHP NPN HBT symbol."""
        symbol = {
            "type": "symbol",
            "name": name,
            "library": "ihp_primitives",
            "prefix": "Q",
            "spice_model": model,
            "pins": [
                {"name": "C", "x": 0, "y": -30, "direction": "input"},
                {"name": "B", "x": -20, "y": 0, "direction": "input"},
                {"name": "E", "x": 0, "y": 30, "direction": "output"},
                {"name": "S", "x": 20, "y": 0, "direction": "inout"},
            ],
            "shapes": [
                {"type": "line", "x1": 0, "y1": -20, "x2": 0, "y2": 20},
                {"type": "line", "x1": 0, "y1": -30, "x2": 0, "y2": -20},
                {"type": "line", "x1": 0, "y1": 20, "x2": 0, "y2": 30},
                {"type": "line", "x1": 0, "y1": 0, "x2": -20, "y2": 0},
                {"type": "polygon", "points": [[0, 5], [-5, 10], [0, 15]]},
                {"type": "circle", "cx": 0, "cy": 0, "r": 20},
            ],
            "parameters": [
                {"name": "Nx", "default": "1", "description": "Emitter stripes"},
            ] + ([{"name": "El", "default": "1.0", "description": "Emitter length"}] if name == "npn13G2l" else []),
            "layout": self._layout_binding(name, ["Nx"] + (["El"] if name == "npn13G2l" else [])),
            "label": {"text": "@name", "x": 5, "y": -25}
        }
        return symbol


def generate_all_ihp_primitives() -> Dict[str, Dict[str, Any]]:
    """Generate all IHP SG13G2 primitive symbols."""
    gen = IHPSymbolGenerator()
    return {
        "sg13_lv_nmos": gen.generate_nmos(),
        "sg13_lv_pmos": gen.generate_pmos(),
        "sg13_lv_rf_nmos": gen.generate_nmos("sg13_lv_rf_nmos", "sg13_lv_nmos"),
        "sg13_lv_rf_pmos": gen.generate_pmos("sg13_lv_rf_pmos", "sg13_lv_pmos"),
        "sg13_hv_nmos": gen.generate_hv_nmos(),
        "sg13_hv_pmos": gen.generate_hv_pmos(),
        "sg13_hv_rf_nmos": gen.generate_hv_nmos("sg13_hv_rf_nmos", "sg13_hv_nmos"),
        "sg13_hv_rf_pmos": gen.generate_hv_pmos("sg13_hv_rf_pmos", "sg13_hv_pmos"),
        "cap_cmim": gen.generate_capacitor(),
        "cap_rfcmim": gen.generate_capacitor("cap_rfcmim", "cap_rfcmim"),
        "rppd": gen.generate_resistor(),
        "rhigh": gen.generate_resistor("rhigh", "rhigh"),
        "rsil": gen.generate_resistor("rsil", "rsil"),
        "diode": gen.generate_diode(),
        "npn13G2": gen.generate_npn(),
        "npn13G2l": gen.generate_npn("npn13G2l", "npn13G2l"),
        "npn13G2v": gen.generate_npn("npn13G2v", "npn13G2v"),
    }


if __name__ == "__main__":
    import sys
    output_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "lumen/ihp_symbols")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    symbols = generate_all_ihp_primitives()
    for name, symbol in symbols.items():
        output_file = output_dir / f"{name}.symbol.json"
        with open(output_file, 'w') as f:
            json.dump(symbol, f, indent=2)
        print(f"Generated {name}")
    
    print(f"\nTotal: {len(symbols)} symbols generated in {output_dir}")
