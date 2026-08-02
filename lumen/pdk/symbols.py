"""
LumenStudio - Symbol Generation

Generates schematic symbols for PDK devices.
Supports industry-style symbols and custom templates.
"""
from dataclasses import dataclass
from typing import List, Dict, Optional
from lumen.pdk.registry import PDKDevice, DeviceCategory, PDKPin


@dataclass
class SymbolShape:
    """A shape in a symbol."""
    type: str  # line, polyline, circle, rect, arc, polygon
    x1: float = 0
    y1: float = 0
    x2: float = 0
    y2: float = 0
    cx: float = 0
    cy: float = 0
    r: float = 0
    rx: float = 0
    ry: float = 0
    w: float = 0
    h: float = 0
    points: List[List[float]] = None
    start: float = 0
    span: float = 0


@dataclass
class SymbolPin:
    """A pin in a symbol."""
    name: str
    x: float
    y: float
    direction: str = "input"


@dataclass
class SymbolData:
    """Complete symbol definition."""
    type: str = "symbol"
    name: str = ""
    library: str = ""
    prefix: str = "X"
    model: str = ""
    description: str = ""
    shapes: List[Dict] = None
    pins: List[Dict] = None
    parameters: List[Dict] = None
    label: Dict = None
    
    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "name": self.name,
            "library": self.library,
            "prefix": self.prefix,
            "model": self.model,
            "description": self.description,
            "shapes": self.shapes or [],
            "pins": self.pins or [],
            "parameters": self.parameters or [],
            "label": self.label or {"text": "", "x": 15, "y": -25},
        }


