"""
Lumen Circuit Studio — Hierarchy Engine

Design hierarchy management with:
- Cell instance tree (parent/child traversal)
- Parameter propagation through hierarchy
- Push/pop navigation data structures
- Cross-probing (click instance -> open child schematic)
- Flat vs hierarchical netlist control
- Missing cell detection
"""
from dataclasses import dataclass, field
from typing import Optional, Callable
from collections import defaultdict

from lumen.core.database import LibraryDatabase


@dataclass
class InstanceRef:
    """A reference to a cell instance in a design."""
    library: str
    cell: str
    instance_name: str                      # e.g., "M1", "R0"
    view: str = "schematic"
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    parameters: dict = field(default_factory=dict)


@dataclass
class HierarchyNode:
    """A node in the design hierarchy tree."""
    library: str
    cell: str
    view: str = "schematic"
    parent: Optional["HierarchyNode"] = None
    instance_name: str = ""                  # Name of this instance in parent
    instances: list[InstanceRef] = field(default_factory=list)
    children: list["HierarchyNode"] = field(default_factory=list)
    depth: int = 0

    @property
    def path(self) -> str:
        """Get the hierarchical path: top/cell/instance ..."""
        if self.parent and self.instance_name:
            return f"{self.parent.path}/{self.instance_name}"
        return f"{self.library}/{self.cell}"

    def find_instance(self, cell_name: str) -> Optional["HierarchyNode"]:
        """Find an instance by cell name in subtree."""
        for child in self.children:
            if child.cell == cell_name:
                return child
            found = child.find_instance(cell_name)
            if found:
                return found
        return None

    def find_by_path(self, path: str) -> Optional["HierarchyNode"]:
        """Find a node by its hierarchical path."""
        if self.path == path:
            return self
        for child in self.children:
            found = child.find_by_path(path)
            if found:
                return found
        return None

    def all_children(self) -> list["HierarchyNode"]:
        """Recursively get all children."""
        result: list[HierarchyNode] = []
        for child in self.children:
            result.append(child)
            result.extend(child.all_children())
        return result

    def get_leaf_cells(self) -> list["HierarchyNode"]:
        """Get all leaf nodes (cells with no children or primitives)."""
        if not self.children:
            return [self]
        result = []
        for child in self.children:
            result.extend(child.get_leaf_cells())
        return result

    def depth_first(self) -> list["HierarchyNode"]:
        """Depth-first traversal of the hierarchy."""
        result = [self]
        for child in self.children:
            result.extend(child.depth_first())
        return result


