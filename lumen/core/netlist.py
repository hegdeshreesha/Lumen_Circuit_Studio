"""
Lumen Circuit Studio — SPICE Netlist Generator

Traverses a schematic design hierarchy and produces a flat or
hierarchical SPICE netlist compatible with GSPICE, Ngspice, and Xyce.

Supports two connectivity models:
- Legacy union-find (for backward compatibility)
- ConnectivityEngine (new, explicit junction/segment graph)
"""
import os
import math
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Any
from lumen.core.database import LibraryDatabase
from lumen.core.connectivity import ConnectivityEngine
from lumen.core.component_validation import validate_symbol_params, parse_spice_number
from lumen.core.component_imports import validate_system_component
from lumen.core.component_capabilities import is_supported


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
        self._pdk_registry: Any = None
        self._target_simulator = "GSPICE"
        self._dynamic_includes: set[str] = set()
        self._custom_blocks: list[str] = []
        self._spfile_subckt_added = False
        self._model_bindings: dict[str, str] = {}

    def set_pdk_model(self, model_path: str, corner: str = ""):
        """Set PDK model file path and optional corner for .lib inclusion."""
        self._pdk_model_path = model_path
        self._pdk_corner = corner

    def set_use_connectivity(self, use: bool):
        """Enable/disable the new ConnectivityEngine."""
        self._use_connectivity = use

    def set_target_simulator(self, simulator: str):
        """Set target simulator for capability-aware netlisting."""
        self._target_simulator = str(simulator or "GSPICE").upper()

    def set_model_bindings(self, bindings: dict[str, str]):
        """Override instance model parameters for this generated deck only."""
        self._model_bindings = {
            str(inst): str(model)
            for inst, model in (bindings or {}).items()
            if str(inst).strip() and str(model).strip()
        }

    @staticmethod
    def _as_float(value: object, default: float = 0.0) -> float:
        """Best-effort float conversion for legacy/string schematic values."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

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
        self._dynamic_includes = set()
        self._custom_blocks = []
        self._spfile_subckt_added = False

        data = self.db.load_view(library, cell, view)
        if not data:
            return f"* ERROR: Cannot load {library}/{cell}/{view}\n"

        lines = []
        lines.append(f"* Lumen Circuit Studio — SPICE Netlist")
        lines.append(f"* Design: {library}/{cell}/{view}")
        lines.append(f"*")

        # PDK model includes
        initial_include_lines = self._generate_pdk_includes()
        lines.extend(initial_include_lines)

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
            pin_names = self._schematic_pin_names(data)
            port_str = " ".join(pin_names) if pin_names else ""
            lines.append(f".SUBCKT {cell} {port_str}")
            inst_lines = self._netlist_instances(data, net_map)
            lines.extend(f"  {l}" for l in inst_lines)
            lines.append(f".ENDS {cell}")

        include_seen = set(initial_include_lines)
        late_include_lines = [line for line in self._generate_pdk_includes() if line not in include_seen]
        if late_include_lines:
            lines.append("")
            lines.append("* Dynamic Includes")
            lines.extend(late_include_lines)

        if self._custom_blocks:
            lines.append("")
            lines.append("* Generated Helper Subcircuits")
            lines.extend(self._custom_blocks)

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

    def _add_dynamic_include(self, path: str):
        """Add a resolved include path once to directives."""
        if not path:
            return
        p = str(Path(path))
        if p in self._dynamic_includes:
            return
        self._dynamic_includes.add(p)
        self._directives.includes.append({"path": p})

    def _generate_pdk_includes(self) -> list[str]:
        """Generate .include and .lib directives for PDK model files."""
        lines = []
        for inc in self._directives.includes:
            if isinstance(inc, dict):
                path = inc.get("path", "")
            else:
                path = str(inc)
            if path:
                if path.lower().endswith(".gsdi"):
                    lines.append(f'.GSDI "{path}"')
                else:
                    lines.append(f'.INCLUDE "{path}"')
        for lib_entry in self._directives.libs:
            if isinstance(lib_entry, dict):
                path = lib_entry.get("path", "")
                section = lib_entry.get("section", "")
                if path and section:
                    lines.append(f".LIB \"{path}\" {section}")
                elif path:
                    lines.append(f".LIB \"{path}\"")
            elif isinstance(lib_entry, (tuple, list)):
                path = lib_entry[0] if len(lib_entry) > 0 else ""
                section = lib_entry[1] if len(lib_entry) > 1 else ""
                if path and section:
                    lines.append(f".LIB \"{path}\" {section}")
                elif path:
                    lines.append(f".LIB \"{path}\"")
            else:
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
        lines.extend(self._generate_child_subcircuits(data, set()))
        return lines

    def _generate_child_subcircuits(self, data: dict, seen: set[tuple[str, str]]) -> list[str]:
        """Emit schematic-backed child subcircuits needed by this schematic."""
        lines: list[str] = []
        for inst in data.get("instances", []):
            lib_name = inst.get("library", "")
            cell_name = inst.get("cell", "")
            key = (lib_name, cell_name)
            if key in seen or lib_name.startswith("pdk:"):
                continue
            child = self.db.load_view(lib_name, cell_name, "schematic")
            if not child:
                continue

            seen.add(key)
            lines.extend(self._generate_child_subcircuits(child, seen))

            pin_names = self._schematic_pin_names(child)
            port_str = " ".join(pin_names)
            subckt_name = self._subckt_model_name(lib_name, cell_name)
            child_net_map = self._build_net_map_connectivity(child) if self._use_connectivity else self._build_net_map(child)
            child_lines = self._netlist_instances(child, child_net_map)
            lines.append(f".SUBCKT {subckt_name}" + (f" {port_str}" if port_str else ""))
            lines.extend(f"  {line}" for line in child_lines)
            lines.append(f".ENDS {subckt_name}")
        return lines

    def _schematic_pin_names(self, data: dict) -> list[str]:
        names: list[str] = []
        for pin in data.get("pins", []):
            name = pin.get("name", "") if isinstance(pin, dict) else str(pin)
            name = str(name).strip()
            if name:
                names.append(name)
        return names

    def _subckt_model_name(self, library: str, cell: str) -> str:
        sym = self._get_symbol_or_generated(library, cell)
        if isinstance(sym, dict):
            model = str(sym.get("spice_model", "")).strip()
            if model:
                return model
        return cell

    def get_errors(self) -> list[str]:
        """Return any errors from the last netlist generation."""
        return list(self._errors)

    def get_warnings(self) -> list[str]:
        """Return any warnings from the last netlist generation."""
        warnings = list(self._warnings)
        if self._connectivity:
            warnings.extend(self._connectivity.get_warnings())
        return list(dict.fromkeys(warnings))

    def _get_pdk_registry(self):
        """Lazily create the unified PDK registry bound to this workspace."""
        if self._pdk_registry is not None:
            return self._pdk_registry
        try:
            from lumen.core.pdk_service import get_registry
            workspace = str(getattr(self.db, "workspace", ""))
            self._pdk_registry = get_registry(workspace)
        except Exception:
            self._pdk_registry = False
        return self._pdk_registry or None

    def _pdk_name_from_library(self, library: str) -> str:
        """Extract PDK name from a `pdk:<name>` virtual library string."""
        if not library or not library.startswith("pdk:"):
            return ""
        return library.split(":", 1)[1].strip()

    def _resolve_pdk_device(self, library: str, cell: str):
        """Resolve a PDK device for a virtual `pdk:<name>` library cell."""
        pdk_name = self._pdk_name_from_library(library)
        if not pdk_name:
            return None
        registry = self._get_pdk_registry()
        if not registry:
            return None

        device = registry.find_device(cell, pdk_name)
        if device:
            return device

        cell_lc = cell.lower()
        for dev in registry.get_devices(pdk_name):
            if dev.name.lower() == cell_lc:
                return dev
            if getattr(dev, "model", "").lower() == cell_lc:
                return dev
            if getattr(dev, "component_name", "").lower() == cell_lc:
                return dev
        return None

    def _get_symbol_or_generated(self, library: str, cell: str) -> Optional[dict]:
        """Load DB symbol; if missing for PDK cells, generate from PDK metadata."""
        sym = self.db.load_view(library, cell, "symbol")
        if sym:
            return sym

        pdk_name = self._pdk_name_from_library(library)
        if not pdk_name:
            return None

        device = self._resolve_pdk_device(library, cell)
        if not device:
            return None

        # Prefer cached symbol payload embedded in the device.
        sym_data = getattr(device, "symbol_data", None)
        if isinstance(sym_data, dict):
            return sym_data

        try:
            from lumen.core.pdk import generate_symbol_data
            return generate_symbol_data(device, pdk_name)
        except Exception as e:
            self._warnings.append(
                f"Failed to generate PDK symbol for {library}/{cell}: {e}"
            )
            return None

    def _pins_for_instance(self, library: str, cell: str) -> list[dict]:
        """Return symbol-style pin dictionaries for an instance."""
        sym = self._get_symbol_or_generated(library, cell)
        if sym and isinstance(sym.get("pins", []), list):
            out: list[dict] = []
            for idx, pin in enumerate(sym.get("pins", [])):
                rec = self._coerce_pin_record(pin, library, cell, idx)
                if rec is not None:
                    out.append(rec)
            return out

        dev = self._resolve_pdk_device(library, cell)
        if not dev:
            return []

        pins: list[dict] = []
        for idx, pin in enumerate(getattr(dev, "pins", [])):
            rec = self._coerce_pin_record(pin, library, cell, idx)
            if rec is not None:
                pins.append(rec)
        return pins

    def _coerce_pin_record(self, pin: Any, library: str, cell: str, index: int) -> Optional[dict]:
        """Normalize heterogeneous pin payloads into dict form."""
        if isinstance(pin, dict):
            name = str(pin.get("name", "")).strip()
            if not name:
                self._warnings.append(
                    f"Ignored unnamed pin #{index + 1} in {library}/{cell}."
                )
                return None
            return {
                "name": name,
                "x": pin.get("x", 0),
                "y": pin.get("y", 0),
                "net_name": pin.get("net_name"),
            }

        if isinstance(pin, str):
            name = pin.strip()
            if not name:
                self._warnings.append(
                    f"Ignored empty pin string #{index + 1} in {library}/{cell}."
                )
                return None
            return {"name": name, "x": 0, "y": 0, "net_name": None}

        name = str(getattr(pin, "name", "")).strip()
        if not name:
            self._warnings.append(
                f"Ignored unknown pin object #{index + 1} in {library}/{cell}."
            )
            return None
        return {
            "name": name,
            "x": getattr(pin, "x", 0),
            "y": getattr(pin, "y", 0),
            "net_name": getattr(pin, "net_name", None),
        }

    def _pdk_term_order(self, device: Any, fallback_pins: list[dict]) -> list[str]:
        """Resolve terminal order for netlisting, CDF-style."""
        order = list(getattr(device, "term_order", []) or [])
        if order:
            return order
        if fallback_pins:
            return [p.get("name", "") for p in fallback_pins if p.get("name", "")]
        return [
            getattr(p, "name", "")
            for p in getattr(device, "pins", [])
            if getattr(p, "name", "")
        ]

    def _pdk_param_string(self, device: Any, inst_params: dict) -> str:
        """Format instance parameters using CDF-like ordered lists."""
        if not isinstance(inst_params, dict):
            inst_params = {}

        defaults: dict[str, str] = {}
        for p in getattr(device, "parameters", []) or []:
            if isinstance(p, dict):
                n = p.get("name")
                if n:
                    defaults[str(n)] = str(p.get("default", ""))
            else:
                n = getattr(p, "name", "")
                if n:
                    defaults[str(n)] = str(getattr(p, "default", ""))

        ordered = list(getattr(device, "inst_parameters", []) or defaults.keys())
        optional = list(getattr(device, "other_parameters", []) or [])

        parts: list[str] = []
        emitted: set[str] = set()

        aliases = {
            "w": ["W", "width"],
            "l": ["L", "length"],
            "ng": ["ng", "nf", "NF"],
            "m": ["m", "mult", "MULT"],
        }

        def get_param_value(name: str):
            for candidate in [name] + aliases.get(name, []):
                if candidate in inst_params:
                    return inst_params.get(candidate)
                for key, val in inst_params.items():
                    if key.lower() == candidate.lower():
                        return val
            if name in defaults:
                return defaults[name]
            for key, val in defaults.items():
                if key.lower() == name.lower():
                    return val
            return ""

        for name in ordered + optional:
            if name in emitted:
                continue
            val = get_param_value(name)
            if val not in ("", None):
                parts.append(f"{name}={val}")
                emitted.add(name)

        for key, val in inst_params.items():
            consumed = False
            for emitted_name in emitted:
                alias_names = [emitted_name] + aliases.get(emitted_name, [])
                if any(key.lower() == alias.lower() for alias in alias_names):
                    consumed = True
                    break
            if consumed or key in emitted:
                continue
            if val in ("", None):
                continue
            parts.append(f"{key}={val}")
            emitted.add(key)

        return " ".join(parts)

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
            v = self._as_float(val, 0.0)
            g = self._as_float(grid, 10.0) or 10.0
            return int(round(v / g) * g)

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

        for pin in data.get("pins", []):
            pos = (snap(pin["x"]), snap(pin["y"]))
            root = find(pos)
            pos_to_net[root] = pin.get("name", "")

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
            lib_name = inst.get("library", "")
            ix, iy = snap(inst.get("x", 0)), snap(inst.get("y", 0))
            rotation = self._as_float(inst.get("rotation", inst.get("rot", 0)), 0.0)
            transform = inst.get("transform")

            pins = self._pins_for_instance(lib_name, cell_name)
            if not pins:
                self._errors.append(
                    f"Cannot find symbol/pins for {iname} ({lib_name}/{cell_name})"
                )
                continue

            for pin in pins:
                pin_name = pin["name"]
                px, py = self._pin_scene_position(ix, iy, pin, rotation, transform)
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
            ix = self._as_float(inst.get("x", 0), 0.0)
            iy = self._as_float(inst.get("y", 0), 0.0)

            # Skip special instances
            if cell_name in ("gnd", "vdd"):
                continue

            pins = self._pins_for_instance(lib_name, cell_name)
            if pins:
                self._connectivity.add_instance_pins(
                    iname,
                    lib_name,
                    cell_name,
                    ix,
                    iy,
                    pins,
                    self._as_float(inst.get("rotation", inst.get("rot", 0)), 0.0),
                    inst.get("transform"),
                )

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

            pins = self._pins_for_instance(lib_name, cell_name)
            if not pins:
                continue

            for pin in pins:
                key = f"{iname}.{pin['name']}"
                if key not in pin_net_map:
                    # Assign auto-generated net name
                    pin_net_map[key] = f"net{self._net_counter}"
                    self._net_counter += 1

        return pin_net_map

    @staticmethod
    def _pin_scene_position(x: float, y: float, pin: dict,
                            rotation: float = 0,
                            transform: dict | None = None) -> tuple[int, int]:
        """Resolve a symbol-local pin through instance mirror/rotation/translation."""
        px = NetlistGenerator._as_float(pin.get("x", 0), 0.0)
        py = NetlistGenerator._as_float(pin.get("y", 0), 0.0)

        if transform:
            m11 = NetlistGenerator._as_float(transform.get("m11", 1), 1.0)
            m12 = NetlistGenerator._as_float(transform.get("m12", 0), 0.0)
            m21 = NetlistGenerator._as_float(transform.get("m21", 0), 0.0)
            m22 = NetlistGenerator._as_float(transform.get("m22", 1), 1.0)
            dx = NetlistGenerator._as_float(transform.get("dx", 0), 0.0)
            dy = NetlistGenerator._as_float(transform.get("dy", 0), 0.0)
            px, py = (m11 * px) + (m21 * py) + dx, (m12 * px) + (m22 * py) + dy

        if rotation:
            theta = math.radians(NetlistGenerator._as_float(rotation, 0.0))
            c = math.cos(theta)
            s = math.sin(theta)
            px, py = (c * px) - (s * py), (s * px) + (c * py)

        return round(NetlistGenerator._as_float(x, 0.0) + px), round(NetlistGenerator._as_float(y, 0.0) + py)

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
            params = dict(inst.get("params", {}) or {})
            if iname in self._model_bindings:
                params["model"] = self._model_bindings[iname]

            sym = self._get_symbol_or_generated(lib_name, cell_name)
            pdk_device = self._resolve_pdk_device(lib_name, cell_name)

            # PDK/CDF-style path: netlist directly from unified device metadata.
            if pdk_device:
                pins = self._pins_for_instance(lib_name, cell_name)
                pin_order = self._pdk_term_order(pdk_device, pins)
                if not pin_order:
                    self._warnings.append(
                        f"Skipping {iname}: no terminal order for {lib_name}/{cell_name}"
                    )
                    continue

                nets = []
                for pname in pin_order:
                    key = f"{iname}.{pname}"
                    nets.append(net_map.get(key, "?"))

                component_name = (
                    getattr(pdk_device, "component_name", "")
                    or getattr(pdk_device, "model", "")
                    or cell_name
                )
                if component_name in ("gnd", "vdd", "0", "VDD"):
                    continue

                nets = self._tie_floating_ihp_mos_bulk_to_source(component_name, pin_order, nets, iname)
                net_str = " ".join(nets)
                param_str = self._pdk_param_string(pdk_device, params)
                prefix = getattr(pdk_device, "prefix", "") or ""
                full_name = iname
                if prefix and not iname.upper().startswith(prefix.upper()):
                    full_name = f"{prefix}{iname}"
                line = f"{full_name} {net_str} {component_name}"
                if param_str:
                    line += f" {param_str}"
                lines.append(line)
                continue

            # Skip special instances (gnd, vdd)
            if not sym:
                self._warnings.append(
                    f"Skipping {iname}: missing symbol {lib_name}/{cell_name}"
                )
                continue
            spice_model = sym.get("spice_model", "")
            supported, reason = is_supported(spice_model, self._target_simulator)
            if not supported:
                self._errors.append(f"{iname} ({cell_name}): {reason}")
                continue

            validation = validate_symbol_params(sym, params, iname)
            self._warnings.extend(validation.warnings)
            self._errors.extend(validation.errors)
            if validation.errors:
                continue

            import_check = validate_system_component(
                spice_model,
                params,
                str(getattr(self.db, "workspace", "")),
            )
            resolved_import_path = ""
            if import_check is not None:
                if not import_check.ok:
                    self._errors.extend(f"{iname}: {msg}" for msg in import_check.errors)
                    continue
                if import_check.resolved_path:
                    resolved_import_path = import_check.resolved_path
                    if str(spice_model).upper() not in ("SPFILE",):
                        self._add_dynamic_include(import_check.resolved_path)

            if spice_model in ("gnd", "vdd", "vss", "port", "no_conn"):
                continue

            prefix = sym.get("prefix", "X")
            pin_order = self._extract_pin_order(sym, iname, lib_name, cell_name)
            if not pin_order:
                self._warnings.append(
                    f"Skipping {iname}: symbol {lib_name}/{cell_name} has no valid pin names."
                )
                continue

            # Collect net names in pin order
            nets = []
            for pname in pin_order:
                key = f"{iname}.{pname}"
                net = net_map.get(key, "?")
                nets.append(net)

            net_str = " ".join(nets)

            def _param_first(*keys: str, default: str = ""):
                """Get first non-empty parameter by key, case-insensitive."""
                for key in keys:
                    if key in params:
                        value = params.get(key)
                        if value not in ("", None):
                            return value
                lowered = {str(k).lower(): v for k, v in params.items()}
                for key in keys:
                    value = lowered.get(str(key).lower(), None)
                    if value not in ("", None):
                        return value
                return default

            def _with_ac(line: str, default: str = "", legacy_phase: bool = False) -> str:
                ac = _param_first("acmag", "AC", default=default)
                if not ac:
                    return line
                phase_keys = ("acphase", "phase") if legacy_phase else ("acphase",)
                phase = _param_first(*phase_keys, default="")
                line += f" AC {ac}"
                if phase:
                    line += f" {phase}"
                return line

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
                dc = _param_first("dc", "DC", default="0")
                line = f"{iname} {net_str} DC {dc}"
                lines.append(_with_ac(line, legacy_phase=True))
            elif spice_model == "I":
                dc = _param_first("dc", "DC", default="0")
                line = f"{iname} {net_str} DC {dc}"
                lines.append(_with_ac(line, legacy_phase=True))
            elif spice_model in ("VDC", "IDC"):
                dc = _param_first("dc", "DC", default="0")
                lines.append(_with_ac(f"{iname} {net_str} DC {dc}"))
            elif spice_model in ("VAC", "IAC"):
                dc = _param_first("dc", "DC", default="0")
                lines.append(_with_ac(f"{iname} {net_str} DC {dc}", default="1"))
            elif spice_model == "PAC":
                lines.extend(self._emit_pac_source(iname, nets, params))
            elif spice_model in ("VPULSE", "IPULSE"):
                dc = _param_first("dc", "DC", default="0")
                args = [
                    params.get("v1", "0"),
                    params.get("v2", "1"),
                    params.get("td", "0"),
                    params.get("tr", "1n"),
                    params.get("tf", "1n"),
                    params.get("pw", "5n"),
                    params.get("per", "10n"),
                ]
                line = f"{iname} {net_str} DC {dc} PULSE({' '.join(args)})"
                lines.append(_with_ac(line))
            elif spice_model in ("VSIN", "ISIN"):
                dc = _param_first("dc", "DC", default="0")
                args = [
                    params.get("vo", "0"),
                    params.get("va", "1"),
                    params.get("freq", "1k"),
                    params.get("td", "0"),
                    params.get("theta", "0"),
                    params.get("phase", "0"),
                ]
                line = f"{iname} {net_str} DC {dc} SIN({' '.join(args)})"
                lines.append(_with_ac(line))
            elif spice_model in ("VPWL", "IPWL"):
                dc = _param_first("dc", "DC", default="0")
                points = params.get("points", "0 0 1n 1")
                line = f"{iname} {net_str} DC {dc} PWL({points})"
                lines.append(_with_ac(line))
            elif spice_model in ("VAM", "VPM"):
                uo = params.get("Uo", "0")
                uac = params.get("Uac", "1")
                fm = params.get("fm", "1k")
                fc = params.get("fc", params.get("freq", "1M"))
                if spice_model == "VAM":
                    line = f"{iname} {net_str} AM({uo} {uac} {fm} {fc})"
                else:
                    line = f"{iname} {net_str} PM({uo} {uac} {fm} {fc})"
                lines.append(line)
            elif spice_model in ("VNOISE", "INOISE"):
                density = params.get("En", params.get("In", "1n"))
                src_prefix = "V" if spice_model == "VNOISE" else "I"
                line = f"{iname} {net_str} DC 0 AC 0"
                lines.append(f"* {iname}: {src_prefix} noise density parameter {density}")
                lines.append(line)
            elif spice_model in ("DIGI_SOURCE",):
                # Analogized digital source for mixed-signal compatibility.
                init = str(params.get("init", "low")).lower()
                vhi = params.get("V", "1")
                vlo = params.get("VLO", "0")
                td = params.get("td", "1n")
                tr = params.get("tr", "100p")
                tf = params.get("tf", "100p")
                pw = params.get("pw", "1n")
                per = params.get("per", "2n")
                v1 = vlo if init in ("0", "low", "false") else vhi
                v2 = vhi if init in ("0", "low", "false") else vlo
                lines.append(f"{iname} {net_str} PULSE({v1} {v2} {td} {tr} {tf} {pw} {per})")
            elif spice_model == "IPROBE":
                lines.append(f"{iname} {net_str} DC 0")
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
            elif spice_model in ("nmos3", "pmos3"):
                model = params.get("model", "nch" if spice_model == "nmos3" else "pch")
                w = params.get("W", "1u")
                l = params.get("L", "100n")
                nf = params.get("nf", "1")
                if len(nets) >= 3:
                    d, g, s = nets[:3]
                    lines.append(f"{iname} {d} {g} {s} {s} {model} W={w} L={l} nf={nf}")
                else:
                    lines.append(f"{iname} {net_str} {model} W={w} L={l} nf={nf}")
            elif spice_model == "E":
                # VCVS: Ename N+ N- NC+ NC- gain
                gain = params.get("gain", "1")
                if len(nets) >= 4:
                    lines.append(f"{iname} {nets[0]} {nets[1]} {nets[2]} {nets[3]} {gain}")
                else:
                    lines.append(f"{iname} {net_str} {gain}")
            elif spice_model == "G":
                # VCCS: Gname N+ N- NC+ NC- gm
                gm = params.get("gm", "1")
                if len(nets) >= 4:
                    lines.append(f"{iname} {nets[0]} {nets[1]} {nets[2]} {nets[3]} {gm}")
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
                # CCVS: Hname N+ N- Vsource transresistance
                rm = params.get("rm", params.get("gm", "1"))
                vsrc = params.get("vsource", "")
                if vsrc:
                    lines.append(f"{iname} {net_str} {vsrc} {rm}")
                else:
                    lines.append(f"{iname} {net_str} {rm}")
            elif spice_model == "Q":
                model = params.get("model", "NPN")
                area = params.get("area", "")
                if area:
                    lines.append(f"{iname} {net_str} {model} {area}")
                else:
                    lines.append(f"{iname} {net_str} {model}")
            elif spice_model in ("J", "Z"):
                model = params.get("model", "NJF")
                area = params.get("area", "")
                if area:
                    lines.append(f"{iname} {net_str} {model} {area}")
                else:
                    lines.append(f"{iname} {net_str} {model}")
            elif spice_model == "S":
                model = params.get("model", "SW")
                lines.append(f"{iname} {net_str} {model}")
            elif spice_model == "W":
                vsrc = params.get("vsource", "V0")
                model = params.get("model", "CSW")
                lines.append(f"{iname} {net_str} {vsrc} {model}")
            elif spice_model == "T":
                z0 = params.get("Z0", "50")
                td = params.get("TD", "1n")
                lines.append(f"{iname} {net_str} Z0={z0} TD={td}")
            elif spice_model == "K":
                l1 = params.get("L1", "L0")
                l2 = params.get("L2", "L1")
                k = params.get("K", "0.99")
                lines.append(f"{iname} {l1} {l2} {k}")
            elif spice_model == "BV":
                expr = params.get("expr", "0")
                lines.append(f"{iname} {net_str} V={expr}")
            elif spice_model == "BI":
                expr = params.get("expr", "0")
                lines.append(f"{iname} {net_str} I={expr}")
            elif spice_model in ("OR", "NOR", "AND", "NAND", "XOR", "XNOR", "INV", "BUF", "LOGIC0", "LOGIC1"):
                lines.extend(self._emit_digital_behavioral(iname, spice_model, pin_order, nets, params))
            elif spice_model in ("SPFILE",):
                lines.extend(self._emit_spfile_instance(iname, nets, params, resolved_import_path))
            elif spice_model in ("SPICE_NETLIST", "SUB_FILE"):
                lines.append(f"* {iname}: external subcircuit from file {params.get('File', '')}")
                lines.append(f"{iname} {net_str} {cell_name}")
            elif spice_model in ("VHDL_FILE", "VERILOG_FILE"):
                lines.append(f"* {iname}: HDL co-sim placeholder ({spice_model}) file={params.get('File', '')}")
                lines.append(f"{iname} {net_str} {cell_name}")
            elif str(spice_model).upper().endswith("_VA"):
                model_file = params.get("ModelFile", "")
                if model_file:
                    from lumen.core.component_imports import validate_component_file
                    chk = validate_component_file(
                        str(model_file),
                        str(getattr(self.db, "workspace", "")),
                        (".so", ".dll"),
                    )
                    if not chk.ok:
                        self._errors.extend(f"{iname}: {msg}" for msg in chk.errors)
                        continue
                    if chk.resolved_path:
                        self._add_dynamic_include(chk.resolved_path)
                param_str = " ".join(f"{k}={v}" for k, v in params.items() if k != "ModelFile")
                if param_str:
                    lines.append(f"{iname} {net_str} {spice_model} {param_str}")
                else:
                    lines.append(f"{iname} {net_str} {spice_model}")
            else:
                # Generic subcircuit call with proper pin mapping
                param_str = " ".join(f"{k}={v}" for k, v in params.items())
                model_name = spice_model or cell_name
                if param_str:
                    lines.append(f"{iname} {net_str} {model_name} {param_str}")
                else:
                    lines.append(f"{iname} {net_str} {model_name}")

        return lines

    def _tie_floating_ihp_mos_bulk_to_source(
        self,
        component_name: str,
        pin_order: list[str],
        nets: list[str],
        instance_name: str,
    ) -> list[str]:
        model = str(component_name or "").lower()
        if not (model.startswith("sg13_") and ("nmos" in model or "pmos" in model)):
            return nets
        lower_pins = [str(pin).lower() for pin in pin_order]
        try:
            source_idx = lower_pins.index("s")
            bulk_idx = lower_pins.index("b")
        except ValueError:
            return nets
        if source_idx >= len(nets) or bulk_idx >= len(nets):
            return nets
        bulk_net = str(nets[bulk_idx])
        if re.fullmatch(r"net\d+", bulk_net) and nets.count(bulk_net) == 1:
            fixed = list(nets)
            fixed[bulk_idx] = fixed[source_idx]
            self._warnings.append(
                f"{instance_name}: tied anonymous IHP MOS bulk net {bulk_net} to source {fixed[source_idx]}."
            )
            return fixed
        return nets

    def _parse_dbm(self, raw: Any, default_dbm: float = 0.0) -> float:
        text = str(raw if raw is not None else "").strip()
        if not text:
            return default_dbm
        low = text.lower()
        if low.endswith("dbm"):
            try:
                return float(low[:-3].strip())
            except ValueError:
                return default_dbm
        try:
            return float(parse_spice_number(text))
        except Exception:
            return default_dbm

    def _extract_pin_order(self, sym: dict, iname: str, lib_name: str, cell_name: str) -> list[str]:
        """Extract pin order robustly from symbol data.

        Imported or user-edited symbols may carry mixed pin encodings.
        """
        pins = sym.get("pins", []) if isinstance(sym, dict) else []
        out: list[str] = []
        for idx, pin in enumerate(pins):
            pname = ""
            if isinstance(pin, dict):
                pname = str(pin.get("name", "")).strip()
            elif isinstance(pin, str):
                pname = pin.strip()
            else:
                pname = str(getattr(pin, "name", "")).strip()
            if not pname:
                self._warnings.append(
                    f"{iname}: ignored unnamed pin #{idx + 1} in {lib_name}/{cell_name}."
                )
                continue
            out.append(pname)
        return out

    def _emit_pac_source(self, iname: str, nets: list[str], params: dict) -> list[str]:
        """Emit QUCS-style AC power source as a Norton equivalent."""
        if len(nets) < 2:
            self._errors.append(f"{iname}: PAC requires two terminals (PLUS/MINUS).")
            return []

        z_raw = params.get("Z", params.get("Z0", "50"))
        try:
            z_ohm = float(parse_spice_number(z_raw))
        except Exception:
            z_ohm = 50.0
            self._warnings.append(f"{iname}: invalid PAC impedance '{z_raw}', defaulting to 50 ohm.")
        z_ohm = max(z_ohm, 1e-12)

        p_dbm = self._parse_dbm(params.get("P", "0dBm"), 0.0)
        p_watt = 1e-3 * pow(10.0, p_dbm / 10.0)
        i_ac = math.sqrt(max(0.0, 8.0 * p_watt / z_ohm))
        phase = str(params.get("phase", "")).strip()

        n_plus, n_minus = nets[0], nets[1]
        lines = [
            f"* {iname}: PAC Norton equivalent (P={p_dbm} dBm, Z={z_ohm} ohm)",
            f"G{iname}_PAC {n_plus} {n_minus} {n_plus} {n_minus} {1.0 / z_ohm}",
        ]
        src = f"I{iname}_PAC {n_plus} {n_minus} DC 0 AC {i_ac:.9g}"
        if phase:
            src += f" {phase}"
        lines.append(src)
        return lines

    def _normalize_touchstone_path(self, path: str) -> str:
        return str(path or "").strip().replace("\\", "/").lower()

    def _emit_spfile_instance(self, iname: str, nets: list[str], params: dict, resolved_path: str) -> list[str]:
        """Emit S-parameter file component netlist lines."""
        if len(nets) < 2:
            self._errors.append(f"{iname}: SPFILE requires two pins (P1/P2).")
            return []

        file_param = str(params.get("File", "")).strip()
        file_path = self._normalize_touchstone_path(resolved_path or file_param)
        zref = params.get("Zref", params.get("Z", "50"))
        n1, n2 = nets[0], nets[1]

        if self._target_simulator == "NGSPICE":
            subckt_name = "LUMEN_S2P_GENERIC"
            if not self._spfile_subckt_added:
                self._custom_blocks.extend([
                    f".SUBCKT {subckt_name} 1 2 3 touchstone={{touchstone}} zref=50",
                    "R1N 1 100 {-zref}",
                    "R1P 100 101 {2*zref}",
                    "R2N 2 200 {-zref}",
                    "R2P 200 201 {2*zref}",
                    "A0101 %vd 100 3 %vd 101 102 m_a0101",
                    ".model m_a0101 xfer file=touchstone span=9",
                    "A0102 %vd 200 3 %vd 102 3 m_a0102",
                    ".model m_a0102 xfer file=touchstone span=9 offset=3",
                    "A0201 %vd 100 3 %vd 201 202 m_a0201",
                    ".model m_a0201 xfer file=touchstone span=9 offset=5",
                    "A0202 %vd 200 3 %vd 202 3 m_a0202",
                    ".model m_a0202 xfer file=touchstone span=9 offset=7",
                    f".ENDS {subckt_name}",
                ])
                self._spfile_subckt_added = True
            return [
                f"* {iname}: SPFILE touchstone={file_path}",
                f"X{iname}_SP {n1} {n2} 0 {subckt_name} touchstone=\"{file_path}\" zref={zref}",
            ]

        self._warnings.append(
            f"{iname}: SPFILE full xfer model available in Ngspice; "
            f"using passive fallback for {self._target_simulator}."
        )
        return [
            f"* {iname}: SPFILE fallback for {self._target_simulator} file={file_path}",
            f"R{iname}_SP {n1} {n2} {zref}",
        ]

    def _emit_digital_behavioral(self, iname: str, spice_model: str,
                                 pin_order: list[str], nets: list[str],
                                 params: dict) -> list[str]:
        """Emit simple analog behavioral approximations for digital primitives."""
        mapping = {pin_order[i]: nets[i] for i in range(min(len(pin_order), len(nets)))}
        vhi = params.get("VHI", "1")
        vlo = params.get("VLO", "0")
        th = params.get("TH", "0.5")
        lines: list[str] = []

        def lv(net: str) -> str:
            return f"(V({net})>{th})"

        if spice_model == "LOGIC0":
            y = mapping.get("Y", mapping.get("OUT", nets[0] if nets else "0"))
            lines.append(f"V{iname}_const {y} 0 DC {vlo}")
            return lines
        if spice_model == "LOGIC1":
            y = mapping.get("Y", mapping.get("OUT", nets[0] if nets else "0"))
            lines.append(f"V{iname}_const {y} 0 DC {vhi}")
            return lines

        if spice_model in ("INV", "BUF"):
            a = mapping.get("A", mapping.get("IN", "0"))
            y = mapping.get("Y", mapping.get("OUT", "0"))
            expr = f"{vhi}*({lv(a)})"
            if spice_model == "INV":
                expr = f"{vhi}*(1-({lv(a)}))"
            lines.append(f"B{iname} {y} 0 V={expr}")
            return lines

        a = mapping.get("A", "0")
        b = mapping.get("B", "0")
        y = mapping.get("Y", mapping.get("OUT", "0"))
        if spice_model == "AND":
            cond = f"({lv(a)}&&{lv(b)})"
        elif spice_model == "NAND":
            cond = f"!( {lv(a)}&&{lv(b)} )"
        elif spice_model == "OR":
            cond = f"({lv(a)}||{lv(b)})"
        elif spice_model == "NOR":
            cond = f"!( {lv(a)}||{lv(b)} )"
        elif spice_model == "XOR":
            cond = f"(({lv(a)})!=({lv(b)}))"
        else:  # XNOR
            cond = f"(({lv(a)})==({lv(b)}))"
        lines.append(f"B{iname} {y} 0 V=({vhi})*({cond})")
        return lines
