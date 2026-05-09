import os
import re

class XschemParser:
    """Parses Xschem .sym files into Lumen symbol format."""
    
    @staticmethod
    def parse_sym_file(filepath: str) -> dict | None:
        if not os.path.isfile(filepath):
            return None
            
        with open(filepath, 'r') as f:
            content = f.read()
            
        return XschemParser.parse_sym_string(content, os.path.basename(filepath).replace(".sym", ""))
        
    @staticmethod
    def parse_sym_string(content: str, name: str) -> dict:
        symbol = {
            "type": "symbol",
            "name": name,
            "description": f"Xschem imported symbol for {name}",
            "parameters": [],
            "shapes": [],
            "pins": [],
            "label": {"text": "@name", "x": 15, "y": -25}
        }
        
        # Super simple parser for Xschem primitives
        # Line format: L layer x1 y1 x2 y2 {attributes}
        for line in content.split('\n'):
            line = line.strip()
            if not line:
                continue
                
            parts = line.split()
            cmd = parts[0]
            
            try:
                if cmd == 'L':
                    # L layer x1 y1 x2 y2 {attrs}
                    x1, y1, x2, y2 = map(float, parts[2:6])
                    symbol["shapes"].append({
                        "type": "line",
                        "x1": x1, "y1": y1, "x2": x2, "y2": y2
                    })
                elif cmd == 'B':
                    # B layer x1 y1 x2 y2 {attrs}
                    x1, y1, x2, y2 = map(float, parts[2:6])
                    w = x2 - x1
                    h = y2 - y1
                    symbol["shapes"].append({
                        "type": "rect",
                        "x": x1, "y": y1, "w": w, "h": h
                    })
                    # Check for pin definition
                    attrs = " ".join(parts[6:])
                    pin_match = re.search(r'name=([^\s}]+)', attrs)
                    if pin_match:
                        pin_name = pin_match.group(1)
                        symbol["pins"].append({
                            "name": pin_name,
                            "x": x1 + w/2,
                            "y": y1 + h/2
                        })
                elif cmd == 'P':
                    # P layer num_points x1 y1 x2 y2 ... {attrs}
                    num_pts = int(parts[2])
                    pts = parts[3:3+num_pts*2]
                    polygon = []
                    for i in range(0, len(pts), 2):
                        polygon.append([float(pts[i]), float(pts[i+1])])
                    symbol["shapes"].append({
                        "type": "polygon",
                        "points": polygon
                    })
                elif cmd == 'A':
                    # A layer x y radius start_angle end_angle {attrs}
                    cx, cy, radius, start, end = map(float, parts[2:7])
                    symbol["shapes"].append({
                        "type": "arc",
                        "cx": cx, "cy": cy,
                        "rx": radius, "ry": radius,
                        "start": start, "span": end - start
                    })
                elif cmd == 'K':
                    # Global attributes
                    attrs = " ".join(parts[1:])
                    # Look for format string
                    format_match = re.search(r'format="([^"]+)"', attrs)
                    if format_match:
                        symbol["format"] = format_match.group(1)
            except (ValueError, IndexError):
                pass
                
        return symbol
