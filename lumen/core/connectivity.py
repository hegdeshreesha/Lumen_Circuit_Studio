"""
Lumen Circuit Studio — Connectivity Engine

Explicit wire connectivity graph for robust netlist generation.
Replaces naive union-find with proper junction/segment model.

Key features:
- Explicit junction nodes and wire segments
- Wire topology normalization (split/merge)
- Net name propagation from labels
- ERC-lite checks (floating pins, net shorts)
"""
from dataclasses import dataclass, field
from typing import Optional
import math


def _coerce_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class WireSegment:
    """A wire segment connecting two junctions."""
    id: str
    start_junction_id: str
    end_junction_id: str
    x1: float
    y1: float
    x2: float
    y2: float
    layer: str = "schematic"
    net_name: Optional[str] = None

    def __post_init__(self):
        self.x1 = _coerce_float(self.x1)
        self.y1 = _coerce_float(self.y1)
        self.x2 = _coerce_float(self.x2)
        self.y2 = _coerce_float(self.y2)


@dataclass
class Junction:
    """A connection point in the schematic (wire junction or pin)."""
    id: str
    x: float
    y: float
    connected_segment_ids: list[str] = field(default_factory=list)
    net_name: Optional[str] = None
    is_pin: bool = False
    pin_name: Optional[str] = None
    pin_instance: Optional[str] = None
    pin_library: Optional[str] = None
    pin_connections: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.x = _coerce_float(self.x)
        self.y = _coerce_float(self.y)
        if self.is_pin and self.pin_name and self.pin_instance and not self.pin_connections:
            self.pin_connections.append({
                "instance": self.pin_instance,
                "pin": self.pin_name,
                "library": self.pin_library,
            })


@dataclass
class Net:
    """A named electrical net."""
    name: str
    junction_ids: list[str] = field(default_factory=list)
    is_global: bool = False


