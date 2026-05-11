"""
Lumen Circuit Studio — GF180MCU PDK Symbol Generator

Generates symbols for the GlobalFoundries GF180MCU process.
Based on the GF180MCU PDK documentation and common EDA conventions.
"""
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class GF180MCUSymbolGenerator:
    """Generate GF180MCU-compliant symbols."""

    def generate_nmos(self, name: str = "nmos", model: str = "n_18_3p3") -> Dict[str, Any]:
        """Generate GF180MCU NMOS symbol."""
        symbol = {
            "type": "symbol",
            "name": name,
            "library": "gf180mcu_primitives",
            "prefix": "M",
            "spice_model": model,
            "pins": [
                {"name": "D", "x": 20, "y": -30, "direction": "inout"},
                {"name": "G", "x": -20, "y": 0, "direction": "input"},
                {"name": "S", "x": 20, "y": 30, "direction": "inout"},
                {"name": "B", "x": 20, "y": 0, "direction": "inout"},
            ],
            "shapes": [
                {"type": "line", "x1": 7.5, "y1": -22.5, "x2": 7.5, "y2": 22.5},
                {"type": "line", "x1": -20, "y1": 0, "x2": 2.5, "y2": 0},
                {"type": "line", "x1": 20, "y1": -30, "x2": 20, "y2": -17.5},
                {"type": "line", "x1": 20, "y1": 17.5, "x2": 20, "y2": 30},
                {"type": "line", "x1": 2.5, "y1": -15, "x2": 2.5, "y2": 15},
                {"type": "line", "x1": 7.5, "y1": -17.5, "x2": 20, "y2": -17.5},
                {"type": "line", "x1": 7.5, "y1": 17.5, "x2": 15, "y2": 17.5},
                {"type": "polygon", "points": [[15, 15], [20, 17.5], [15, 20]]},
                {"type": "polygon", "points": [[20, -2.5], [15, 0], [20, 2.5]]},
            ],
            "parameters": [
                {"name": "W", "default": "1u", "description": "Width"},
                {"name": "L", "default": "180n", "description": "Length"},
                {"name": "nf", "default": "1", "description": "Number of fingers"},
                {"name": "m", "default": "1", "description": "Multiplier"},
            ],
            "label": {"text": "@name", "x": 5, "y": -30}
        }
        return symbol
    
    def generate_pmos(self, name: str = "pmos", model: str = "p_18_3p3") -> Dict[str, Any]:
        """Generate GF180MCU PMOS symbol."""
        symbol = {
            "type": "symbol",
            "name": name,
            "library": "gf180mcu_primitives",
            "prefix": "M",
            "spice_model": model,
            "pins": [
                {"name": "D", "x": 20, "y": 30, "direction": "inout"},
                {"name": "G", "x": -20, "y": 0, "direction": "input"},
                {"name": "S", "x": 20, "y": -30, "direction": "inout"},
                {"name": "B", "x": 20, "y": 0, "direction": "inout"},
            ],
            "shapes": [
                {"type": "line", "x1": 7.5, "y1": -22.5, "x2": 7.5, "y2": 22.5},
                {"type": "line", "x1": 20, "y1": 30, "x2": 20, "y2": 17.5},
                {"type": "line", "x1": 20, "y1": -30, "x2": 20, "y2": -17.5},
                {"type": "line", "x1": 2.5, "y1": -15, "x2": 2.5, "y2": 15},
                {"type": "line", "x1": 7.5, "y1": -17.5, "x2": 12.5, "y2": -17.5},
                {"type": "line", "x1": 7.5, "y1": 17.5, "x2": 20, "y2": 17.5},
                {"type": "line", "x1": -20, "y1": 0, "x2": -7.5, "y2": 0},
                {"type": "circle", "cx": -2.5, "cy": 0, "r": 5},
                {"type": "polygon", "points": [[12.5, -20], [7.5, -17.5], [12.5, -15]]},
                {"type": "polygon", "points": [[15, -2.5], [20, 0], [15, 2.5]]},
            ],
            "parameters": [
                {"name": "W", "default": "1u", "description": "Width"},
                {"name": "L", "default": "180n", "description": "Length"},
                {"name": "nf", "default": "1", "description": "Number of fingers"},
                {"name": "m", "default": "1", "description": "Multiplier"},
            ],
            "label": {"text": "@name", "x": 5, "y": -30}
        }
        return symbol
    
    def generate_resistor(self, name: str = "res", model: str = "res_n_std") -> Dict[str, Any]:
        """Generate GF180MCU resistor symbol with zigzag."""
        symbol = {
            "type": "symbol",
            "name": name,
            "library": "gf180mcu_primitives",
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
                {"name": "R", "default": "1k", "description": "Resistance"},
                {"name": "W", "default": "1u", "description": "Width"},
                {"name": "L", "default": "1u", "description": "Length"},
            ],
            "label": {"text": "@name\\nR=@R", "x": 15, "y": 0}
        }
        return symbol
    
    def generate_capacitor(self, name: str = "cap", model: str = "cap_mim") -> Dict[str, Any]:
        """Generate GF180MCU capacitor symbol."""
        symbol = {
            "type": "symbol",
            "name": name,
            "library": "gf180mcu_primitives",
            "prefix": "C",
            "spice_model": model,
            "pins": [
                {"name": "PLUS", "x": 0, "y": -30, "direction": "inout"},
                {"name": "MINUS", "x": 0, "y": 30, "direction": "inout"},
            ],
            "shapes": [
                {"type": "line", "x1": -15, "y1": -10, "x2": 15, "y2": -10},
                {"type": "line", "x1": -12, "y1": 10, "x2": 12, "y2": 10},
                {"type": "line", "x1": 0, "y1": -30, "x2": 0, "y2": -10},
                {"type": "line", "x1": 0, "y1": 10, "x2": 0, "y2": 30},
            ],
            "parameters": [
                {"name": "C", "default": "1p", "description": "Capacitance"},
            ],
            "label": {"text": "@name\\nC=@C", "x": 20, "y": 0}
        }
        return symbol
    
    def generate_diode(self, name: str = "diode", model: str = "diode") -> Dict[str, Any]:
        """Generate GF180MCU diode symbol."""
        symbol = {
            "type": "symbol",
            "name": name,
            "library": "gf180mcu_primitives",
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
                {"name": "area", "default": "1", "description": "Area multiplier"},
            ],
            "label": {"text": "@name", "x": 15, "y": 0}
        }
        return symbol
    
    def generate_vsource(self, name: str = "vsource") -> Dict[str, Any]:
        """Generate a voltage source symbol."""
        symbol = {
            "type": "symbol",
            "name": name,
            "library": "gf180mcu_primitives",
            "prefix": "V",
            "spice_model": "V",
            "pins": [
                {"name": "PLUS", "x": 0, "y": -30, "direction": "inout"},
                {"name": "MINUS", "x": 0, "y": 30, "direction": "inout"},
            ],
            "shapes": [
                {"type": "circle", "cx": 0, "cy": 0, "r": 20},
                {"type": "line", "x1": -5, "y1": 0, "x2": 5, "y2": 0},
                {"type": "line", "x1": 0, "y1": -5, "x2": 0, "y2": 5},
                {"type": "line", "x1": -5, "y1": 10, "x2": 5, "y2": 10},
                {"type": "line", "x1": 0, "y1": -30, "x2": 0, "y2": -20},
                {"type": "line", "x1": 0, "y1": 20, "x2": 0, "y2": 30},
            ],
            "parameters": [
                {"name": "DC", "default": "1.8", "description": "DC voltage"},
            ],
            "label": {"text": "@name\\nDC=@DC", "x": 25, "y": 0}
        }
        return symbol


