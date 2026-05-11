"""
Lumen Circuit Studio — Xschem Symbol Importer

Converts Xschem .sym files to Lumen's JSON symbol format.
Enables importing professional symbols from existing PDKs.

Xschem Symbol Format:
- L commands: lines/polylines
- B commands: boxes (pins)
- T commands: text labels
- K section: metadata (type, format, template)
"""
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
import json


@dataclass
class XschemSymbol:
    """Parsed Xschem symbol data."""
    name: str
    pins: List[Dict] = field(default_factory=list)
    lines: List[Dict] = field(default_factory=list)
    boxes: List[Dict] = field(default_factory=list)
    texts: List[Dict] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)
    format_str: str = ""
    template: str = ""
    
    def to_lumen_json(self) -> Dict:
        """Convert to Lumen symbol JSON format."""
        # Determine SPICE prefix from metadata or infer
        prefix = self.metadata.get("prefix", "X")
        spice_model = self.metadata.get("spice_model", self.name)
        
        # Build pins from B (box) commands
        pins = []
        for box in self.boxes:
            pin_name = box.get("name", f"PIN{len(pins)+1}")
            # Xschem coords: box is [x1, y1, x2, y2]
            x1, y1, x2, y2 = box["coords"]
            # Pin position: center of box
            x_center = (x1 + x2) / 2
            y_center = (y1 + y2) / 2
            direction = box.get("dir", "inout")
            
            pins.append({
                "name": pin_name,
                "x": x_center,
                "y": y_center,
                "direction": direction,
                "net_name": box.get("net_name")
            })
        
        # Convert L commands to shapes
        shapes = []
        for line in self.lines:
            # L x1 y1 x2 y2 {layer=N}
            x1, y1, x2, y2 = line["coords"]
            shapes.append({
                "type": "line",
                "x1": x1, "y1": y1,
                "x2": x2, "y2": y2
            })
        
        # Convert B commands that are not pins (decorations)
        for box in self.boxes:
            if "name" not in box:
                # Decorative box
                x1, y1, x2, y2 = box["coords"]
                shapes.append({
                    "type": "rect",
                    "x": min(x1, x2),
                    "y": min(y1, y2),
                    "w": abs(x2 - x1),
                    "h": abs(y2 - y1)
                })
        
        # Add text labels as shapes (or separate label field)
        label = None
        for text in self.texts:
            # T {text} x y rotation size {layer=N}
            label_text = text.get("text", "")
            x, y = text.get("coords", (0, 0))[:2]
            if label_text.startswith("@"):
                # This is the main label
                label = {"text": label_text, "x": x, "y": y}
        
        # Build symbol JSON
        symbol = {
            "type": "symbol",
            "name": self.name,
            "library": "imported",
            "prefix": prefix,
            "spice_model": spice_model,
            "pins": pins,
            "shapes": shapes
        }
        
        if label:
            symbol["label"] = label
        
        # Extract parameters from format string
        params = []
        if self.format_str:
            # format="@name @pinlist sky130_fd_pr__@model W=@W L=@L m=@mult"
            parts = self.format_str.split()
            for part in parts:
                if "=" in part:
                    name, _, default = part.partition("=")
                    if name.startswith("@") and name[1:]:
                        param_name = name[1:]
                        params.append({
                            "name": param_name,
                            "default": default,
                            "description": f"Parameter {param_name}"
                        })
        symbol["parameters"] = params
        
        return symbol