class ConnectivityEngine:
    """
    Manages explicit wire connectivity graph.

    Models wires as segments between junctions, enabling:
    - Proper wire topology (junctions, T-connections, crossings)
    - Net name propagation from labels
    - ERC-lite validation
    """

    def __init__(self):
        self.junctions: dict[str, Junction] = {}
        self.segments: dict[str, WireSegment] = {}
        self.nets: dict[str, Net] = {}
        self._next_junction_id = 0
        self._next_segment_id = 0
        self._next_net_id = 0
        self._warnings: list[str] = []

    def _new_junction_id(self) -> str:
        """Generate unique junction ID."""
        jid = f"j{self._next_junction_id}"
        self._next_junction_id += 1
        return jid

    def _new_segment_id(self) -> str:
        """Generate unique segment ID."""
        sid = f"s{self._next_segment_id}"
        self._next_segment_id += 1
        return sid

    def reset(self):
        """Clear all data."""
        self.junctions.clear()
        self.segments.clear()
        self.nets.clear()
        self._next_junction_id = 0
        self._next_segment_id = 0
        self._next_net_id = 0
        self._warnings.clear()

    @staticmethod
    def _as_float(value: object, default: float = 0.0) -> float:
        """Best-effort numeric conversion for legacy schematic payloads."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _as_coord(cls, value: object, default: float = 0.0) -> int:
        return int(round(cls._as_float(value, default)))

    def build_from_schematic(self, schematic_data: dict) -> None:
        """
        Build connectivity graph from schematic JSON data.

        Args:
            schematic_data: Dict with 'wires', 'instances', 'labels', 'pins' keys
        """
        self.reset()

        # Step 1: Create junctions at all wire endpoints
        wire_endpoints: dict[tuple[float, float], str] = {}

        for wire in schematic_data.get("wires", []):
            x1, y1 = self._as_coord(wire.get("x1", 0)), self._as_coord(wire.get("y1", 0))
            x2, y2 = self._as_coord(wire.get("x2", 0)), self._as_coord(wire.get("y2", 0))

            j1 = self._get_or_create_junction(x1, y1)
            j2 = self._get_or_create_junction(x2, y2)

            wire_endpoints[(x1, y1)] = j1
            wire_endpoints[(x2, y2)] = j2

            # Record net name on wire if specified
            net_name = wire.get("net", "")

            # Create segment
            seg = WireSegment(
                id=self._new_segment_id(),
                start_junction_id=j1,
                end_junction_id=j2,
                x1=x1, y1=y1, x2=x2, y2=y2,
                net_name=net_name if net_name else None
            )
            self.segments[seg.id] = seg

            # Link to junctions
            self.junctions[j1].connected_segment_ids.append(seg.id)
            self.junctions[j2].connected_segment_ids.append(seg.id)
            if net_name:
                self.junctions[j1].net_name = str(net_name).strip()
                self.junctions[j2].net_name = str(net_name).strip()

        # Step 2: Process labels - assign net names to junctions
        for label in schematic_data.get("labels", []):
            x, y = self._as_coord(label.get("x", 0)), self._as_coord(label.get("y", 0))
            label_text = str(label.get("text", "")).strip()
            if not label_text:
                continue

            jid = self._get_or_create_wire_junction(x, y)
            self.junctions[jid].net_name = label_text

        for pin in schematic_data.get("pins", []):
            x, y = self._as_coord(pin.get("x", 0)), self._as_coord(pin.get("y", 0))
            jid = self._get_or_create_wire_junction(x, y)
            self.junctions[jid].net_name = str(pin.get("name", "")).strip()
            self._add_pin_to_junction(jid, "__top__", pin.get("name", ""), None)

        # Step 3: Process instance pins - connect to wires
        for inst in schematic_data.get("instances", []):
            inst_name = inst.get("name", "?")
            cell_name = inst.get("cell", "")
            lib_name = inst.get("library", "")
            ix, iy = self._as_coord(inst.get("x", 0)), self._as_coord(inst.get("y", 0))

            # Create junction at each pin position
            # We need symbol data to know pin locations
            # This will be passed separately via add_instance_pins()

        # Step 4: Handle special instances (gnd, vdd)
        for inst in schematic_data.get("instances", []):
            cell_name = inst.get("cell", "")
            if cell_name == "gnd":
                ix, iy = self._as_coord(inst.get("x", 0)), self._as_coord(inst.get("y", 0))
                # GND pin is at offset (0, -10)
                jid = self._get_or_create_wire_junction(ix, iy - 10)
                self.junctions[jid].net_name = "0"
                self._add_pin_to_junction(jid, inst.get("name", "gnd"), "gnd", None)
            elif cell_name == "vdd":
                ix, iy = self._as_coord(inst.get("x", 0)), self._as_coord(inst.get("y", 0))
                # VDD pin is at offset (0, +10)
                jid = self._get_or_create_wire_junction(ix, iy + 10)
                self.junctions[jid].net_name = "VDD"
                self._add_pin_to_junction(jid, inst.get("name", "vdd"), "vdd", None)

    def add_instance_pins(self, instance_name: str, library_name: str,
                           cell_name: str, x: float, y: float,
                           pin_data: list[dict], rotation: float = 0,
                           transform: Optional[dict] = None) -> None:
        """
        Add instance pins to the connectivity graph.

        Args:
            instance_name: Instance name (e.g., "R0")
            library_name: Library containing the cell
            cell_name: Cell name
            x, y: Instance position
            pin_data: List of pin dicts with 'name', 'x', 'y' (relative to instance)
            rotation: Instance rotation in degrees
            transform: Optional QTransform-style matrix dict for mirror/orient
        """
        for pin in pin_data:
            px, py = self._pin_scene_position(x, y, pin, rotation, transform)

            # If a pin lands on the middle of a wire, split that wire so the
            # pin participates in the same electrical net.
            jid = self._get_or_create_wire_junction(px, py)

            self._add_pin_to_junction(jid, instance_name, pin.get("name", "?"), library_name)
            if pin.get("net_name"):
                self.junctions[jid].net_name = str(pin.get("net_name")).strip()

    def _add_pin_to_junction(self, jid: str, instance: object, pin: object, library: object = None) -> None:
        """Attach a pin to a junction without overwriting other pins at that point."""
        if jid not in self.junctions:
            return
        j = self.junctions[jid]
        rec = {
            "instance": str(instance or ""),
            "pin": str(pin or ""),
            "library": str(library or ""),
        }
        if not rec["instance"] or not rec["pin"]:
            return
        j.is_pin = True
        if not j.pin_name:
            j.pin_name = rec["pin"]
            j.pin_instance = rec["instance"]
            j.pin_library = rec["library"]
        if rec not in j.pin_connections:
            j.pin_connections.append(rec)

    @staticmethod
    def _pin_scene_position(x: float, y: float, pin: dict,
                            rotation: float = 0,
                            transform: Optional[dict] = None) -> tuple[int, int]:
        """Resolve a symbol-local pin through instance mirror/rotation/translation."""
        px = float(pin.get("x", 0))
        py = float(pin.get("y", 0))

        if transform:
            m11 = float(transform.get("m11", 1))
            m12 = float(transform.get("m12", 0))
            m21 = float(transform.get("m21", 0))
            m22 = float(transform.get("m22", 1))
            dx = float(transform.get("dx", 0))
            dy = float(transform.get("dy", 0))
            px, py = (m11 * px) + (m21 * py) + dx, (m12 * px) + (m22 * py) + dy

        if rotation:
            theta = math.radians(float(rotation))
            c = math.cos(theta)
            s = math.sin(theta)
            px, py = (c * px) - (s * py), (s * px) + (c * py)

        return round(float(x) + px), round(float(y) + py)

    def _get_or_create_junction(self, x: float, y: float) -> str:
        """Get junction ID at position, creating if necessary."""
        pos = (self._as_coord(x), self._as_coord(y))
        for jid, j in self.junctions.items():
            if self._as_coord(j.x) == pos[0] and self._as_coord(j.y) == pos[1]:
                return jid

        jid = self._new_junction_id()
        self.junctions[jid] = Junction(id=jid, x=pos[0], y=pos[1])
        return jid

    def _find_junction_at(self, x: float, y: float) -> Optional[str]:
        """Find junction at exact position."""
        rx, ry = self._as_coord(x), self._as_coord(y)
        for jid, j in self.junctions.items():
            if self._as_coord(j.x) == rx and self._as_coord(j.y) == ry:
                return jid
        return None

    def _get_or_create_wire_junction(self, x: float, y: float) -> str:
        """Get a junction, splitting a segment if the point lies on a wire."""
        existing = self._find_junction_at(x, y)
        if existing:
            return existing

        rx, ry = self._as_coord(x), self._as_coord(y)
        for sid, seg in list(self.segments.items()):
            if self._point_on_segment(rx, ry, seg):
                return self._split_segment_at(sid, rx, ry)
        return self._get_or_create_junction(rx, ry)

    def _point_on_segment(self, x: float, y: float, seg: WireSegment) -> bool:
        """Return True when a point lies on a segment, excluding endpoints."""
        tol = 1e-6
        if (
            (abs(x - seg.x1) < tol and abs(y - seg.y1) < tol)
            or (abs(x - seg.x2) < tol and abs(y - seg.y2) < tol)
        ):
            return False
        if not self._is_collinear(seg.x1, seg.y1, seg.x2, seg.y2, x, y):
            return False
        return (
            min(seg.x1, seg.x2) - tol <= x <= max(seg.x1, seg.x2) + tol
            and min(seg.y1, seg.y2) - tol <= y <= max(seg.y1, seg.y2) + tol
        )

    def _endpoint_junction_at(self, seg: WireSegment, x: float, y: float) -> Optional[str]:
        tol = 1e-6
        if abs(x - seg.x1) < tol and abs(y - seg.y1) < tol:
            return seg.start_junction_id
        if abs(x - seg.x2) < tol and abs(y - seg.y2) < tol:
            return seg.end_junction_id
        return None

    def _point_on_segment_including_endpoints(self, x: float, y: float, seg: WireSegment) -> bool:
        tol = 1e-6
        if not self._is_collinear(seg.x1, seg.y1, seg.x2, seg.y2, x, y):
            return False
        return (
            min(seg.x1, seg.x2) - tol <= x <= max(seg.x1, seg.x2) + tol
            and min(seg.y1, seg.y2) - tol <= y <= max(seg.y1, seg.y2) + tol
        )

    def _ensure_segment_junction(self, segment_id: str, x: float, y: float) -> Optional[str]:
        """Ensure a segment has a junction at x/y, splitting if needed."""
        if segment_id not in self.segments:
            return None
        rx, ry = self._as_coord(x), self._as_coord(y)
        seg = self.segments[segment_id]
        endpoint = self._endpoint_junction_at(seg, rx, ry)
        if endpoint:
            return endpoint
        if self._point_on_segment_including_endpoints(rx, ry, seg):
            return self._split_segment_at(segment_id, rx, ry)
        return None

    def _merge_junctions(self, jid1: str, jid2: str) -> None:
        """Merge two junctions, updating all references."""
        if jid1 == jid2:
            return

        j1 = self.junctions[jid1]
        j2 = self.junctions[jid2]

        # Move all segments from j2 to j1
        for seg_id in j2.connected_segment_ids:
            seg = self.segments[seg_id]
            if seg.start_junction_id == jid2:
                seg.start_junction_id = jid1
            if seg.end_junction_id == jid2:
                seg.end_junction_id = jid1
            j1.connected_segment_ids.append(seg_id)

        # Merge net names (prefer named over unnamed)
        if j1.net_name is None and j2.net_name is not None:
            j1.net_name = j2.net_name
        if j2.net_name is not None and j1.net_name != j2.net_name:
            self._warnings.append(
                f"Net name conflict during merge: {j1.net_name} vs {j2.net_name}"
            )

        # Merge pin info
        if not j1.is_pin and j2.is_pin:
            j1.is_pin = j2.is_pin
            j1.pin_name = j2.pin_name
            j1.pin_instance = j2.pin_instance
            j1.pin_library = j2.pin_library
        for rec in j2.pin_connections:
            if rec not in j1.pin_connections:
                j1.pin_connections.append(rec)

        # Remove j2
        del self.junctions[jid2]

    def normalize_wires(self) -> list[str]:
        """
        Normalize wire topology:
        - Split segments at intersections
        - Merge collinear segments

        Returns:
            List of changes made (for logging/debugging)
        """
        changes = []

        # Phase 1: Detect and handle intersections
        changed = True
        iterations = 0
        max_iterations = 100  # Prevent infinite loops

        while changed and iterations < max_iterations:
            changed = False
            iterations += 1

            segment_ids = list(self.segments.keys())
            for i, sid1 in enumerate(segment_ids):
                if sid1 not in self.segments:
                    continue
                seg1 = self.segments[sid1]

                for sid2 in segment_ids[i+1:]:
                    if sid2 not in self.segments:
                        continue
                    seg2 = self.segments[sid2]

                    # Check for intersection
                    intersection = self._segments_intersect(seg1, seg2)
                    if intersection:
                        ix, iy = intersection
                        jid1 = self._ensure_segment_junction(sid1, ix, iy)
                        jid2 = self._ensure_segment_junction(sid2, ix, iy)
                        if jid1 and jid2 and jid1 != jid2:
                            self._merge_junctions(jid1, jid2)
                            changes.append(f"Connected segments at ({ix},{iy})")
                            changed = True

        # Phase 2: Merge collinear segments
        changed = True
        iterations = 0

        while changed and iterations < max_iterations:
            changed = False
            iterations += 1

            for sid in list(self.segments.keys()):
                if sid not in self.segments:
                    continue
                seg = self.segments[sid]

                # Try to merge with connected segments
                j1 = self.junctions.get(seg.start_junction_id)
                j2 = self.junctions.get(seg.end_junction_id)

                if j1 and j2:
                    # Check segment connected to start junction
                    for other_sid in j1.connected_segment_ids:
                        if other_sid != sid and other_sid in self.segments:
                            if self._can_merge(sid, other_sid):
                                if self._merge_segments(sid, other_sid):
                                    changes.append(f"Merged collinear segments {sid} and {other_sid}")
                                    changed = True

                    # Check segment connected to end junction
                    if not changed:
                        for other_sid in j2.connected_segment_ids:
                            if other_sid != sid and other_sid in self.segments:
                                if self._can_merge(sid, other_sid):
                                    if self._merge_segments(sid, other_sid):
                                        changes.append(f"Merged collinear segments {sid} and {other_sid}")
                                        changed = True

        return changes

    def _segments_intersect(self, seg1: WireSegment, seg2: WireSegment) -> Optional[tuple[float, float]]:
        """Check if two segments intersect, return intersection point or None."""
        # Check if segments are parallel
        dx1, dy1 = seg1.x2 - seg1.x1, seg1.y2 - seg1.y1
        dx2, dy2 = seg2.x2 - seg2.x1, seg2.y2 - seg2.y1

        # Cross product for parallel check
        cross = dx1 * dy2 - dy1 * dx2
        if abs(cross) < 1e-9:
            # Parallel - check for overlap
            return self._segments_overlap(seg1, seg2)

        # Line intersection
        # seg1: P1 + t*(P2-P1), seg2: Q1 + u*(Q2-Q1)
        px1, py1 = seg1.x1, seg1.y1
        px2, py2 = seg1.x2, seg1.y2
        qx1, qy1 = seg2.x1, seg2.y1
        qx2, qy2 = seg2.x2, seg2.y2

        denom = cross
        t = ((qx1 - px1) * dy2 - (qy1 - py1) * dx2) / denom
        u = ((qx1 - px1) * dy1 - (qy1 - py1) * dx1) / denom

        # Check if intersection is within both segments (with small tolerance)
        eps = 1e-9
        if -eps <= t <= 1 + eps and -eps <= u <= 1 + eps:
            ix = px1 + t * (px2 - px1)
            iy = py1 + t * (py2 - py1)
            tol = 1e-6
            on_seg1_end = (abs(ix - px1) < tol and abs(iy - py1) < tol) or \
                         (abs(ix - px2) < tol and abs(iy - py2) < tol)
            on_seg2_end = (abs(ix - qx1) < tol and abs(iy - qy1) < tol) or \
                         (abs(ix - qx2) < tol and abs(iy - qy2) < tol)
            if on_seg1_end or on_seg2_end:
                return (round(ix), round(iy))

        return None

    def _segments_overlap(self, seg1: WireSegment, seg2: WireSegment) -> Optional[tuple[float, float]]:
        """Check for overlapping parallel segments."""
        # Check if collinear
        if not self._is_collinear(seg1.x1, seg1.y1, seg1.x2, seg1.y2,
                                   seg2.x1, seg2.y1):
            return None

        # Check for overlap in 1D
        # Project onto primary axis
        if abs(seg1.x2 - seg1.x1) >= abs(seg1.y2 - seg1.y1):
            # Horizontal-ish
            min_x1, max_x1 = min(seg1.x1, seg1.x2), max(seg1.x1, seg1.x2)
            min_x2, max_x2 = min(seg2.x1, seg2.x2), max(seg2.x1, seg2.x2)
            if max(min_x1, min_x2) <= min(max_x1, max_x2) + 1e-6:
                # Overlap exists - return midpoint
                overlap_start = max(min_x1, min_x2)
                overlap_end = min(max_x1, max_x2)
                mid_x = (overlap_start + overlap_end) / 2
                mid_y = (seg1.y1 + seg1.y2) / 2  # Assume same y
                return (round(mid_x), round(mid_y))
        else:
            # Vertical-ish
            min_y1, max_y1 = min(seg1.y1, seg1.y2), max(seg1.y1, seg1.y2)
            min_y2, max_y2 = min(seg2.y1, seg2.y2), max(seg2.y1, seg2.y2)
            if max(min_y1, min_y2) <= min(max_y1, max_y2) + 1e-6:
                overlap_start = max(min_y1, min_y2)
                overlap_end = min(max_y1, max_y2)
                mid_y = (overlap_start + overlap_end) / 2
                mid_x = (seg1.x1 + seg1.x2) / 2
                return (round(mid_x), round(mid_y))

        return None

    def _is_collinear(self, x1: float, y1: float, x2: float, y2: float,
                     x3: float, y3: float) -> bool:
        """Check if point (x3,y3) is on line from (x1,y1) to (x2,y2)."""
        # Use cross product
        cross = (x2 - x1) * (y3 - y1) - (y2 - y1) * (x3 - x1)
        return abs(cross) < 1e-6

    def _split_segment_at(self, segment_id: str, x: float, y: float) -> str:
        """Split a segment at a given point, return new segment ID."""
        seg = self.segments[segment_id]
        old_end_jid = seg.end_junction_id

        # Create new junction at split point
        jid = self._get_or_create_junction(x, y)

        # Create new segment from split point to end
        new_seg = WireSegment(
            id=self._new_segment_id(),
            start_junction_id=jid,
            end_junction_id=old_end_jid,
            x1=x, y1=y, x2=seg.x2, y2=seg.y2,
            net_name=seg.net_name
        )

        # Update original segment
        seg.end_junction_id = jid
        seg.x2 = x
        seg.y2 = y

        # Add to graphs
        self.segments[new_seg.id] = new_seg
        if segment_id in self.junctions[old_end_jid].connected_segment_ids:
            self.junctions[old_end_jid].connected_segment_ids.remove(segment_id)
        if segment_id not in self.junctions[jid].connected_segment_ids:
            self.junctions[jid].connected_segment_ids.append(segment_id)
        if new_seg.id not in self.junctions[jid].connected_segment_ids:
            self.junctions[jid].connected_segment_ids.append(new_seg.id)
        if new_seg.id not in self.junctions[old_end_jid].connected_segment_ids:
            self.junctions[old_end_jid].connected_segment_ids.append(new_seg.id)

        return jid

    def _can_merge(self, seg1_id: str, seg2_id: str) -> bool:
        """Check if two segments can be merged (collinear and connected)."""
        if seg1_id not in self.segments or seg2_id not in self.segments:
            return False

        seg1 = self.segments[seg1_id]
        seg2 = self.segments[seg2_id]

        # Must share a junction
        shared_junctions = {seg1.start_junction_id, seg1.end_junction_id} & \
                          {seg2.start_junction_id, seg2.end_junction_id}
        if not shared_junctions:
            return False

        # Must be collinear
        j_shared = shared_junctions.pop()
        shared = self.junctions.get(j_shared)
        if shared:
            if shared.is_pin or shared.net_name:
                return False
            if len(set(shared.connected_segment_ids)) != 2:
                return False

        # Get the non-shared endpoints
        if seg1.start_junction_id == j_shared:
            other1_end = (seg1.x2, seg1.y2)
        else:
            other1_end = (seg1.x1, seg1.y1)

        if seg2.start_junction_id == j_shared:
            other2_end = (seg2.x2, seg2.y2)
        else:
            other2_end = (seg2.x1, seg2.y1)

        # Check if they form a straight line (non-collinear if angle is 180)
        # Actually, we want collinear segments pointing in same direction
        # Simple check: the three points should be collinear
        j = self.junctions[j_shared]
        return self._is_collinear(other1_end[0], other1_end[1],
                                  j.x, j.y,
                                  other2_end[0], other2_end[1])

    def _merge_segments(self, seg1_id: str, seg2_id: str) -> bool:
        """Merge two collinear connected segments."""
        if seg1_id not in self.segments or seg2_id not in self.segments:
            return False

        seg1 = self.segments[seg1_id]
        seg2 = self.segments[seg2_id]

        shared = {seg1.start_junction_id, seg1.end_junction_id} & {
            seg2.start_junction_id,
            seg2.end_junction_id,
        }
        if not shared:
            return False
        shared_jid = next(iter(shared))

        def outer_endpoint(seg: WireSegment) -> tuple[str, float, float]:
            if seg.start_junction_id == shared_jid:
                return seg.end_junction_id, seg.x2, seg.y2
            return seg.start_junction_id, seg.x1, seg.y1

        start_jid, x1, y1 = outer_endpoint(seg1)
        end_jid, x2, y2 = outer_endpoint(seg2)
        if start_jid == end_jid:
            return False

        old_refs = {
            seg1.start_junction_id,
            seg1.end_junction_id,
            seg2.start_junction_id,
            seg2.end_junction_id,
        }
        seg1.start_junction_id = start_jid
        seg1.end_junction_id = end_jid
        seg1.x1, seg1.y1 = x1, y1
        seg1.x2, seg1.y2 = x2, y2

        for jid in old_refs:
            junction = self.junctions.get(jid)
            if not junction:
                continue
            junction.connected_segment_ids = [
                sid for sid in junction.connected_segment_ids
                if sid not in {seg1_id, seg2_id}
            ]
        for jid in (start_jid, end_jid):
            if jid in self.junctions and seg1_id not in self.junctions[jid].connected_segment_ids:
                self.junctions[jid].connected_segment_ids.append(seg1_id)

        del self.segments[seg2_id]
        shared_j = self.junctions.get(shared_jid)
        if (
            shared_j is not None
            and not shared_j.connected_segment_ids
            and not shared_j.is_pin
            and not shared_j.net_name
        ):
            del self.junctions[shared_jid]

        return True

    def get_net_map(self) -> dict[str, list[str]]:
        """
        Get net mapping: net name -> list of (instance, pin) connections.

        Returns:
            Dict like {"net0": ["R1.d", "C1.1"], "VOUT": ["out", "R2.2"]}
        """
        net_map: dict[str, list[str]] = {}

        for component in self._connected_components():
            net_name = self._choose_component_net_name(component)
            for jid in component:
                self.junctions[jid].net_name = net_name

            for jid in component:
                j = self.junctions[jid]
                if not j.is_pin:
                    continue
                connections = j.pin_connections or [{
                    "instance": j.pin_instance,
                    "pin": j.pin_name,
                }]
                for rec in connections:
                    key = f"{rec.get('instance')}.{rec.get('pin')}"
                    net_map.setdefault(net_name, [])
                    if key not in net_map[net_name]:
                        net_map[net_name].append(key)

        return net_map

    def _connected_components(self) -> list[list[str]]:
        """Return wire-connected junction components in deterministic order."""
        components: list[list[str]] = []
        visited: set[str] = set()

        def sort_key(jid: str) -> tuple[float, float, str]:
            j = self.junctions[jid]
            return (j.x, j.y, jid)

        for start in sorted(self.junctions.keys(), key=sort_key):
            if start in visited:
                continue
            queue = [start]
            visited.add(start)
            component: list[str] = []
            while queue:
                jid = queue.pop(0)
                component.append(jid)
                j = self.junctions[jid]
                for seg_id in j.connected_segment_ids:
                    seg = self.segments.get(seg_id)
                    if not seg:
                        continue
                    for other_jid in (seg.start_junction_id, seg.end_junction_id):
                        if other_jid not in visited:
                            visited.add(other_jid)
                            queue.append(other_jid)
            components.append(sorted(component, key=sort_key))

        return components

    def _choose_component_net_name(self, component: list[str]) -> str:
        """Choose the canonical net name for a connected component."""
        names: list[str] = []
        for jid in component:
            name = str(self.junctions[jid].net_name or "").strip()
            if name and name not in names:
                names.append(name)

        if names:
            if "0" in names or any(n.upper() == "GND" for n in names):
                chosen = "0"
            else:
                globals_first = [n for n in names if n.upper() in {"VDD", "VSS", "VCC", "VEE"}]
                chosen = globals_first[0] if globals_first else names[0]

            for name in names:
                normalized = "0" if name.upper() == "GND" else name
                if normalized != chosen:
                    self._warnings.append(f"Net name conflict: {chosen} connected to {name}")
            return chosen

        name = f"net{self._next_net_id}"
        self._next_net_id += 1
        return name

    def _propagate_net_names(self) -> None:
        """Propagate net names from labeled junctions through connectivity."""
        # BFS from each named junction
        visited = set()

        for jid, j in self.junctions.items():
            if j.net_name and jid not in visited:
                # BFS to propagate this name
                queue = [jid]
                while queue:
                    current = queue.pop(0)
                    if current in visited:
                        continue
                    visited.add(current)

                    current_j = self.junctions[current]
                    # Propagate name to connected junctions without names
                    for seg_id in current_j.connected_segment_ids:
                        seg = self.segments[seg_id]
                        for other_jid in [seg.start_junction_id, seg.end_junction_id]:
                            if other_jid != current and other_jid not in visited:
                                other_j = self.junctions[other_jid]
                                if other_j.net_name is None:
                                    other_j.net_name = current_j.net_name
                                    queue.append(other_jid)
                                elif other_j.net_name != current_j.net_name:
                                    self._warnings.append(
                                        f"Net conflict: {current_j.net_name} trying to "
                                        f"connect to {other_j.net_name} at junction {other_jid}"
                                    )

    def get_warnings(self) -> list[str]:
        """Return any warnings generated during processing."""
        return list(self._warnings)

    def find_floating_pins(self) -> list[dict]:
        """Find pins not connected to any wire (floating)."""
        floating = []

        for jid, j in self.junctions.items():
            if j.is_pin:
                # Check if connected to any segment
                if not j.connected_segment_ids:
                    for rec in j.pin_connections or [{"instance": j.pin_instance, "pin": j.pin_name, "library": j.pin_library}]:
                        floating.append({
                            "instance": rec.get("instance"),
                            "pin": rec.get("pin"),
                            "library": rec.get("library"),
                            "x": j.x,
                            "y": j.y
                        })

        return floating

    def find_net_shorts(self) -> list[dict]:
        """Find instances where same pin type connected to different named nets."""
        # This would require tracking per-pin-type connections
        # Simplified: check if any pin has conflicting net connections
        shorts = []

        # Group pins by (instance, pin_name)
        pin_connections: dict[tuple[str, str], list[str]] = {}

        for jid, j in self.junctions.items():
            if j.is_pin and j.net_name:
                for rec in j.pin_connections or [{"instance": j.pin_instance, "pin": j.pin_name}]:
                    key = (rec.get("instance"), rec.get("pin"))
                    if key not in pin_connections:
                        pin_connections[key] = []
                    if j.net_name not in pin_connections[key]:
                        pin_connections[key].append(j.net_name)

        for (inst, pin), nets in pin_connections.items():
            if len(nets) > 1:
                shorts.append({
                    "instance": inst,
                    "pin": pin,
                    "conflicting_nets": nets
                })

        return shorts

    def find_unconnected_bulks(self) -> list[dict]:
        """Find MOSFET instances whose bulk (B/BULK) terminal is floating."""
        unconnected = []
        bulk_pin_names = {"B", "BULK", "B4", "4"}
        for jid, j in self.junctions.items():
            if not j.is_pin or j.connected_segment_ids:
                continue
            for rec in j.pin_connections or [{"instance": j.pin_instance, "pin": j.pin_name, "library": j.pin_library}]:
                pin_name = str(rec.get("pin") or "")
                if pin_name.upper() in bulk_pin_names:
                    unconnected.append({
                        "instance": rec.get("instance"),
                        "pin": pin_name,
                        "library": rec.get("library"),
                        "x": j.x,
                        "y": j.y
                    })
        return unconnected

    def run_check_and_save(self) -> dict:
        """
        Comprehensive Check & Save validation pipeline.
        Returns detailed report containing errors, warnings, floating pins, and unconnected bulks.
        """
        floating = self.find_floating_pins()
        shorts = self.find_net_shorts()
        unconnected_bulks = self.find_unconnected_bulks()
        errors = [f"Net short on instance '{s['instance']}' pin '{s['pin']}': {s['conflicting_nets']}" for s in shorts]
        warnings = self.get_warnings()
        for fp in floating:
            warnings.append(f"Floating pin on instance '{fp['instance']}' pin '{fp['pin']}' at ({fp['x']}, {fp['y']})")
        for ub in unconnected_bulks:
            warnings.append(f"Unconnected MOS Bulk (B) terminal on instance '{ub['instance']}'")

        is_valid = len(errors) == 0
        return {
            "valid": is_valid,
            "errors": errors,
            "warnings": warnings,
            "floating_pins": floating,
            "net_shorts": shorts,
            "unconnected_bulks": unconnected_bulks,
            "stats": self.get_stats()
        }

    def get_junction_at(self, x: float, y: float) -> Optional[Junction]:
        """Get junction at position if exists."""
        jid = self._find_junction_at(x, y)
        if jid:
            return self.junctions[jid]
        return None

    def get_segments_connected_to_junction(self, jid: str) -> list[WireSegment]:
        """Get all segments connected to a junction."""
        if jid not in self.junctions:
            return []
        return [self.segments[sid] for sid in self.junctions[jid].connected_segment_ids
                if sid in self.segments]

    def get_stats(self) -> dict:
        """Get statistics about the connectivity graph."""
        return {
            "junction_count": len(self.junctions),
            "segment_count": len(self.segments),
            "pin_count": sum(1 for j in self.junctions.values() if j.is_pin),
            "named_net_count": sum(1 for j in self.junctions.values() if j.net_name),
            "warning_count": len(self._warnings)
        }
