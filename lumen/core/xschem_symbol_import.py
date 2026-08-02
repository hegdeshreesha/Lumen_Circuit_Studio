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
    arcs: List[Dict] = field(default_factory=list)
    polygons: List[Dict] = field(default_factory=list)
    boxes: List[Dict] = field(default_factory=list)
    texts: List[Dict] = field(default_factory=list)
    nets: List[Dict] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)
    format_str: str = ""
    template: str = ""
    
    def to_lumen_json(self) -> Dict:
        """Convert to Lumen symbol JSON format."""
        template_values = self._template_values()

        # Determine SPICE prefix/model from the xschem K/template block.
        prefix = (
            template_values.get("spiceprefix")
            or self.metadata.get("spiceprefix")
            or "X"
        ).strip('"')
        spice_model = (
            template_values.get("model")
            or self.metadata.get("model")
            or self.metadata.get("lvs_model")
            or self.name
        ).strip('"')
        
        # Build pins from B (box) commands
        pins = []
        for box in self.boxes:
            if "name" not in box:
                continue
            pin_name = box["name"]
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
                "bbox": [x1, y1, x2, y2],
                "direction": direction,
                "net_name": box.get("net_name"),
                "sim_pinnumber": box.get("sim_pinnumber"),
            })

        def pin_sort_key(pin: Dict):
            try:
                return int(pin.get("sim_pinnumber", 10_000))
            except (TypeError, ValueError):
                return 10_000

        if any(pin.get("sim_pinnumber") for pin in pins):
            pins.sort(key=pin_sort_key)
        
        # Convert L commands to shapes
        shapes = []
        for line in self.lines:
            x1, y1, x2, y2 = line["coords"]
            shapes.append({
                "type": "line",
                "x1": x1, "y1": y1,
                "x2": x2, "y2": y2,
                "source": "xschem",
            })

        for net in self.nets:
            x1, y1, x2, y2 = net["coords"]
            shapes.append({
                "type": "line",
                "x1": x1, "y1": y1,
                "x2": x2, "y2": y2,
                "source": "xschem",
            })

        for arc in self.arcs:
            cx, cy, r, start, span = arc["coords"]
            shapes.append({
                "type": "arc",
                "cx": cx,
                "cy": cy,
                "rx": r,
                "ry": r,
                "start": start,
                "span": span,
                "source": "xschem",
            })

        for polygon in self.polygons:
            shapes.append({
                "type": "polygon",
                "points": polygon["points"],
                "fill": polygon.get("fill", False),
                "source": "xschem",
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
                    "h": abs(y2 - y1),
                    "source": "xschem",
                })
        
        # Preserve Xschem text as interpreted label shapes. industry-standard does a
        # similar separation through symbol graphics plus CDF display labels.
        for text in self.texts:
            label_text = text.get("text", "")
            x, y = text.get("coords", (0, 0))[:2]
            role = "interpreted_label" if "@" in label_text else "pin_label"
            shapes.append({
                "type": "text",
                "text": label_text,
                "x": x,
                "y": y,
                "size": max(5, int(round(float(text.get("size", 0.2)) * 30))),
                "rotation": text.get("rotation", 0),
                "bold": label_text.startswith("@"),
                "role": role,
                "source": "xschem",
            })
        
        # Build symbol JSON
        symbol = {
            "type": "symbol",
            "name": self.name,
            "library": "imported",
            "prefix": prefix,
            "spice_model": spice_model,
            "component_name": spice_model,
            "source_format": "xschem",
            "pin_style": "terminal",
            "render_options": {
                "draw_pin_markers": True,
                "pin_marker_style": "xschem_box",
                "pin_marker_size": 5,
                "use_text_shapes_for_labels": True,
            },
            "xschem_format": self.format_str,
            "xschem_template": self.template,
            "xschem_metadata": self.metadata,
            "pins": pins,
            "shapes": shapes
        }
        
        params = []
        extra_keys = set(str(self.metadata.get("extra", "")).split())
        skip_template = {"name", "model", "spiceprefix", "prefix", *extra_keys}
        for key, value in template_values.items():
            if key in skip_template:
                continue
            params.append({
                "name": key,
                "default": value,
                "description": f"IHP/xschem parameter {key}",
            })
        symbol["parameters"] = params
        symbol["cdf"] = {
            "parameters": params,
            "term_order": [pin["name"] for pin in pins],
            "sim_info": {
                "spice": {
                    "prefix": prefix,
                    "component_name": spice_model,
                    "format": self.format_str,
                }
            },
            "display": {
                "interpreted_labels": True,
            },
        }
        
        return symbol

    def _template_values(self) -> Dict[str, str]:
        values: Dict[str, str] = {}
        for match in re.finditer(r'(\w+)=(".*?"|[^\s]+)', self.template):
            key, value = match.groups()
            values[key.strip()] = value.strip().strip('"')
        return values