class XschemSymbolParser:
    """Parse Xschem .sym files."""
    
    def parse_file(self, filepath: str) -> XschemSymbol:
        """Parse a Xschem symbol file."""
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        
        lines = content.split('\n')
        symbol = XschemSymbol(name=Path(filepath).stem)
        
        # Parse K section (metadata)
        in_k_section = False
        k_lines = []
        for line in lines:
            line = line.strip()
            if line.startswith('K {'):
                in_k_section = True
                continue
            if in_k_section:
                if line == '}':
                    in_k_section = False
                    break
                k_lines.append(line)
        
        # Parse K section content
        k_content = ' '.join(k_lines)
        # Extract key=value pairs
        for match in re.finditer(r'(\w+)=([^\s]+)', k_content):
            key, value = match.groups()
            symbol.metadata[key] = value
        
        # Extract format and template
        if 'format=' in k_content:
            fmt_match = re.search(r'format="([^"]+)"', k_content)
            if fmt_match:
                symbol.format_str = fmt_match.group(1)
        
        if 'template="' in k_content:
            tmpl_match = re.search(r'template="([^"]+)"', k_content, re.DOTALL)
            if tmpl_match:
                symbol.template = tmpl_match.group(1)
        
        # Parse other commands
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('L '):
                # Line: L <linewidth> x1 y1 x2 y2 {layer=N}
                # Xschem format: L <width> <x1> <y1> <x2> <y2> {layer=N}
                parts = line[2:].strip().split()
                if len(parts) < 5:
                    continue  # Skip malformed
                # Skip linewidth (parts[0]), take next 4 as coords
                coords = list(map(float, parts[1:5]))
                layer = None
                # Check if there's a layer attribute in the remaining parts
                if len(parts) > 5:
                    rest = ' '.join(parts[5:])
                    if 'layer=' in rest:
                        layer = rest.split('layer=')[1].rstrip('}')
                symbol.lines.append({
                    "coords": coords,
                    "layer": layer
                })
            elif line.startswith('B '):
                # Box: B x1 y1 x2 y2 {attrs}
                parts = line[2:].split()
                coords = list(map(float, parts[:4]))
                attrs = {}
                if len(parts) > 4:
                    attrs_str = ' '.join(parts[4:]).strip('{}')
                    for attr in attrs_str.split():
                        if '=' in attr:
                            k, v = attr.split('=', 1)
                            attrs[k] = v
                symbol.boxes.append({
                    "coords": coords,
                    **attrs
                })
            elif line.startswith('T '):
                # Text: T {text} x y rotation size {layer=N}
                # Extract text in braces
                text_match = re.search(r'T\s+\{([^}]+)\}\s+([\d\.\-]+)\s+([\d\.\-]+)', line)
                if text_match:
                    text = text_match.group(1)
                    x = float(text_match.group(2))
                    y = float(text_match.group(3))
                    # Get rest for rotation, size, layer
                    rest = line[text_match.end():]
                    rotation = 0.0
                    size = 0.2
                    layer = None
                    for part in rest.split():
                        if part.replace('.', '').isdigit():
                            if rotation == 0.0:
                                rotation = float(part)
                            else:
                                size = float(part)
                        elif part.startswith('layer='):
                            layer = part.split('=')[1].rstrip('}')
                    symbol.texts.append({
                        "text": text,
                        "coords": (x, y),
                        "rotation": rotation,
                        "size": size,
                        "layer": layer
                    })
        
        return symbol


def convert_xschem_directory(input_dir: str, output_dir: str) -> Tuple[int, List[str]]:
    """
    Convert all .sym files in a directory to Lumen JSON format.
    
    Returns:
        (count, errors) - number of files converted and list of errors
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    parser = XschemSymbolParser()
    count = 0
    errors = []
    
    for sym_file in input_path.glob("*.sym"):
        try:
            symbol = parser.parse_file(str(sym_file))
            lumen_json = symbol.to_lumen_json()
            
            # Save as JSON
            output_file = output_path / f"{sym_file.stem}.symbol.json"
            with open(output_file, 'w') as f:
                json.dump(lumen_json, f, indent=2)
            count += 1
        except Exception as e:
            errors.append(f"{sym_file.name}: {str(e)}")
    
    return count, errors


if __name__ == "__main__":
    # Example usage
    import sys
    if len(sys.argv) == 3:
        input_dir, output_dir = sys.argv[1], sys.argv[2]
        count, errors = convert_xschem_directory(input_dir, output_dir)
        print(f"Converted {count} symbols")
        if errors:
            print("Errors:")
            for err in errors:
                print(f"  {err}")
    else:
        print("Usage: python xschem_symbol_import.py <input_dir> <output_dir>")