class SymbolGenerator:
    """
    Generates schematic symbols for PDK devices.
    
    Creates industry-style symbols for:
    - MOSFETs (NMOS, PMOS)
    - BJTs (NPN, PNP)
    - Resistors
    - Capacitors
    - Diodes
    - Inductors
    """
    
    # Pin position templates for different device types
    PIN_TEMPLATES = {
        DeviceCategory.MOSFET: [
            {"name": "D", "x": 25, "y": -30},
            {"name": "G", "x": -25, "y": 0},
            {"name": "S", "x": 25, "y": 30},
            {"name": "B", "x": 40, "y": 0},
        ],
        DeviceCategory.BJT: [
            {"name": "C", "x": 20, "y": -30},
            {"name": "B", "x": -30, "y": 0},
            {"name": "E", "x": 20, "y": 30},
        ],
        DeviceCategory.RESISTOR: [
            {"name": "PLUS", "x": 0, "y": -35},
            {"name": "MINUS", "x": 0, "y": 35},
        ],
        DeviceCategory.CAPACITOR: [
            {"name": "PLUS", "x": 0, "y": -35},
            {"name": "MINUS", "x": 0, "y": 35},
        ],
        DeviceCategory.DIODE: [
            {"name": "PLUS", "x": 0, "y": -30},
            {"name": "MINUS", "x": 0, "y": 30},
        ],
        DeviceCategory.INDUCTOR: [
            {"name": "PLUS", "x": 0, "y": -35},
            {"name": "MINUS", "x": 0, "y": 35},
        ],
        DeviceCategory.SOURCE: [
            {"name": "PLUS", "x": 0, "y": -35},
            {"name": "MINUS", "x": 0, "y": 35},
        ],
    }
    
    def __init__(self, pdk_name: str = ""):
        self.pdk_name = pdk_name
    
    def generate(self, device: PDKDevice) -> SymbolData:
        """Generate a symbol for a PDK device."""
        category = device.category
        
        if category == DeviceCategory.MOSFET:
            return self._generate_mosfet(device)
        elif category == DeviceCategory.BJT:
            return self._generate_bjt(device)
        elif category == DeviceCategory.RESISTOR:
            return self._generate_resistor(device)
        elif category == DeviceCategory.CAPACITOR:
            return self._generate_capacitor(device)
        elif category == DeviceCategory.DIODE:
            return self._generate_diode(device)
        elif category == DeviceCategory.INDUCTOR:
            return self._generate_inductor(device)
        else:
            return self._generate_generic(device)
    
    def _generate_mosfet(self, device: PDKDevice) -> SymbolData:
        """Generate MOSFET symbol (industry-style)."""
        is_pmos = "p" in device.name.lower() or "pfet" in device.name.lower()
        
        shapes = []
        
        # Channel (vertical bar)
        shapes.append({"type": "line", "x1": 0, "y1": -18, "x2": 0, "y2": 18})
        
        # Gate bar
        shapes.append({"type": "line", "x1": -12, "y1": -18, "x2": -12, "y2": 18})
        
        # Drain lead
        shapes.append({"type": "line", "x1": 0, "y1": -18, "x2": 0, "y2": -35})
        
        # Source lead
        shapes.append({"type": "line", "x1": 0, "y1": 18, "x2": 0, "y2": 35})
        
        # Bulk lead
        shapes.append({"type": "line", "x1": 0, "y1": 0, "x2": 35, "y2": 0})
        
        if is_pmos:
            # PMOS: inversion circle on gate
            shapes.append({"type": "circle", "cx": -15, "cy": 0, "r": 4})
            # Gate connection
            shapes.append({"type": "line", "x1": -35, "y1": 0, "x2": -19, "y2": 0})
            # Arrow pointing up (into channel)
            shapes.append({"type": "polygon", "points": [[-5, 20], [5, 20], [0, 12]]})
        else:
            # NMOS: direct gate connection
            shapes.append({"type": "line", "x1": -35, "y1": 0, "x2": -12, "y2": 0})
            # Arrow pointing down (out of channel)
            shapes.append({"type": "polygon", "points": [[-5, 14], [5, 14], [0, 22]]})
        
        # Get pin positions
        pins = self.PIN_TEMPLATES.get(DeviceCategory.MOSFET, [])
        
        # Create parameters list
        params = [{"name": p.name, "default": p.default, "description": p.description}
                  for p in device.parameters]
        
        # Add model parameter if not present
        if not any(p["name"] == "model" for p in params):
            params.append({"name": "model", "default": device.model, "description": "Model name"})
        
        return SymbolData(
            type="symbol",
            name=device.name,
            library=f"pdk:{self.pdk_name}" if self.pdk_name else "pdk:",
            prefix=device.prefix,
            model=device.model,
            description=device.description,
            shapes=shapes,
            pins=pins,
            parameters=params,
            label={"text": f"@name\n@model", "x": 20, "y": -25},
        )
    
    def _generate_bjt(self, device: PDKDevice) -> SymbolData:
        """Generate BJT symbol (industry-style)."""
        is_pnp = "pnp" in device.name.lower()
        
        shapes = []
        
        # Base bar
        shapes.append({"type": "line", "x1": -12, "y1": -18, "x2": -12, "y2": 18})
        
        # Base lead
        shapes.append({"type": "line", "x1": -35, "y1": 0, "x2": -12, "y2": 0})
        
        # Collector diagonal
        shapes.append({"type": "line", "x1": -12, "y1": -10, "x2": 18, "y2": -28})
        shapes.append({"type": "line", "x1": 18, "y1": -28, "x2": 18, "y2": -35})
        
        # Emitter diagonal
        shapes.append({"type": "line", "x1": -12, "y1": 10, "x2": 18, "y2": 28})
        shapes.append({"type": "line", "x1": 18, "y1": 28, "x2": 18, "y2": 35})
        
        # Arrow
        if not is_pnp:
            shapes.append({"type": "polygon", "points": [[5, 18], [15, 28], [16, 16]]})
        else:
            shapes.append({"type": "polygon", "points": [[-8, 12], [4, 6], [2, 18]]})
        
        pins = self.PIN_TEMPLATES.get(DeviceCategory.BJT, [])
        
        params = [{"name": p.name, "default": p.default, "description": p.description}
                  for p in device.parameters]
        
        return SymbolData(
            type="symbol",
            name=device.name,
            library=f"pdk:{self.pdk_name}",
            prefix=device.prefix,
            model=device.model,
            description=device.description,
            shapes=shapes,
            pins=pins,
            parameters=params,
            label={"text": f"@name\n@model", "x": 25, "y": -20},
        )
    
    def _generate_resistor(self, device: PDKDevice) -> SymbolData:
        """Generate resistor symbol (custom IC editor zigzag)."""
        shapes = []
        
        # Top lead
        shapes.append({"type": "line", "x1": 0, "y1": -35, "x2": 0, "y2": -18})
        
        # Zigzag pattern
        shapes.append({"type": "polyline", "points": [
            [0, -18], [10, -14], [-10, -6], [10, 2], [-10, 10], [0, 14]
        ]})
        
        # Bottom lead
        shapes.append({"type": "line", "x1": 0, "y1": 14, "x2": 0, "y2": 35})
        
        pins = self.PIN_TEMPLATES.get(DeviceCategory.RESISTOR, [])
        
        params = [{"name": p.name, "default": p.default, "description": p.description}
                  for p in device.parameters]
        
        return SymbolData(
            type="symbol",
            name=device.name,
            library=f"pdk:{self.pdk_name}",
            prefix=device.prefix,
            model=device.model,
            description=device.description,
            shapes=shapes,
            pins=pins,
            parameters=params,
            label={"text": f"@name\nR=@R", "x": 15, "y": 0},
        )
    
    def _generate_capacitor(self, device: PDKDevice) -> SymbolData:
        """Generate capacitor symbol (custom IC editor parallel plates)."""
        shapes = []
        
        # Top lead
        shapes.append({"type": "line", "x1": 0, "y1": -35, "x2": 0, "y2": -6})
        
        # Top plate
        shapes.append({"type": "line", "x1": -15, "y1": -6, "x2": 15, "y2": -6})
        
        # Bottom plate
        shapes.append({"type": "line", "x1": -15, "y1": 6, "x2": 15, "y2": 6})
        
        # Bottom lead
        shapes.append({"type": "line", "x1": 0, "y1": 6, "x2": 0, "y2": 35})
        
        pins = self.PIN_TEMPLATES.get(DeviceCategory.CAPACITOR, [])
        
        params = [{"name": p.name, "default": p.default, "description": p.description}
                  for p in device.parameters]
        
        return SymbolData(
            type="symbol",
            name=device.name,
            library=f"pdk:{self.pdk_name}",
            prefix=device.prefix,
            model=device.model,
            description=device.description,
            shapes=shapes,
            pins=pins,
            parameters=params,
            label={"text": f"@name\nC=@C", "x": 15, "y": 0},
        )
    
    def _generate_diode(self, device: PDKDevice) -> SymbolData:
        """Generate diode symbol (custom IC editor style)."""
        shapes = []
        
        # Top lead
        shapes.append({"type": "line", "x1": 0, "y1": -35, "x2": 0, "y2": -10})
        
        # Triangle (anode)
        shapes.append({"type": "polygon", "points": [[-12, -10], [12, -10], [0, 10]]})
        
        # Bar (cathode)
        shapes.append({"type": "line", "x1": -12, "y1": 10, "x2": 12, "y2": 10})
        
        # Bottom lead
        shapes.append({"type": "line", "x1": 0, "y1": 10, "x2": 0, "y2": 35})
        
        pins = self.PIN_TEMPLATES.get(DeviceCategory.DIODE, [])
        
        params = [{"name": p.name, "default": p.default, "description": p.description}
                  for p in device.parameters]
        
        return SymbolData(
            type="symbol",
            name=device.name,
            library=f"pdk:{self.pdk_name}",
            prefix=device.prefix,
            model=device.model,
            description=device.description,
            shapes=shapes,
            pins=pins,
            parameters=params,
            label={"text": f"@name\n@model", "x": 15, "y": 0},
        )
    
    def _generate_inductor(self, device: PDKDevice) -> SymbolData:
        """Generate inductor symbol (custom IC editor coils)."""
        shapes = []
        
        # Top lead
        shapes.append({"type": "line", "x1": 0, "y1": -35, "x2": 0, "y2": -18})
        
        # Three arcs
        shapes.append({"type": "arc", "cx": 0, "cy": -12, "rx": 6, "ry": 6, "start": -90, "span": 180})
        shapes.append({"type": "arc", "cx": 0, "cy": 0, "rx": 6, "ry": 6, "start": -90, "span": 180})
        shapes.append({"type": "arc", "cx": 0, "cy": 12, "rx": 6, "ry": 6, "start": -90, "span": 180})
        
        # Bottom lead
        shapes.append({"type": "line", "x1": 0, "y1": 18, "x2": 0, "y2": 35})
        
        pins = self.PIN_TEMPLATES.get(DeviceCategory.INDUCTOR, [])
        
        params = [{"name": p.name, "default": p.default, "description": p.description}
                  for p in device.parameters]
        
        return SymbolData(
            type="symbol",
            name=device.name,
            library=f"pdk:{self.pdk_name}",
            prefix=device.prefix,
            model=device.model,
            description=device.description,
            shapes=shapes,
            pins=pins,
            parameters=params,
            label={"text": f"@name\nL=@L", "x": 15, "y": 0},
        )
    
    def _generate_generic(self, device: PDKDevice) -> SymbolData:
        """Generate generic symbol for unknown device types."""
        shapes = [
            {"type": "rect", "x": -25, "y": -25, "w": 50, "h": 50},
        ]
        
        # Position pins on left side
        pins = []
        y = -20
        for pin in device.pins:
            pins.append({"name": pin.name, "x": -30, "y": y})
            y += 15
        
        params = [{"name": p.name, "default": p.default, "description": p.description}
                  for p in device.parameters]
        
        return SymbolData(
            type="symbol",
            name=device.name,
            library=f"pdk:{self.pdk_name}",
            prefix=device.prefix,
            model=device.model,
            description=device.description,
            shapes=shapes,
            pins=pins,
            parameters=params,
            label={"text": f"@name", "x": 15, "y": -20},
        )


def generate_device_symbol(device: PDKDevice, pdk_name: str = "") -> dict:
    """Generate symbol data dictionary for a PDK device."""
    generator = SymbolGenerator(pdk_name)
    symbol = generator.generate(device)
    return symbol.to_dict()