class XschemSymbolParser:
    """Parse Xschem .sym files."""
    
    def parse_file(self, filepath: str) -> XschemSymbol:
        """Parse a Xschem symbol file."""
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        
        lines = content.split('\n')
        symbol = XschemSymbol(name=Path(filepath).stem)
        
        # Parse K section (metadata). Xschem allows multiline quoted values, so
        # keep the raw block and extract known keys with regex below.
        in_k_section = False
        k_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('K {'):
                in_k_section = True
                after = stripped[3:].strip()
                if after:
                    k_lines.append(after)
                continue
            if in_k_section:
                if stripped == '}':
                    in_k_section = False
                    break
                k_lines.append(line)
        
        # Parse K section content
        k_content = '\n'.join(k_lines)
        # Extract key=value pairs
        for match in re.finditer(r'(\w+)=([^\s"\n{}]+)', k_content):
            key, value = match.groups()
            symbol.metadata[key] = value
        
        # Extract format and template
        if 'format=' in k_content:
            fmt_match = re.search(r'format="(.*?)"', k_content, re.DOTALL)
            if fmt_match:
                symbol.format_str = fmt_match.group(1)
        
        if 'template="' in k_content:
            tmpl_match = re.search(r'template="(.*?)"', k_content, re.DOTALL)
            if tmpl_match:
                symbol.template = tmpl_match.group(1)

        extra_match = re.search(r'extra="(.*?)"', k_content, re.DOTALL)
        if extra_match:
            symbol.metadata["extra"] = extra_match.group(1)
        
        # Parse other commands
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('L '):
                # Xschem format: L <layer> <x1> <y1> <x2> <y2> {attrs}
                parts = line[2:].strip().split()
                if len(parts) < 5:
                    continue  # Skip malformed
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
                # Box: B <layer> x1 y1 x2 y2 {attrs}
                parts = line[2:].split()
                if len(parts) < 5:
                    continue
                coords = list(map(float, parts[1:5]))
                attrs = {}
                attrs_str = self._extract_attr_block(line)
                attrs.update(self._parse_attrs(attrs_str))
                symbol.boxes.append({
                    "coords": coords,
                    **attrs
                })
            elif line.startswith('P '):
                # Polygon: P <layer> <npoints> x1 y1 ... {attrs}
                parts = line[2:].split()
                if len(parts) < 4:
                    continue
                try:
                    npoints = int(float(parts[1]))
                    raw = [float(v) for v in parts[2:2 + npoints * 2]]
                    points = [[raw[i], raw[i + 1]] for i in range(0, len(raw), 2)]
                    if points:
                        attrs = self._parse_attrs(self._extract_attr_block(line))
                        symbol.polygons.append({
                            "points": points,
                            "fill": str(attrs.get("fill", "")).lower() == "true",
                        })
                except (ValueError, IndexError):
                    continue
            elif line.startswith('A '):
                # Arc: A <layer> cx cy r start span {attrs}
                parts = line[2:].split()
                if len(parts) < 6:
                    continue
                try:
                    symbol.arcs.append({
                        "coords": list(map(float, parts[1:6]))
                    })
                except ValueError:
                    continue
            elif line.startswith('N '):
                # Net segment in some symbols, used visually as internal wiring.
                parts = line[2:].split()
                if len(parts) < 4:
                    continue
                try:
                    symbol.nets.append({"coords": list(map(float, parts[:4]))})
                except ValueError:
                    continue
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
                        if part.replace('.', '').replace('-', '').isdigit():
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

    def _extract_attr_block(self, line: str) -> str:
        match = re.search(r'\{(.*)\}\s*$', line)
        return match.group(1) if match else ""

    def _parse_attrs(self, attrs_str: str) -> Dict[str, str]:
        attrs: Dict[str, str] = {}
        for match in re.finditer(r'(\w+)=(".*?"|[^\s{}]+)', attrs_str):
            key, value = match.groups()
            attrs[key] = value.strip('"')
        return attrs


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
