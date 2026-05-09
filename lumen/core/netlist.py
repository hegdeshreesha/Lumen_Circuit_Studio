"""
Lumen Circuit Studio — SPICE Netlist Generator

Traverses a schematic design hierarchy and produces a flat or
hierarchical SPICE netlist compatible with GSPICE, Ngspice, and Xyce.

Supports two connectivity models:
- Legacy union-find (for backward compatibility)
- ConnectivityEngine (new, explicit junction/segment graph)
"""
import os
from dataclasses import dataclass, field
from typing import Optional
from lumen.core.database import LibraryDatabase
from lumen.core.connectivity import ConnectivityEngine


@dataclass
class NetlistDirectives:
    """SPICE simulation directives for netlist generation."""
    includes: list[str] = field(default_factory=list)
    libs: list[str] = field(default_factory=list)
    params: dict[str, str] = field(default_factory=dict)
    options: dict[str, str] = field(default_factory=dict)
    globals_: list[str] = field(default_factory=list)
    temp: Optional[float] = None
    measures: list[str] = field(default_factory=list)
    nodesets: list[str] = field(default_factory=list)
    ics: list[str] = field(default_factory=list)
    mc: Optional[dict] = None
    subcircuits: list[str] = field(default_factory=list)


class NetlistGenerator:
    """Generate SPICE netlists from schematic data."""

    def __init__(self, db: LibraryDatabase, use_connectivity: bool = True):
        self.db = db
        self._net_counter = 0
        self._errors: list[str] = []
        self._warnings: list[str] = []
        self._directives = NetlistDirectives()
        self._pdk_model_path: str = ""
        self._pdk_corner: str = ""
        self._use_connectivity = use_connectivity
        self._connectivity: Optional[ConnectivityEngine] = None

    def set_pdk_model(self, model_path: str, corner: str = ""):
        """Set PDK model file path and optional corner for .lib inclusion."""
        self._pdk_model_path = model_path
        self._pdk_corner = corner

    def set_use_connectivity(self, use: bool):
        """Enable/disable the new ConnectivityEngine."""
        self._use_connectivity = use

    def generate(self, library: str, cell: str,
                 view: str = "schematic", flat: bool = True) -> str:
        """Generate a SPICE netlist for the given cell.

        Args:
            library: Library name
            cell: Cell name
            view: View to netlist (usually "schematic")
            flat: If True, produce a flat netlist; else hierarchical .subckt

        Returns:
            SPICE netlist as a string
        """
        self._errors = []
        self._warnings = []
        self._net_counter = 0
        self._connectivity = None

        data = self.db.load_view(library, cell, view)
        if not data:
            return f"* ERROR: Cannot load {library}/{cell}/{view}\n"

        lines = []
        lines.append(f"* Lumen Circuit Studio — SPICE Netlist")
        lines.append(f"* Design: {library}/{cell}/{view}")
        lines.append(f"*")

        # PDK model includes
        lines.extend(self._generate_pdk_includes())

        # Build net connectivity map
        if self._use_connectivity:
            net_map = self._build_net_map_connectivity(data)
        else:
            net_map = self._build_net_map(data)

        # Generate subcircuit definitions first
        subckt_lines = self._generate_subcircuits(data)
        if subckt_lines:
            lines.append("")
            lines.append("* Subcircuit Definitions")
            lines.extend(subckt_lines)

        # Generate directives (PARAM, OPTIONS, GLOBAL, TEMP)
        lines.extend(self._generate_directives())

        if flat:
            # Generate flat netlist
            lines.append("")
            inst_lines = self._netlist_instances(data, net_map)
            lines.extend(inst_lines)
        else:
            # Generate hierarchical .subckt
            pins = data.get("pins", [])
            pin_names = [p.get("name", "") for p in pins]
            port_str = " ".join(pin_names) if pin_names else ""
            lines.append(f".SUBCKT {cell} {port_str}")
            inst_lines = self._netlist_instances(data, net_map)
            lines.extend(f"  {l}" for l in inst_lines)
            lines.append(f".ENDS {cell}")

        # Generate convergence helpers (.NODESET, .IC)
        lines.extend(self._generate_convergence_helpers())

        # Generate .MEASURE statements
        lines.extend(self._generate_measures())

        # Generate Monte Carlo if configured
        lines.extend(self._generate_monte_carlo())

        lines.append("")
        lines.append(".END")
        lines.append("")

        return "\n".join(lines)

    def _generate_pdk_includes(self) -> list[str]:
        """Generate .include and .lib directives for PDK model files."""
        lines = []
        for inc in self._directives.includes:
            lines.append(f".INCLUDE \"{inc}\"")
        for lib_entry in self._directives.libs:
            lines.append(f".LIB \"{lib_entry}\"")
        if self._pdk_model_path:
            if self._pdk_corner:
                lines.append(f".LIB \"{self._pdk_model_path}\" {self._pdk_corner}")
            else:
                lines.append(f".INCLUDE \"{self._pdk_model_path}\"")
        return lines

    def _generate_directives(self) -> list[str]:
        """Generate .PARAM, .OPTIONS, .GLOBAL, .TEMP statements."""
        lines = []
        if self._directives.params:
            lines.append("")
            lines.append("* Parameters")
            for name, value in self._directives.params.items():
                lines.append(f".PARAM {name} = {value}")
        if self._directives.options:
            lines.append("")
            lines.append("* Simulation Options")
            parts = [f"{k}={v}" for k, v in self._directives.options.items()]
            lines.append(f".OPTIONS {' '.join(parts)}")
        if self._directives.globals_:
            lines.append("")
            lines.append("* Global Nodes")
            lines.append(f".GLOBAL {' '.join(self._directives.globals_)}")
        if self._directives.temp is not None:
            lines.append("")
            lines.append(f"* Temperature")
            lines.append(f".TEMP {self._directives.temp}")
        return lines

    def _generate_convergence_helpers(self) -> list[str]:
        """Generate .NODESET and .IC statements."""
        lines = []
        if self._directives.nodesets:
            lines.append("")
            lines.append("* Node Sets")
            for ns in self._directives.nodesets:
                lines.append(ns)
        if self._directives.ics:
            lines.append("")
            lines.append("* Initial Conditions")
            for ic in self._directives.ics:
                lines.append(ic)
        return lines

    def _generate_measures(self) -> list[str]:
        """Generate .MEASURE statements."""
        lines = []
        if self._directives.measures:
            lines.append("")
            lines.append("* Measurements")
            for m in self._directives.measures:
                lines.append(m)
        return lines

    def _generate_monte_carlo(self) -> list[str]:
        """Generate .MC directive if configured."""
        lines = []
        mc = self._directives.mc
        if mc:
            lines.append("")
            lines.append("* Monte Carlo Analysis")
            analysis_type = mc.get("type", "DC")
            output = mc.get("output", "")
            num_runs = mc.get("runs", 100)
            expr = mc.get("expression", "")
            if expr:
                lines.append(f".MC {num_runs} {analysis_type} {output} {expr}")
        return lines

    def _generate_subcircuits(self, data: dict) -> list[str]:
        """Generate .SUBCKT definitions from data."""
        lines = []
        for sub in self._directives.subcircuits:
            lines.append(sub)
        return lines

    def get_errors(self) -> list[str]:
        """Return any errors from the last netlist generation."""
        return list(self._errors)

    def get_warnings(self) -> list[str]:
        """Return any warnings from the last netlist generation."""
        if self._connectivity:
            return self._connectivity.get_warnings()
        return list(self._warnings)

    # ── Net Map Construction ──────────────────────────────────

    def _build_net_map(self, data: dict) -> dict[str, str]:
        """Build a mapping from (instance, pin) -> net name.

        Strategy:
        - Each wire endpoint at a grid position defines a connection point
        - Labels at positions assign names to nets
        - Instance pins at positions connect to the net at that position
        - Unnamed nets get auto-assigned names (net0, net1, ...)
        - Multi-segment wires are split at intermediate points
        - T-junctions are detected where wire segments cross or meet
        """
        # Map from (x,y) position -> net name
        pos_to_net: dict[tuple[float, float], str] = {}

        # Union-Find for connecting wire endpoints
        parent: dict[tuple[float, float], tuple[float, float]] = {}

        def find(p):
            if p not in parent:
                parent[p] = p
            while parent[p] != p:
                parent[p] = parent[parent[p]]
                p = parent[p]
            return p

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        def snap(val, grid=10):
            return round(val / grid) * grid

        # Process wires — union their endpoints and intermediate points
        for w in data.get("wires", []):
            x1, y1 = snap(w["x1"]), snap(w["y1"])
            x2, y2 = snap(w["x2"]), snap(w["y2"])
            p1 = (x1, y1)
            p2 = (x2, y2)

            # For multi-segment wires, add intermediate points
            if x1 == x2:
                # Vertical wire
                step = 10 if y2 > y1 else -10
                y = y1
                while y != y2:
                    union((x1, y), (x1, y + step))
                    y += step
            elif y1 == y2:
                # Horizontal wire
                step = 10 if x2 > x1 else -10
                x = x1
                while x != x2:
                    union((x, y1), (x + step, y1))
                    x += step
            else:
                # Diagonal or L-shaped: union endpoints directly
                union(p1, p2)

            # If wire has a net name, record it
            if w.get("net"):
                root = find(p1)
                pos_to_net[root] = w["net"]

        # Detect T-junctions: where a wire crosses another wire's segment
        wire_segments = []
        for w in data.get("wires", []):
            x1, y1 = snap(w["x1"]), snap(w["y1"])
            x2, y2 = snap(w["x2"]), snap(w["y2"])
            wire_segments.append((x1, y1, x2, y2))

        for i, seg1 in enumerate(wire_segments):
            for j, seg2 in enumerate(wire_segments):
                if i >= j:
                    continue
                # Check for crossing points
                crossings = self._find_crossings(seg1, seg2)
                for cx, cy in crossings:
                    union((snap(cx), snap(cy)), (snap(cx), snap(cy)))

        # Process labels — assign net names
        for lbl in data.get("labels", []):
            pos = (snap(lbl["x"]), snap(lbl["y"]))
            root = find(pos)
            pos_to_net[root] = lbl["text"]

        # Process ground instances — assign net "0"
        for inst in data.get("instances", []):
            if inst.get("cell") == "gnd":
                pos = (snap(inst["x"]), snap(inst["y"]))
                gnd_pos = (pos[0], pos[1] - 10)
                root = find(gnd_pos)
                pos_to_net[root] = "0"
            elif inst.get("cell") == "vdd":
                pos = (snap(inst["x"]), snap(inst["y"]))
                vdd_pos = (pos[0], pos[1] + 10)
                root = find(vdd_pos)
                pos_to_net[root] = "VDD"

        # Build instance_pin -> net mapping
        pin_net_map: dict[str, str] = {}

        for inst in data.get("instances", []):
            iname = inst.get("name", "?")
            cell_name = inst.get("cell", "")
            ix, iy = snap(inst.get("x", 0)), snap(inst.get("y", 0))

            # Load symbol to get pin positions
            sym = self.db.load_view(
                inst.get("library", ""), cell_name, "symbol")
            if not sym:
                self._errors.append(
                    f"Cannot find symbol for {iname} ({cell_name})")
                continue

            for pin in sym.get("pins", []):
                pin_name = pin["name"]
                px = ix + snap(pin["x"])
                py = iy + snap(pin["y"])
                pos = (px, py)
                root = find(pos)

                # Get or assign net name
                if root in pos_to_net:
                    net_name = pos_to_net[root]
                else:
                    # Check if any equivalent position has a name
                    named = False
                    for p in parent:
                        if find(p) == root and p in pos_to_net:
                            net_name = pos_to_net[p]
                            pos_to_net[root] = net_name
                            named = True
                            break
                    if not named:
                        net_name = f"net{self._net_counter}"
                        self._net_counter += 1
                        pos_to_net[root] = net_name

                # Handle special global net pins
                if pin.get("net_name"):
                    net_name = pin["net_name"]

                pin_net_map[f"{iname}.{pin_name}"] = net_name

        return pin_net_map

    def _build_net_map_connectivity(self, data: dict) -> dict[str, str]:
        """Build net mapping using the ConnectivityEngine.

        This provides more robust wire topology handling than the legacy
        union-find approach, with proper junction/segment modeling.
        """
        # Initialize connectivity engine
        self._connectivity = ConnectivityEngine()

        # Build graph from schematic data
        self._connectivity.build_from_schematic(data)

        # Normalize wires (split/merge for proper topology)
        changes = self._connectivity.normalize_wires()
        if changes:
            self._warnings.extend([f"Wire normalization: {c}" for c in changes])

        # Add instance pins to the connectivity graph
        for inst in data.get("instances", []):
            iname = inst.get("name", "?")
            cell_name = inst.get("cell", "")
            lib_name = inst.get("library", "")
            ix = inst.get("x", 0)
            iy = inst.get("y", 0)

            # Skip special instances
            if cell_name in ("gnd", "vdd"):
                continue

            # Load symbol to get pin positions
            sym = self.db.load_view(lib_name, cell_name, "symbol")
            if sym:
                pins = sym.get("pins", [])
                self._connectivity.add_instance_pins(iname, lib_name, cell_name, ix, iy, pins)

        # Get net mapping from connectivity engine
        net_connections = self._connectivity.get_net_map()

        # Convert to instance.pin -> net name format
        pin_net_map: dict[str, str] = {}

        for net_name, connections in net_connections.items():
            for conn in connections:
                # connections are in "instance.pin" format
                if "." in conn:
                    pin_net_map[conn] = net_name
                else:
                    # Handle global nets like "0", "VDD"
                    pass

        # Also add any floating pins as warnings
        floating = self._connectivity.find_floating_pins()
        for fp in floating:
            self._warnings.append(
                f"Floating pin: {fp['instance']}.{fp['pin']} at ({fp['x']}, {fp['y']})"
            )

        # Check for net shorts
        shorts = self._connectivity.find_net_shorts()
        for s in shorts:
            self._warnings.append(
                f"Net short: {s['instance']}.{s['pin']} connected to multiple nets: {s['conflicting_nets']}"
            )

        # For any pins not in the connectivity map, assign auto-names
        # This handles cases where the connectivity might have missed something
        for inst in data.get("instances", []):
            if inst.get("cell") in ("gnd", "vdd"):
                continue

            iname = inst.get("name", "?")
            lib_name = inst.get("library", "")
            cell_name = inst.get("cell", "")

            sym = self.db.load_view(lib_name, cell_name, "symbol")
            if not sym:
                continue

            for pin in sym.get("pins", []):
                key = f"{iname}.{pin['name']}"
                if key not in pin_net_map:
                    # Assign auto-generated net name
                    pin_net_map[key] = f"net{self._net_counter}"
                    self._net_counter += 1

        return pin_net_map

    def _find_crossings(self, seg1: tuple, seg2: tuple) -> list[tuple[float, float]]:
        """Find crossing points between two wire segments."""
        x1, y1, x2, y2 = seg1
        x3, y3, x4, y4 = seg2
        crossings = []

        # Normalize segments
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1
        if x3 > x4:
            x3, x4 = x4, x3
        if y3 > y4:
            y3, y4 = y4, y3

        # Check if seg1 is horizontal and seg2 is vertical
        if y1 == y2 and x3 == x4:
            if x1 <= x3 <= x2 and y3 <= y1 <= y4:
                crossings.append((x3, y1))
        elif x1 == x2 and y3 == y4:
            if x3 <= x1 <= x4 and y1 <= y3 <= y2:
                crossings.append((x1, y3))

        return crossings

    # ── Instance Netlisting ───────────────────────────────────

    def _netlist_instances(self, data: dict,
                           net_map: dict[str, str]) -> list[str]:
        """Generate SPICE instance lines."""
        lines = []

        for inst in data.get("instances", []):
            iname = inst.get("name", "?")
            cell_name = inst.get("cell", "")
            lib_name = inst.get("library", "")
            params = inst.get("params", {})

            # Skip special instances (gnd, vdd)
            sym = self.db.load_view(lib_name, cell_name, "symbol")
            if not sym:
                continue
            spice_model = sym.get("spice_model", "")
            if spice_model in ("gnd", "vdd"):
                continue

            prefix = sym.get("prefix", "X")
            pin_order = [p["name"] for p in sym.get("pins", [])]

            # Collect net names in pin order
            nets = []
            for pname in pin_order:
                key = f"{iname}.{pname}"
                net = net_map.get(key, "?")
                nets.append(net)

            net_str = " ".join(nets)

            # Build SPICE line based on component type
            if spice_model == "R":
                val = params.get("R", "1k")
                lines.append(f"{iname} {net_str} {val}")
            elif spice_model == "C":
                val = params.get("C", "1p")
                lines.append(f"{iname} {net_str} {val}")
            elif spice_model == "L":
                val = params.get("L", "1n")
                lines.append(f"{iname} {net_str} {val}")
            elif spice_model == "V":
                dc = params.get("DC", "0")
                ac = params.get("AC", "")
                line = f"{iname} {net_str} DC {dc}"
                if ac:
                    line += f" AC {ac}"
                lines.append(line)
            elif spice_model == "I":
                dc = params.get("DC", "0")
                lines.append(f"{iname} {net_str} DC {dc}")
            elif spice_model == "D":
                model = params.get("model", "D1N4148")
                lines.append(f"{iname} {net_str} {model}")
            elif spice_model in ("nmos", "pmos"):
                model = params.get("model", "nch" if spice_model == "nmos" else "pch")
                w = params.get("W", "1u")
                l = params.get("L", "100n")
                nf = params.get("nf", "1")
                ad = params.get("AD", "")
                pd = params.get("PD", "")
                as_ = params.get("AS", "")
                ps = params.get("PS", "")
                line = f"{iname} {net_str} {model} W={w} L={l} nf={nf}"
                if ad:
                    line += f" AD={ad}"
                if pd:
                    line += f" PD={pd}"
                if as_:
                    line += f" AS={as_}"
                if ps:
                    line += f" PS={ps}"
                lines.append(line)
            elif spice_model == "E":
                # VCVS: Ename N+ N- NC+ NC- gain
                gain = params.get("gain", "1")
                ctrl_nets = nets[:2] if len(nets) >= 2 else nets
                out_nets = nets[2:] if len(nets) >= 4 else nets
                if len(out_nets) >= 2 and len(ctrl_nets) >= 2:
                    lines.append(f"{iname} {out_nets[0]} {out_nets[1]} {ctrl_nets[0]} {ctrl_nets[1]} {gain}")
                else:
                    lines.append(f"{iname} {net_str} {gain}")
            elif spice_model == "G":
                # VCCS: Gname N+ N- NC+ NC- gm
                gm = params.get("gm", "1")
                ctrl_nets = nets[:2] if len(nets) >= 2 else nets
                out_nets = nets[2:] if len(nets) >= 4 else nets
                if len(out_nets) >= 2 and len(ctrl_nets) >= 2:
                    lines.append(f"{iname} {out_nets[0]} {out_nets[1]} {ctrl_nets[0]} {ctrl_nets[1]} {gm}")
                else:
                    lines.append(f"{iname} {net_str} {gm}")
            elif spice_model == "F":
                # CCCS: Fname N+ N- Vsource gain
                gain = params.get("gain", "1")
                vsrc = params.get("vsource", "")
                if vsrc:
                    lines.append(f"{iname} {net_str} {vsrc} {gain}")
                else:
                    lines.append(f"{iname} {net_str} {gain}")
            elif spice_model == "H":
                # CCVS: Hname N+ N- Vsource gm
                gm = params.get("gm", "1")
                vsrc = params.get("vsource", "")
                if vsrc:
                    lines.append(f"{iname} {net_str} {vsrc} {gm}")
                else:
                    lines.append(f"{iname} {net_str} {gm}")
            elif spice_model == "Q":
                model = params.get("model", "NPN")
                area = params.get("area", "")
                if area:
                    lines.append(f"{iname} {net_str} {model} {area}")
                else:
                    lines.append(f"{iname} {net_str} {model}")
            else:
                # Generic subcircuit call with proper pin mapping
                param_str = " ".join(f"{k}={v}" for k, v in params.items())
                if param_str:
                    lines.append(f"{iname} {net_str} {cell_name} {param_str}")
                else:
                    lines.append(f"{iname} {net_str} {cell_name}")

        return lines