class HierarchyEngine:
    """
    Builds and traverses the design hierarchy tree.
    
    Usage:
        engine = HierarchyEngine(db)
        root = engine.build_hierarchy("my_lib", "amp")
        for node in root.depth_first():
            print(node.path)
    """

    # Cells that are primitives (no sub-hierarchy)
    PRIMITIVE_CELLS = {
        "res", "cap", "ind", "vsource", "isource", "gnd", "vdd",
        "nmos", "pmos", "diode", "npn", "pnp", "switch",
    }

    def __init__(self, db: LibraryDatabase):
        self.db = db
        self._missing_cells: list[dict] = []
        self._visited: set[tuple[str, str, str]] = set()
        self._max_depth = 50  # Safety limit

    def build_hierarchy(self, library: str, cell: str,
                        view: str = "schematic") -> Optional[HierarchyNode]:
        """
        Build the complete hierarchy tree for a given cell.
        
        Args:
            library: Library name
            cell: Cell name
            view: View to traverse (usually "schematic")
            
        Returns:
            Root HierarchyNode, or None if cell/view not found.
        """
        self._missing_cells = []
        self._visited.clear()

        root = HierarchyNode(
            library=library,
            cell=cell,
            view=view,
            depth=0,
        )

        self._build_node(root, 0)
        return root

    def _build_node(self, node: HierarchyNode, depth: int):
        """Recursively build hierarchy for a node."""
        if depth > self._max_depth:
            return

        visit_key = (node.library, node.cell, node.view)
        if visit_key in self._visited:
            return  # Prevent infinite recursion
        self._visited.add(visit_key)

        # Load schematic data
        data = self.db.load_view(node.library, node.cell, node.view)
        if not data:
            return

        # Process instances
        for inst in data.get("instances", []):
            inst_lib = inst.get("library", "")
            inst_cell = inst.get("cell", "")
            inst_name = inst.get("name", "?")
            inst_view = "schematic"

            ref = InstanceRef(
                library=inst_lib,
                cell=inst_cell,
                instance_name=inst_name,
                view=inst_view,
                x=inst.get("x", 0),
                y=inst.get("y", 0),
                rotation=inst.get("rotation", 0),
                parameters=dict(inst.get("params", {})),
            )
            node.instances.append(ref)

            # Skip primitives
            if self._is_primitive(inst_cell) or inst_cell in ("gnd", "vdd"):
                continue

            # Skip PDK library cells (they're primitives too)
            if inst_lib.startswith("pdk:"):
                continue

            # Check if this cell has a schematic view
            if self.db.view_exists(inst_lib, inst_cell, "schematic"):
                child = HierarchyNode(
                    library=inst_lib,
                    cell=inst_cell,
                    view="schematic",
                    parent=node,
                    instance_name=inst_name,
                    depth=depth + 1,
                )
                node.children.append(child)
                self._build_node(child, depth + 1)
            else:
                # Check for symbol view (for PDK cells referenced by name)
                if self.db.view_exists(inst_lib, inst_cell, "symbol"):
                    # It's a leaf cell with just a symbol
                    pass
                else:
                    self._missing_cells.append({
                        "library": inst_lib,
                        "cell": inst_cell,
                        "instance": inst_name,
                        "parent": f"{node.library}/{node.cell}",
                    })

    def _is_primitive(self, cell_name: str) -> bool:
        """Check if a cell is a primitive (no sub-hierarchy)."""
        return cell_name.lower() in self.PRIMITIVE_CELLS

    def get_missing_cells(self) -> list[dict]:
        """Get list of cells referenced but not found."""
        return list(self._missing_cells)

    def get_hierarchy_summary(self, node: HierarchyNode) -> str:
        """Get a human-readable hierarchy summary."""
        lines = []
        self._format_node(node, lines, 0)
        return "\n".join(lines)

    def _format_node(self, node: HierarchyNode, lines: list[str], indent: int):
        prefix = "  " * indent
        if indent == 0:
            lines.append(f"{prefix}{node.cell} [{node.library}]")
        else:
            lines.append(f"{prefix}{node.instance_name} -> {node.cell} [{node.library}]")
        for child in node.children:
            self._format_node(child, lines, indent + 1)

    def get_total_instances(self, node: HierarchyNode) -> int:
        """Count total instances (flattened) in the hierarchy."""
        count = len(node.instances)
        for child in node.children:
            count += self.get_total_instances(child)
        return count

    def get_unique_cells(self, node: HierarchyNode) -> set[tuple[str, str]]:
        """Get all unique (library, cell) pairs in the hierarchy."""
        cells = {(node.library, node.cell)}
        for ref in node.instances:
            cells.add((ref.library, ref.cell))
        for child in node.children:
            cells.update(self.get_unique_cells(child))
        return cells

    def get_instance_path_map(self, node: HierarchyNode) -> dict[str, HierarchyNode]:
        """Build a map of instance name -> HierarchyNode for cross-probing."""
        path_map = {}
        for child in node.depth_first():
            if child.instance_name:
                path_map[child.instance_name] = child
        return path_map

    def get_parameter_propagation(self, node: HierarchyNode) -> dict[str, dict]:
        """
        Get parameter propagation through hierarchy.
        
        Returns:
            Dict of instance_path -> {param_name: value} with inherited values.
        """
        params_map = {}

        def _propagate(n: HierarchyNode, parent_params: dict):
            # Merge instance parameters with inherited
            instance_params = {}
            for ref in n.instances:
                instance_params.update(ref.parameters)

            # Inherited parameters override at deeper levels
            effective_params = dict(parent_params)
            effective_params.update(instance_params)

            params_map[n.path] = effective_params

            for child in n.children:
                _propagate(child, effective_params)

        _propagate(node, {})
        return params_map


# ── Cross-Probing ─────────────────────────────────────────────

class CrossProbeManager:
    """Manages cross-probing between schematic instances and hierarchy."""

    def __init__(self, engine: HierarchyEngine):
        self.engine = engine
        self._root: Optional[HierarchyNode] = None
        self._on_navigate: Optional[Callable] = None  # Callback: (library, cell, view) -> None

    def set_root(self, node: HierarchyNode):
        self._root = node

    def set_navigate_callback(self, callback: Callable):
        """Set callback fired when user navigates to a cell."""
        self._on_navigate = callback

    def push_down(self, instance_name: str) -> bool:
        """Navigate into an instance (push down hierarchy)."""
        if not self._root:
            return False

        for node in self._root.depth_first():
            if node.instance_name == instance_name and node.children:
                if self._on_navigate:
                    # Navigate to the first child
                    child = node.children[0]
                    self._on_navigate(child.library, child.cell, child.view)
                    return True
        return False

    def pop_up(self) -> bool:
        """Navigate up the hierarchy (return to parent)."""
        # This requires tracking the current position externally
        # The schematic editor window maintains the current context
        return True