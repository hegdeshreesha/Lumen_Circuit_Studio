"""Technology layer parsing and layout interoperability helpers."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class LayoutLayer:
    """A physical technology layer/purpose entry."""

    name: str
    purpose: str
    gds_layer: int
    gds_datatype: int
    color: str = "#808080"
    visible: bool = True
    valid: bool = True
    source: str = ""
    display_name: str = ""
    stream_name: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def parse_klayout_layer_properties(layer_properties_file: str | Path) -> list[LayoutLayer]:
    """Parse a KLayout .lyp file into Lumen's layer registry format."""
    path = Path(layer_properties_file)
    if not path.exists():
        return []
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []

    layers: list[LayoutLayer] = []
    seen: set[tuple[str, str, int, int]] = set()
    for props in root.findall(".//properties"):
        name_text = _child_text(props, "name")
        source = _child_text(props, "source")
        parsed_source = _parse_source(source)
        if not name_text or parsed_source is None:
            continue
        layer_name, purpose = _split_layer_name(name_text)
        gds_layer, gds_datatype = parsed_source
        key = (layer_name, purpose, gds_layer, gds_datatype)
        if key in seen:
            continue
        seen.add(key)
        layers.append(
            LayoutLayer(
                name=layer_name,
                purpose=purpose,
                gds_layer=gds_layer,
                gds_datatype=gds_datatype,
                color=_child_text(props, "frame-color") or _child_text(props, "fill-color") or "#808080",
                visible=_parse_bool(_child_text(props, "visible"), default=True),
                valid=_parse_bool(_child_text(props, "valid"), default=True),
                source=source,
                display_name=name_text,
                stream_name=f"{layer_name}/{purpose}",
            )
        )
    return sorted(layers, key=lambda item: (item.gds_layer, item.gds_datatype, item.name, item.purpose))


def layer_table_for_view(layers: list[LayoutLayer]) -> list[dict]:
    """Return serializable layer records suitable for layout view metadata."""
    return [layer.as_dict() for layer in layers]


def _child_text(element: ET.Element, name: str) -> str:
    child = element.find(name)
    return (child.text or "").strip() if child is not None else ""


def _parse_source(source: str) -> tuple[int, int] | None:
    match = re.match(r"^\s*(\d+)\s*/\s*(\d+)", source or "")
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _split_layer_name(name_text: str) -> tuple[str, str]:
    if "." in name_text:
        layer, purpose = name_text.split(".", 1)
        return layer.strip(), purpose.strip()
    if "/" in name_text:
        layer, purpose = name_text.split("/", 1)
        return layer.strip(), purpose.strip()
    return name_text.strip(), "drawing"


def _parse_bool(value: str, default: bool = False) -> bool:
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return default
