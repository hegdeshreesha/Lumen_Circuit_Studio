# Sprint 1: Connectivity Engine - Technical Specification

## Overview

Replace the naive union-find netlist generation with a proper explicit connectivity graph that models:
- **Junctions**: Points where wires connect (3+ segments, pins, labels)
- **Wire Segments**: Straight line segments between junctions
- **Net Names**: Named nets from labels, power/ground, user-defined

This enables robust wire topology operations and eliminates connectivity bugs in netlist generation.

## Data Model

### Core Classes

```python
@dataclass
class WireSegment:
    id: str                           # Unique identifier
    start_junction_id: str           # Start junction
    end_junction_id: str             # End junction
    x1: float                         # Start point (cached for fast lookup)
    y1: float
    x2: float
    y2: float
    layer: str = "schematic"          # For future layout support

@dataclass
class Junction:
    id: str                           # Unique identifier "j{index}"
    x: float
    y: float
    connected_segment_ids: list[str]  # Adjacency list
    net_name: str | None = None       # Assigned net name (from label/power)
    is_pin: bool = False              # Connected to instance pin
    pin_name: str | None = None       # If is_pin, which pin
    pin_instance: str | None = None   # If is_pin, which instance

@dataclass
class Net:
    name: str                         # Net name (e.g., "VOUT", "net42")
    junction_ids: list[str]           # All junctions in this net
    is_global: bool = False           # GND, VDD, etc.
```

### ConnectivityEngine Class

```python
class ConnectivityEngine:
    """Manages explicit wire connectivity graph."""

    def __init__(self):
        self.junctions: dict[str, Junction] = {}
        self.segments: dict[str, WireSegment] = {}
        self.nets: dict[str, Net] = {}
        self._next_junction_id = 0
        self._next_segment_id = 0

    # Building from schematic data
    def build_from_schematic(self, schematic_data: dict) -> None:
        """Build connectivity graph from schematic JSON data."""

    # Wire normalization
    def normalize_wires(self) -> list[str]:
        """Split/merge wires, return list of changes made."""

    def split_segment_at_point(self, segment_id: str, x: float, y: float) -> str:
        """Split a segment at a given point, return new segment id."""

    def merge_collinear_segments(self, segment_id1: str, segment_id2: str) -> bool:
        """Merge two collinear segments, return True if merged."""

    # Net extraction
    def get_net_for_junction(self, junction_id: str) -> str:
        """Get net name for a junction (resolves through net graph)."""

    def get_all_nets(self) -> dict[str, list[str]]:
        """Return dict of net_name -> list of (instance, pin) connections."""

    # Validation
    def find_floating_pins(self) -> list[dict]:
        """Return list of pins not connected to any net."""

    def find_net_shorts(self) -> list[dict]:
        """Find instances where same pin connected to different named nets."""
```

## Algorithm: Wire Normalization

### Step 1: Build Initial Graph
1. Create junctions at every wire endpoint
2. Create segments between connected endpoints
3. Track which junctions are connected to instance pins

### Step 2: Detect Intersections
- For each pair of segments, detect if they intersect
- If intersection not at existing junction, split both segments
- Handle T-junctions and cross-junctions

### Step 3: Merge Collinear
- Find sequences of segments on same line
- Replace with single segment (reduces graph complexity)

### Step 4: Assign Net Names
- Walk from labeled junctions, propagate names through connected graph
- Handle global nets (GND, VDD, etc.) specially

## Integration Points

### netlist.py Changes

```python
class NetlistGenerator:
    def __init__(self, db: LibraryDatabase):
        self.db = db
        self._net_counter = 0
        self._errors: list[str] = []
        self._connectivity = None  # NEW: ConnectivityEngine

    def generate(self, library: str, cell: str, view: str = "schematic",
                 flat: bool = True, use_connectivity: bool = True) -> str:
        """Generate SPICE netlist with proper connectivity."""
        # ... existing code ...
        if use_connectivity:
            self._connectivity = ConnectivityEngine()
            self._connectivity.build_from_schematic(data)
            self._connectivity.normalize_wires()
            # Use connectivity graph for net mapping
        else:
            # Fall back to union-find for compatibility
```

## Test Cases

### Basic Connectivity
- Two resistors in series → single net
- Wire with label → net gets name
- Floating pin → warning generated

### Wire Topology
- Crossing wires (no dot) → different nets
- T-junction → single net
- Multiple segments collinear → merged

### Corner Cases
- Wire connecting to pin exactly at pin position
- Label at wire start vs middle vs end
- Hierarchical net names (e.g., "vdd!" in subcircuit)

## Acceptance Criteria

1. Netlist generated matches custom IC editor/Ocean output for same schematic
2. No "floating pin" errors for properly connected instances
3. Net names correctly propagate from labels
4. Wire crossing without junction dot stays isolated (standard schematic rule)
5. Undo/redo works correctly for all wire operations
6. Performance: <100ms for schematics with 500+ wires