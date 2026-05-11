"""
Lumen Circuit Studio — SkyWater PDK Compliant Symbols

Generates symbols that match the official SkyWater PDK device details:
https://skywater-pdk.readthedocs.io/en/main/rules/device-details.html

Based on official Xschem .sym files from the SkyWater PDK distribution:
- nfet_01v8.sym, pfet_01v8.sym (MOSFETs)
- res_generic_po.sym (Resistors)
- cap_mim_m3_1.sym (Capacitors)
- diode.sym (Diodes)

Key requirements:
- MOSFETs: Standard 4-pin with vertical body line
- Pins: D, G, S, B (D at top-right, S at bottom-right in NMOS; swapped in PMOS)
- Proper pin positioning as per official Xschem symbols
- Correct triangle arrows (NMOS: arrow into device; PMOS: arrow out of device)
- PMOS has circle at gate connection
- Resistors: Zigzag pattern for SkyWater PO resistor
"""
import json
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, List, Any


@dataclass
class SymbolGenerator:
    """Generate SkyWater-compliant symbols matching official PDK references."""
    
    def generate_nmos(self, name: str = "nmos", model: str = "nfet_01v8") -> Dict[str, Any]:
        """
        Generate an NMOS symbol matching SkyWater official nfet_01v8.sym.
        
        Reference Xschem layout:
        - Vertical body line at x=7.5 from y=-22.5 to y=22.5
        - Gate connection from left at x=-20, y=0 to x=2.5, y=0
        - Drain at top-right: vertical from x=20, y=-30 to y=-17.5, horizontal from x=7.5 to x=20
        - Source at bottom-right: vertical from x=20, y=17.5 to y=30, horizontal from x=7.5 to x=20
        - Inner body line: x=2.5, y=-15 to y=15
        - NMOS arrow (triangle) pointing into device: (15,15)->(20,17.5)->(15,20)
        - Bulk marker: small triangle at (15,0)->(20,2.5)->(20,-2.5)
        - Pin B at x=20, y=0 (micro-pin)
        """
        symbol = {
            "type": "symbol",
            "name": name,
            "library": "skywater_primitives",
            "prefix": "M",
            "spice_model": model,
            "pins": [
                {"name": "D", "x": 20, "y": -30, "direction": "inout"},
                {"name": "G", "x": -20, "y": 0, "direction": "input"},
                {"name": "S", "x": 20, "y": 30, "direction": "inout"},
                {"name": "B", "x": 20, "y": 0, "direction": "inout"},
            ],
            "shapes": [
                # Vertical body line (channel)
                {"type": "line", "x1": 7.5, "y1": -22.5, "x2": 7.5, "y2": 22.5},
                # Gate connection line from left
                {"type": "line", "x1": -20, "y1": 0, "x2": 2.5, "y2": 0},
                # Drain connection (top-right)
                {"type": "line", "x1": 20, "y1": -30, "x2": 20, "y2": -17.5},
                # Source connection (bottom-right)
                {"type": "line", "x1": 20, "y1": 17.5, "x2": 20, "y2": 30},
                # Inner body line
                {"type": "line", "x1": 2.5, "y1": -15, "x2": 2.5, "y2": 15},
                # Drain horizontal connection from body
                {"type": "line", "x1": 7.5, "y1": -17.5, "x2": 20, "y2": -17.5},
                # Source horizontal connection from body
                {"type": "line", "x1": 7.5, "y1": 17.5, "x2": 15, "y2": 17.5},
                # NMOS arrow (triangle pointing into device - from source)
                {"type": "polygon", "points": [[15, 15], [20, 17.5], [15, 20]]},
                # Bulk connection marker (small triangle)
                {"type": "polygon", "points": [[20, -2.5], [15, 0], [20, 2.5]]},
            ],
            "parameters": [
                {"name": "W", "default": "1", "description": "Width (um)"},
                {"name": "L", "default": "0.15", "description": "Length (um)"},
                {"name": "nf", "default": "1", "description": "Number of fingers"},
                {"name": "mult", "default": "1", "description": "Multiplier"},
                {"name": "ad", "default": "", "description": "Drain area"},
                {"name": "as", "default": "", "description": "Source area"},
                {"name": "pd", "default": "", "description": "Drain perimeter"},
                {"name": "ps", "default": "", "description": "Source perimeter"},
                {"name": "nrd", "default": "", "description": "Drain resistance squares"},
                {"name": "nrs", "default": "", "description": "Source resistance squares"},
            ],
            "label": {"text": "@name", "x": 5, "y": -30}
        }
        return symbol
    
    def generate_pmos(self, name: str = "pmos", model: str = "pfet_01v8") -> Dict[str, Any]:
        """
        Generate a PMOS symbol matching SkyWater official pfet_01v8.sym.
        
        Reference Xschem layout:
        - Vertical body line at x=7.5 from y=-22.5 to y=22.5
        - Source at top-right (swapped from NMOS)
        - Drain at bottom-right (swapped from NMOS)
        - PMOS arrow (triangle) pointing OUT of device: (12.5,-20)->(7.5,-17.5)->(12.5,-15)
        - Circle at gate connection: centered at (-2.5,0), radius 5
        - Bulk marker: small triangle at (15,0)->(20,2.5)->(15,-2.5)
        """
        symbol = {
            "type": "symbol",
            "name": name,
            "library": "skywater_primitives",
            "prefix": "M",
            "spice_model": model,
            "pins": [
                {"name": "D", "x": 20, "y": 30, "direction": "inout"},
                {"name": "G", "x": -20, "y": 0, "direction": "input"},
                {"name": "S", "x": 20, "y": -30, "direction": "inout"},
                {"name": "B", "x": 20, "y": 0, "direction": "inout"},
            ],
            "shapes": [
                # Vertical body line (channel)
                {"type": "line", "x1": 7.5, "y1": -22.5, "x2": 7.5, "y2": 22.5},
                # Drain connection (bottom-right)
                {"type": "line", "x1": 20, "y1": 30, "x2": 20, "y2": 17.5},
                # Source connection (top-right)
                {"type": "line", "x1": 20, "y1": -30, "x2": 20, "y2": -17.5},
                # Inner body line
                {"type": "line", "x1": 2.5, "y1": -15, "x2": 2.5, "y2": 15},
                # Source horizontal connection from body
                {"type": "line", "x1": 7.5, "y1": -17.5, "x2": 12.5, "y2": -17.5},
                # Drain horizontal connection from body
                {"type": "line", "x1": 7.5, "y1": 17.5, "x2": 20, "y2": 17.5},
                # Gate connection from left
                {"type": "line", "x1": -20, "y1": 0, "x2": -7.5, "y2": 0},
                # PMOS circle at gate (circle centered at (-2.5,0) radius 5)
                {"type": "circle", "cx": -2.5, "cy": 0, "r": 5},
                # PMOS arrow (triangle pointing OUT of device)
                {"type": "polygon", "points": [[12.5, -20], [7.5, -17.5], [12.5, -15]]},
                # Bulk connection marker (small triangle)
                {"type": "polygon", "points": [[15, -2.5], [20, 0], [15, 2.5]]},
            ],
            "parameters": [
                {"name": "W", "default": "1", "description": "Width (um)"},
                {"name": "L", "default": "0.15", "description": "Length (um)"},
                {"name": "nf", "default": "1", "description": "Number of fingers"},
                {"name": "mult", "default": "1", "description": "Multiplier"},
                {"name": "ad", "default": "", "description": "Drain area"},
                {"name": "as", "default": "", "description": "Source area"},
                {"name": "pd", "default": "", "description": "Drain perimeter"},
                {"name": "ps", "default": "", "description": "Source perimeter"},
                {"name": "nrd", "default": "", "description": "Drain resistance squares"},
                {"name": "nrs", "default": "", "description": "Source resistance squares"},
            ],
            "label": {"text": "@name", "x": 5, "y": -30}
        }
        return symbol
    
    def generate_nmos_3pin(self, name: str = "nmos_3pin", model: str = "nfet_01v8") -> Dict[str, Any]:
        """
        Generate a 3-pin NMOS symbol (no bulk connection).
        Used by sky130_fd_pr 3-pin variants.
        """
        symbol = {
            "type": "symbol",
            "name": name,
            "library": "skywater_primitives",
            "prefix": "M",
            "spice_model": model,
            "pins": [
                {"name": "D", "x": 20, "y": -30, "direction": "inout"},
                {"name": "G", "x": -20, "y": 0, "direction": "input"},
                {"name": "S", "x": 20, "y": 30, "direction": "inout"},
            ],
            "shapes": [
                # Vertical body line (channel)
                {"type": "line", "x1": 7.5, "y1": -22.5, "x2": 7.5, "y2": 22.5},
                # Gate connection line from left
                {"type": "line", "x1": -20, "y1": 0, "x2": 2.5, "y2": 0},
                # Drain connection (top-right)
                {"type": "line", "x1": 20, "y1": -30, "x2": 20, "y2": -17.5},
                # Source connection (bottom-right)
                {"type": "line", "x1": 20, "y1": 17.5, "x2": 20, "y2": 30},
                # Drain horizontal connection from body
                {"type": "line", "x1": 7.5, "y1": -17.5, "x2": 20, "y2": -17.5},
                # Source horizontal connection from body
                {"type": "line", "x1": 7.5, "y1": 17.5, "x2": 15, "y2": 17.5},
                # NMOS arrow
                {"type": "polygon", "points": [[15, 15], [20, 17.5], [15, 20]]},
            ],
            "parameters": [
                {"name": "W", "default": "1", "description": "Width (um)"},
                {"name": "L", "default": "0.15", "description": "Length (um)"},
                {"name": "nf", "default": "1", "description": "Number of fingers"},
                {"name": "mult", "default": "1", "description": "Multiplier"},
            ],
            "label": {"text": "@name", "x": 5, "y": -30}
        }
        return symbol
    
    def generate_resistor(self, name: str = "res", model: str = "res_generic_po") -> Dict[str, Any]:
        """
        Generate a SkyWater PO poly resistor symbol with zigzag pattern.
        
        Reference: res_generic_po.sym from SkyWater PDK
        - Meandering zigzag pattern for the resistor body
        - Pins: P (positive) at bottom, M (minus) at top
        """
        symbol = {
            "type": "symbol",
            "name": name,
            "library": "skywater_primitives",
            "prefix": "R",
            "spice_model": model,
            "pins": [
                {"name": "P", "x": 0, "y": -30, "direction": "inout"},
                {"name": "M", "x": 0, "y": 30, "direction": "inout"},
            ],
            "shapes": [
                # Zigzag resistor body (meandering lines from bottom to top)
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
                {"name": "W", "default": "1", "description": "Width (um)"},
                {"name": "L", "default": "1", "description": "Length (um)"},
                {"name": "mult", "default": "1", "description": "Multiplier"},
            ],
            "label": {"text": "@name\\n@mult * @W / @L", "x": 15, "y": 0}
        }
        return symbol
    
    def generate_capacitor(self, name: str = "cap", model: str = "cap_mim") -> Dict[str, Any]:
        """
        Generate a MIM capacitor symbol matching SkyWater style.
        
        Reference: cap_mim_m3_1.sym
        - Two parallel plates with slight offset
        """
        symbol = {
            "type": "symbol",
            "name": name,
            "library": "skywater_primitives",
            "prefix": "C",
            "spice_model": model,
            "pins": [
                {"name": "PLUS", "x": 0, "y": -30, "direction": "inout"},
                {"name": "MINUS", "x": 0, "y": 30, "direction": "inout"},
            ],
            "shapes": [
                # Top plate
                {"type": "line", "x1": -15, "y1": -10, "x2": 15, "y2": -10},
                # Bottom plate (offset for MIM-like look)
                {"type": "line", "x1": -12, "y1": 10, "x2": 12, "y2": 10},
                # Lead lines
                {"type": "line", "x1": 0, "y1": -30, "x2": 0, "y2": -10},
                {"type": "line", "x1": 0, "y1": 10, "x2": 0, "y2": 30},
            ],
            "parameters": [
                {"name": "C", "default": "1p", "description": "Capacitance"},
                {"name": "W", "default": "5u", "description": "Width"},
                {"name": "L", "default": "5u", "description": "Length"},
                {"name": "mult", "default": "1", "description": "Multiplier"},
            ],
            "label": {"text": "@name\\nC=@C", "x": 20, "y": 0}
        }
        return symbol
    
    def generate_diode(self, name: str = "diode", model: str = "diode") -> Dict[str, Any]:
        """
        Generate a diode symbol matching SkyWater official diode.sym.
        
        Reference Xschem layout:
        - Triangle pointing LEFT (anode/cathode bar on right)
        - d1 (anode) at bottom, d0 (cathode) at top
        - Triangle: (0,-5)->(-10,5)->(10,5)
        - Cathode bar at x=10
        """
        symbol = {
            "type": "symbol",
            "name": name,
            "library": "skywater_primitives",
            "prefix": "D",
            "spice_model": model,
            "pins": [
                {"name": "d1", "x": 0, "y": -30, "direction": "inout"},
                {"name": "d0", "x": 0, "y": 30, "direction": "inout"},
            ],
            "shapes": [
                # Anode lead line
                {"type": "line", "x1": 0, "y1": -30, "x2": 0, "y2": -5},
                # Cathode lead line
                {"type": "line", "x1": 0, "y1": 5, "x2": 0, "y2": 30},
                # Triangle (pointing right - anode to cathode)
                {"type": "polygon", "points": [[0, -5], [10, 5], [-10, 5]]},
                # Cathode bar line
                {"type": "line", "x1": -10, "y1": -5, "x2": -10, "y2": 5},
            ],
            "parameters": [
                {"name": "model", "default": "D", "description": "Model name"},
                {"name": "area", "default": "1e12", "description": "Area multiplier"},
                {"name": "perim", "default": "4e6", "description": "Perimeter"},
            ],
            "label": {"text": "@name", "x": 15, "y": 0}
        }
        return symbol
    
    def generate_vsource(self, name: str = "vsource") -> Dict[str, Any]:
        """Generate a voltage source symbol (circle with +/- signs)."""
        symbol = {
            "type": "symbol",
            "name": name,
            "library": "skywater_primitives",
            "prefix": "V",
            "spice_model": "V",
            "pins": [
                {"name": "PLUS", "x": 0, "y": -30, "direction": "inout"},
                {"name": "MINUS", "x": 0, "y": 30, "direction": "inout"},
            ],
            "shapes": [
                # Circle
                {"type": "circle", "cx": 0, "cy": 0, "r": 20},
                # Plus sign (+)
                {"type": "line", "x1": -5, "y1": 0, "x2": 5, "y2": 0},
                {"type": "line", "x1": 0, "y1": -5, "x2": 0, "y2": 5},
                # Minus sign positioned at bottom of circle (y = +10)
                {"type": "line", "x1": -5, "y1": 10, "x2": 5, "y2": 10},
                # Lead lines
                {"type": "line", "x1": 0, "y1": -30, "x2": 0, "y2": -20},
                {"type": "line", "x1": 0, "y1": 20, "x2": 0, "y2": 30},
            ],
            "parameters": [
                {"name": "DC", "default": "1.8", "description": "DC voltage"},
                {"name": "AC", "default": "", "description": "AC magnitude"},
            ],
            "label": {"text": "@name\\nDC=@DC", "x": 25, "y": 0}
        }
        return symbol
    
    def generate_isource(self, name: str = "isource") -> Dict[str, Any]:
        """Generate a current source symbol (circle with arrow)."""
        symbol = {
            "type": "symbol",
            "name": name,
            "library": "skywater_primitives",
            "prefix": "I",
            "spice_model": "I",
            "pins": [
                {"name": "PLUS", "x": 0, "y": -30, "direction": "inout"},
                {"name": "MINUS", "x": 0, "y": 30, "direction": "inout"},
            ],
            "shapes": [
                # Circle
                {"type": "circle", "cx": 0, "cy": 0, "r": 20},
                # Arrow (pointing down - conventional direction)
                {"type": "line", "x1": 0, "y1": -10, "x2": 0, "y2": 10},
                {"type": "polygon", "points": [[-5, 5], [0, 15], [5, 5]]},
                # Lead lines
                {"type": "line", "x1": 0, "y1": -30, "x2": 0, "y2": -20},
                {"type": "line", "x1": 0, "y1": 20, "x2": 0, "y2": 30},
            ],
            "parameters": [
                {"name": "DC", "default": "1m", "description": "DC current"},
            ],
            "label": {"text": "@name\\nDC=@DC", "x": 25, "y": 0}
        }
        return symbol
    
    def generate_gnd(self, name: str = "gnd") -> Dict[str, Any]:
        """Generate a ground symbol (three decreasing horizontal lines)."""
        symbol = {
            "type": "symbol",
            "name": name,
            "library": "skywater_primitives",
            "prefix": "",
            "spice_model": "0",
            "pins": [
                {"name": "GND", "x": 0, "y": -10, "direction": "inout", "net_name": "0"}
            ],
            "shapes": [
                # Vertical connection line
                {"type": "line", "x1": 0, "y1": -10, "x2": 0, "y2": 0},
                # Three horizontal lines (decreasing length for ground symbol)
                {"type": "line", "x1": -12, "y1": 0, "x2": 12, "y2": 0},
                {"type": "line", "x1": -8, "y1": 5, "x2": 8, "y2": 5},
                {"type": "line", "x1": -4, "y1": 10, "x2": 4, "y2": 10},
            ],
            "parameters": [],
            "label": {"text": "GND", "x": 0, "y": -15}
        }
        return symbol
    
    def generate_vdd(self, name: str = "vdd") -> Dict[str, Any]:
        """Generate a VDD (power) symbol."""
        symbol = {
            "type": "symbol",
            "name": name,
            "library": "skywater_primitives",
            "prefix": "",
            "spice_model": "VDD",
            "pins": [
                {"name": "VDD", "x": 0, "y": 10, "direction": "inout", "net_name": "VDD"}
            ],
            "shapes": [
                # Top horizontal line
                {"type": "line", "x1": -12, "y1": 0, "x2": 12, "y2": 0},
                # Vertical connection
                {"type": "line", "x1": 0, "y1": 10, "x2": 0, "y2": 0},
            ],
            "parameters": [],
            "label": {"text": "VDD", "x": 0, "y": 15}
        }
        return symbol
    
    def generate_npn(self, name: str = "npn", model: str = "npn_05v5") -> Dict[str, Any]:
        """Generate an NPN BJT symbol."""
        symbol = {
            "type": "symbol",
            "name": name,
            "library": "skywater_primitives",
            "prefix": "Q",
            "spice_model": model,
            "pins": [
                {"name": "C", "x": 0, "y": -30, "direction": "input"},
                {"name": "B", "x": -20, "y": 0, "direction": "input"},
                {"name": "E", "x": 0, "y": 30, "direction": "output"},
            ],
            "shapes": [
                # Vertical line (collector/emitter axis)
                {"type": "line", "x1": 0, "y1": -20, "x2": 0, "y2": 20},
                # Collector lead
                {"type": "line", "x1": 0, "y1": -30, "x2": 0, "y2": -20},
                # Emitter lead
                {"type": "line", "x1": 0, "y1": 20, "x2": 0, "y2": 30},
                # Base lead
                {"type": "line", "x1": 0, "y1": 0, "x2": -20, "y2": 0},
                # Collector arrow (NPN: arrow points out from base to emitter)
                {"type": "polygon", "points": [[0, 5], [-5, 10], [0, 15]]},
                # Circle around device
                {"type": "circle", "cx": 0, "cy": 0, "r": 20},
            ],
            "parameters": [
                {"name": "mult", "default": "1", "description": "Multiplier"},
                {"name": "area", "default": "1", "description": "Area multiplier"},
            ],
            "label": {"text": "@name", "x": 5, "y": -25}
        }
        return symbol


def generate_all_skywater_primitives() -> Dict[str, Dict[str, Any]]:
    """Generate all SkyWater-compliant primitive symbols."""
    gen = SymbolGenerator()
    return {
        "nmos": gen.generate_nmos(),
        "pmos": gen.generate_pmos(),
        "nmos_3pin": gen.generate_nmos_3pin(),
        "res": gen.generate_resistor(),
        "cap": gen.generate_capacitor(),
        "diode": gen.generate_diode(),
        "vsource": gen.generate_vsource(),
        "isource": gen.generate_isource(),
        "gnd": gen.generate_gnd(),
        "vdd": gen.generate_vdd(),
        "npn": gen.generate_npn(),
    }


if __name__ == "__main__":
    # Generate and save all symbols
    import sys
    output_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "lumen/skywater_symbols")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    symbols = generate_all_skywater_primitives()
    for name, symbol in symbols.items():
        output_file = output_dir / f"{name}.symbol.json"
        with open(output_file, 'w') as f:
            json.dump(symbol, f, indent=2)
        print(f"Generated {name}")
    
    print(f"\nTotal: {len(symbols)} symbols generated in {output_dir}")