def generate_all_gf180mcu_primitives() -> Dict[str, Dict[str, Any]]:
    """Generate all GF180MCU primitive symbols."""
    gen = GF180MCUSymbolGenerator()
    return {
        "nmos": gen.generate_nmos(),
        "nmos_3p3": gen.generate_nmos("nmos_3p3", "n_18_3p3"),
        "nmos_6p0": gen.generate_nmos("nmos_6p0", "n_18_6p0"),
        "pmos": gen.generate_pmos(),
        "pmos_3p3": gen.generate_pmos("pmos_3p3", "p_18_3p3"),
        "pmos_6p0": gen.generate_pmos("pmos_6p0", "p_18_6p0"),
        "res": gen.generate_resistor(),
        "cap": gen.generate_capacitor(),
        "diode": gen.generate_diode(),
        "vsource": gen.generate_vsource(),
    }


if __name__ == "__main__":
    import sys
    output_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "lumen/gf180mcu_symbols")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    symbols = generate_all_gf180mcu_primitives()
    for name, symbol in symbols.items():
        output_file = output_dir / f"{name}.symbol.json"
        with open(output_file, 'w') as f:
            json.dump(symbol, f, indent=2)
        print(f"Generated {name}")
    
    print(f"\nTotal: {len(symbols)} symbols generated in {output_dir}")