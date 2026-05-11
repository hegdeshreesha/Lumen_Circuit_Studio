"""
Lumen Circuit Studio — Library Database (CDB)

Manages the library/cell/view hierarchy similar to Cadence's OpenAccess.
File-based storage using JSON for design data.

Directory Structure:
    library_root/
    ├── .lumen_lib.json          # Library metadata
    ├── cell_name/
    │   ├── .lumen_cell.json     # Cell metadata  
    │   ├── schematic.lumen.json # Schematic view
    │   ├── symbol.lumen.json    # Symbol view
    │   └── layout.lumen.json    # Layout view
    └── ...
"""
import json
import os
import shutil
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional
from enum import Enum


class ViewType(Enum):
    """Standard view types in the design database."""
    SCHEMATIC = "schematic"
    SYMBOL = "symbol"
    LAYOUT = "layout"
    CONFIG = "config"
    VERILOGA = "veriloga"
    EXTRACTED = "extracted"


@dataclass
class ViewInfo:
    """Metadata for a single view."""
    name: str
    view_type: str
    created: str = ""
    modified: str = ""

    @property
    def filename(self) -> str:
        return f"{self.name}.lumen.json"


@dataclass
class CellInfo:
    """Metadata for a cell within a library."""
    name: str
    views: list[str] = field(default_factory=list)
    created: str = ""
    modified: str = ""


@dataclass
class LibraryInfo:
    """Metadata for a design library."""
    name: str
    path: str
    tech: str = ""
    description: str = ""
    created: str = ""
    modified: str = ""


class LibraryDatabase:
    """
    Manages the library/cell/view file hierarchy.
    
    This is the central database for all design data in Lumen.
    Equivalent to Cadence's cds.lib / OpenAccess library system.
    """

    LIB_META = ".lumen_lib.json"
    CELL_META = ".lumen_cell.json"
    REGISTRY_FILE = "lumen_libs.json"

    def __init__(self, workspace_dir: str):
        self.workspace = Path(workspace_dir)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._libraries: dict[str, LibraryInfo] = {}
        self._load_registry()

    # ── Registry ──────────────────────────────────────────────

    def _registry_path(self) -> Path:
        return self.workspace / self.REGISTRY_FILE

    def _load_registry(self):
        """Load the library registry from disk."""
        reg = self._registry_path()
        if reg.exists():
            with open(reg, "r") as f:
                data = json.load(f)
            for entry in data.get("libraries", []):
                info = LibraryInfo(**entry)
                if Path(info.path).exists():
                    self._libraries[info.name] = info
        # Always include built-in primitives
        self._ensure_primitives()

    def _save_registry(self):
        """Persist the library registry to disk."""
        data = {
            "version": "1.0",
            "libraries": [asdict(lib) for lib in self._libraries.values()]
        }
        with open(self._registry_path(), "w") as f:
            json.dump(data, f, indent=2)

    # ── Library Operations ────────────────────────────────────

    def get_libraries(self) -> list[LibraryInfo]:
        """Return all registered libraries."""
        return list(self._libraries.values())

    def get_library(self, name: str) -> Optional[LibraryInfo]:
        return self._libraries.get(name)

    def create_library(self, name: str, path: str = "", tech: str = "",
                       description: str = "") -> LibraryInfo:
        """Create a new library directory and register it."""
        if name in self._libraries:
            raise ValueError(f"Library '{name}' already exists")
        if not path:
            path = str(self.workspace / name)
        lib_path = Path(path)
        lib_path.mkdir(parents=True, exist_ok=True)

        from datetime import datetime
        now = datetime.now().isoformat()
        info = LibraryInfo(name=name, path=str(lib_path), tech=tech,
                           description=description, created=now, modified=now)
        # Write library metadata
        meta = lib_path / self.LIB_META
        with open(meta, "w") as f:
            json.dump(asdict(info), f, indent=2)

        self._libraries[name] = info
        self._save_registry()
        return info

    def delete_library(self, name: str):
        """Delete a library and all its contents."""
        if name not in self._libraries:
            raise ValueError(f"Library '{name}' not found")
        lib = self._libraries[name]
        path = Path(lib.path)
        if path.exists():
            shutil.rmtree(path)
        del self._libraries[name]
        self._save_registry()

    def rename_library(self, old_name: str, new_name: str):
        """Rename a library."""
        if old_name not in self._libraries:
            raise ValueError(f"Library '{old_name}' not found")
        if new_name in self._libraries:
            raise ValueError(f"Library '{new_name}' already exists")
        lib = self._libraries.pop(old_name)
        old_path = Path(lib.path)
        new_path = old_path.parent / new_name
        if old_path.exists():
            old_path.rename(new_path)
        lib.name = new_name
        lib.path = str(new_path)
        self._libraries[new_name] = lib
        self._save_registry()

    # ── Cell Operations ───────────────────────────────────────

    def get_cells(self, library: str) -> list[str]:
        """List all cells in a library."""
        lib = self._libraries.get(library)
        if not lib:
            return []
        lib_path = Path(lib.path)
        cells = []
        if lib_path.exists():
            for child in sorted(lib_path.iterdir()):
                if child.is_dir() and not child.name.startswith("."):
                    cells.append(child.name)
        return cells

    def cell_exists(self, library: str, cell_name: str) -> bool:
        """Return True if a cell directory exists in the given library."""
        lib = self._libraries.get(library)
        if not lib:
            return False
        return (Path(lib.path) / cell_name).is_dir()

    def create_cell(self, library: str, cell_name: str) -> Path:
        """Create a new cell directory inside a library."""
        lib = self._libraries.get(library)
        if not lib:
            raise ValueError(f"Library '{library}' not found")
        cell_path = Path(lib.path) / cell_name
        cell_path.mkdir(parents=True, exist_ok=True)
        # Write cell metadata
        from datetime import datetime
        now = datetime.now().isoformat()
        meta = {"name": cell_name, "views": [], "created": now, "modified": now}
        with open(cell_path / self.CELL_META, "w") as f:
            json.dump(meta, f, indent=2)
        return cell_path

    def delete_cell(self, library: str, cell_name: str):
        lib = self._libraries.get(library)
        if not lib:
            raise ValueError(f"Library '{library}' not found")
        cell_path = Path(lib.path) / cell_name
        if cell_path.exists():
            shutil.rmtree(cell_path)

    # ── View Operations ───────────────────────────────────────

    def get_views(self, library: str, cell: str) -> list[str]:
        """List all views for a cell."""
        lib = self._libraries.get(library)
        if not lib:
            return []
        cell_path = Path(lib.path) / cell
        views = []
        if cell_path.exists():
            for child in sorted(cell_path.iterdir()):
                if child.is_file() and child.name.endswith(".lumen.json"):
                    view_name = child.name.replace(".lumen.json", "")
                    views.append(view_name)
                elif child.suffix == ".va":
                    views.append("veriloga")
        return views

    def view_exists(self, library: str, cell: str, view: str) -> bool:
        """Return True if a specific view exists for a cell."""
        return self.get_view_path(library, cell, view).is_file() if self.get_view_path(library, cell, view) else False

    def save_view(self, library: str, cell: str, view: str, data: dict):
        """Save view data as JSON."""
        lib = self._libraries.get(library)
        if not lib:
            raise ValueError(f"Library '{library}' not found")
        cell_path = Path(lib.path) / cell
        cell_path.mkdir(parents=True, exist_ok=True)
        filepath = cell_path / f"{view}.lumen.json"
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

    def load_view(self, library: str, cell: str, view: str) -> Optional[dict]:
        """Load view data from JSON."""
        lib = self._libraries.get(library)
        if not lib:
            return None
        filepath = Path(lib.path) / cell / f"{view}.lumen.json"
        if filepath.exists():
            with open(filepath, "r") as f:
                return json.load(f)
        return None

    def get_view_path(self, library: str, cell: str, view: str) -> Optional[Path]:
        """Get filesystem path for a view."""
        lib = self._libraries.get(library)
        if not lib:
            return None
        return Path(lib.path) / cell / f"{view}.lumen.json"

    # ── Built-in Primitives ───────────────────────────────────

    def _ensure_primitives(self):
        """Create the built-in primitives library if it doesn't exist."""
        prim_name = "primitives"
        prim_path = self.workspace / prim_name
        if prim_name not in self._libraries:
            if not prim_path.exists():
                self._create_primitive_symbols(prim_path)
            info = LibraryInfo(
                name=prim_name,
                path=str(prim_path),
                tech="generic",
                description="Built-in primitive components"
            )
            self._libraries[prim_name] = info
            self._save_registry()

    def _create_primitive_symbols(self, lib_path: Path):
        """Create the standard primitive component symbols."""
        lib_path.mkdir(parents=True, exist_ok=True)
        # Write lib metadata
        meta = {"name": "primitives", "tech": "generic",
                "description": "Built-in primitive components"}
        with open(lib_path / self.LIB_META, "w") as f:
            json.dump(meta, f, indent=2)

        primitives = {
            "res": self._primitive_resistor(),
            "cap": self._primitive_capacitor(),
            "ind": self._primitive_inductor(),
            "vsource": self._primitive_vsource(),
            "isource": self._primitive_isource(),
            "gnd": self._primitive_gnd(),
            "vdd": self._primitive_vdd(),
            "nmos": self._primitive_nmos(),
            "pmos": self._primitive_pmos(),
            "diode": self._primitive_diode(),
        }
        for name, (sym_data, sch_data) in primitives.items():
            cell_dir = lib_path / name
            cell_dir.mkdir(exist_ok=True)
            with open(cell_dir / self.CELL_META, "w") as f:
                json.dump({"name": name, "views": ["symbol"]}, f, indent=2)
            with open(cell_dir / "symbol.lumen.json", "w") as f:
                json.dump(sym_data, f, indent=2)

    # ── Primitive Symbol Definitions ──────────────────────────
    # Each returns (symbol_data, schematic_data) — schematic is None for primitives

    def _primitive_resistor(self):
        sym = {
            "type": "symbol", "name": "res", "library": "primitives",
            "prefix": "R", "spice_model": "R",
            "pins": [
                {"name": "PLUS", "x": 0, "y": -40, "direction": "input"},
                {"name": "MINUS", "x": 0, "y": 40, "direction": "output"}
            ],
            "shapes": [
                {"type": "line", "x1": 0, "y1": -40, "x2": 0, "y2": -25},
                {"type": "polyline", "points": [
                    [0, -25], [8, -20], [-8, -15], [8, -10],
                    [-8, -5], [8, 0], [-8, 5], [8, 10],
                    [-8, 15], [8, 20], [0, 25]
                ]},
                {"type": "line", "x1": 0, "y1": 25, "x2": 0, "y2": 40},
            ],
            "parameters": [
                {"name": "R", "default": "1k", "description": "Resistance"},
            ],
            "label": {"text": "@name\\nR=@R", "x": 15, "y": 0}
        }
        return sym, None

    def _primitive_capacitor(self):
        sym = {
            "type": "symbol", "name": "cap", "library": "primitives",
            "prefix": "C", "spice_model": "C",
            "pins": [
                {"name": "PLUS", "x": 0, "y": -40, "direction": "input"},
                {"name": "MINUS", "x": 0, "y": 40, "direction": "output"}
            ],
            "shapes": [
                {"type": "line", "x1": 0, "y1": -40, "x2": 0, "y2": -6},
                {"type": "line", "x1": -12, "y1": -6, "x2": 12, "y2": -6},
                {"type": "line", "x1": -12, "y1": 6, "x2": 12, "y2": 6},
                {"type": "line", "x1": 0, "y1": 6, "x2": 0, "y2": 40},
            ],
            "parameters": [
                {"name": "C", "default": "1p", "description": "Capacitance"},
            ],
            "label": {"text": "@name\\nC=@C", "x": 15, "y": 0}
        }
        return sym, None

    def _primitive_inductor(self):
        sym = {
            "type": "symbol", "name": "ind", "library": "primitives",
            "prefix": "L", "spice_model": "L",
            "pins": [
                {"name": "PLUS", "x": 0, "y": -40, "direction": "input"},
                {"name": "MINUS", "x": 0, "y": 40, "direction": "output"}
            ],
            "shapes": [
                {"type": "line", "x1": 0, "y1": -40, "x2": 0, "y2": -24},
                {"type": "arc", "cx": 0, "cy": -18, "rx": 6, "ry": 6,
                 "start": 270, "span": 180},
                {"type": "arc", "cx": 0, "cy": -6, "rx": 6, "ry": 6,
                 "start": 270, "span": 180},
                {"type": "arc", "cx": 0, "cy": 6, "rx": 6, "ry": 6,
                 "start": 270, "span": 180},
                {"type": "arc", "cx": 0, "cy": 18, "rx": 6, "ry": 6,
                 "start": 270, "span": 180},
                {"type": "line", "x1": 0, "y1": 24, "x2": 0, "y2": 40},
            ],
            "parameters": [
                {"name": "L", "default": "1n", "description": "Inductance"},
            ],
            "label": {"text": "@name\\nL=@L", "x": 15, "y": 0}
        }
        return sym, None

    def _primitive_vsource(self):
        sym = {
            "type": "symbol", "name": "vsource", "library": "primitives",
            "prefix": "V", "spice_model": "V",
            "pins": [
                {"name": "PLUS", "x": 0, "y": -40, "direction": "input"},
                {"name": "MINUS", "x": 0, "y": 40, "direction": "output"}
            ],
            "shapes": [
                {"type": "line", "x1": 0, "y1": -40, "x2": 0, "y2": -20},
                {"type": "circle", "cx": 0, "cy": 0, "r": 20},
                {"type": "line", "x1": 0, "y1": -14, "x2": 0, "y2": -6},
                {"type": "line", "x1": -4, "y1": -10, "x2": 4, "y2": -10},
                {"type": "line", "x1": -4, "y1": 10, "x2": 4, "y2": 10},
                {"type": "line", "x1": 0, "y1": 20, "x2": 0, "y2": 40},
            ],
            "parameters": [
                {"name": "DC", "default": "1.8", "description": "DC voltage"},
                {"name": "AC", "default": "", "description": "AC magnitude"},
            ],
            "label": {"text": "@name\\nDC=@DC", "x": 25, "y": 0}
        }
        return sym, None

    def _primitive_isource(self):
        sym = {
            "type": "symbol", "name": "isource", "library": "primitives",
            "prefix": "I", "spice_model": "I",
            "pins": [
                {"name": "PLUS", "x": 0, "y": -40, "direction": "input"},
                {"name": "MINUS", "x": 0, "y": 40, "direction": "output"}
            ],
            "shapes": [
                {"type": "line", "x1": 0, "y1": -40, "x2": 0, "y2": -20},
                {"type": "circle", "cx": 0, "cy": 0, "r": 20},
                {"type": "line", "x1": 0, "y1": -12, "x2": 0, "y2": 12},
                {"type": "line", "x1": -4, "y1": -6, "x2": 0, "y2": -12},
                {"type": "line", "x1": 4, "y1": -6, "x2": 0, "y2": -12},
                {"type": "line", "x1": 0, "y1": 20, "x2": 0, "y2": 40},
            ],
            "parameters": [
                {"name": "DC", "default": "1m", "description": "DC current"},
            ],
            "label": {"text": "@name\\nDC=@DC", "x": 25, "y": 0}
        }
        return sym, None

    def _primitive_gnd(self):
        sym = {
            "type": "symbol", "name": "gnd", "library": "primitives",
            "prefix": "", "spice_model": "gnd",
            "pins": [
                {"name": "GND", "x": 0, "y": -10, "direction": "inout",
                 "net_name": "0"}
            ],
            "shapes": [
                {"type": "line", "x1": 0, "y1": -10, "x2": 0, "y2": 0},
                {"type": "line", "x1": -12, "y1": 0, "x2": 12, "y2": 0},
                {"type": "line", "x1": -8, "y1": 5, "x2": 8, "y2": 5},
                {"type": "line", "x1": -4, "y1": 10, "x2": 4, "y2": 10},
            ],
            "parameters": [],
            "label": {"text": "", "x": 0, "y": 0}
        }
        return sym, None

    def _primitive_vdd(self):
        sym = {
            "type": "symbol", "name": "vdd", "library": "primitives",
            "prefix": "", "spice_model": "vdd",
            "pins": [
                {"name": "VDD", "x": 0, "y": 10, "direction": "inout",
                 "net_name": "VDD"}
            ],
            "shapes": [
                {"type": "line", "x1": 0, "y1": 10, "x2": 0, "y2": 0},
                {"type": "line", "x1": -12, "y1": 0, "x2": 12, "y2": 0},
            ],
            "parameters": [],
            "label": {"text": "VDD", "x": 0, "y": -8}
        }
        return sym, None

    def _primitive_nmos(self):
        sym = {
            "type": "symbol", "name": "nmos", "library": "primitives",
            "prefix": "M", "spice_model": "nmos",
            "pins": [
                {"name": "D", "x": 20, "y": -30, "direction": "inout"},
                {"name": "G", "x": -20, "y": 0, "direction": "input"},
                {"name": "S", "x": 20, "y": 30, "direction": "inout"},
                {"name": "B", "x": 40, "y": 0, "direction": "inout"},
            ],
            "shapes": [
                # Gate
                {"type": "line", "x1": -20, "y1": 0, "x2": -4, "y2": 0},
                {"type": "line", "x1": -4, "y1": -16, "x2": -4, "y2": 16},
                # Channel
                {"type": "line", "x1": 2, "y1": -16, "x2": 2, "y2": -6},
                {"type": "line", "x1": 2, "y1": -3, "x2": 2, "y2": 3},
                {"type": "line", "x1": 2, "y1": 6, "x2": 2, "y2": 16},
                # Drain
                {"type": "line", "x1": 2, "y1": -12, "x2": 20, "y2": -12},
                {"type": "line", "x1": 20, "y1": -30, "x2": 20, "y2": -12},
                # Source
                {"type": "line", "x1": 2, "y1": 12, "x2": 20, "y2": 12},
                {"type": "line", "x1": 20, "y1": 12, "x2": 20, "y2": 30},
                # Bulk
                {"type": "line", "x1": 2, "y1": 0, "x2": 40, "y2": 0},
                # Arrow on source (N-type)
                {"type": "line", "x1": 6, "y1": 12, "x2": 2, "y2": 9},
                {"type": "line", "x1": 6, "y1": 12, "x2": 2, "y2": 15},
            ],
            "parameters": [
                {"name": "W", "default": "1u", "description": "Width"},
                {"name": "L", "default": "100n", "description": "Length"},
                {"name": "nf", "default": "1", "description": "Fingers"},
                {"name": "model", "default": "nch", "description": "Model name"},
            ],
            "label": {"text": "@name\\nW=@W L=@L\\nm=@nf", "x": 30, "y": -20}
        }
        return sym, None

    def _primitive_pmos(self):
        sym = {
            "type": "symbol", "name": "pmos", "library": "primitives",
            "prefix": "M", "spice_model": "pmos",
            "pins": [
                {"name": "D", "x": 20, "y": 30, "direction": "inout"},
                {"name": "G", "x": -20, "y": 0, "direction": "input"},
                {"name": "S", "x": 20, "y": -30, "direction": "inout"},
                {"name": "B", "x": 40, "y": 0, "direction": "inout"},
            ],
            "shapes": [
                {"type": "line", "x1": -20, "y1": 0, "x2": -10, "y2": 0},
                {"type": "circle", "cx": -7, "cy": 0, "r": 3},
                {"type": "line", "x1": -4, "y1": -16, "x2": -4, "y2": 16},
                {"type": "line", "x1": 2, "y1": -16, "x2": 2, "y2": -6},
                {"type": "line", "x1": 2, "y1": -3, "x2": 2, "y2": 3},
                {"type": "line", "x1": 2, "y1": 6, "x2": 2, "y2": 16},
                {"type": "line", "x1": 2, "y1": -12, "x2": 20, "y2": -12},
                {"type": "line", "x1": 20, "y1": -30, "x2": 20, "y2": -12},
                {"type": "line", "x1": 2, "y1": 12, "x2": 20, "y2": 12},
                {"type": "line", "x1": 20, "y1": 12, "x2": 20, "y2": 30},
                {"type": "line", "x1": 2, "y1": 0, "x2": 40, "y2": 0},
            ],
            "parameters": [
                {"name": "W", "default": "2u", "description": "Width"},
                {"name": "L", "default": "100n", "description": "Length"},
                {"name": "nf", "default": "1", "description": "Fingers"},
                {"name": "model", "default": "pch", "description": "Model name"},
            ],
            "label": {"text": "@name\\nW=@W L=@L\\nm=@nf", "x": 30, "y": -20}
        }
        return sym, None

    def _primitive_diode(self):
        sym = {
            "type": "symbol", "name": "diode", "library": "primitives",
            "prefix": "D", "spice_model": "D",
            "pins": [
                {"name": "PLUS", "x": 0, "y": -30, "direction": "input"},
                {"name": "MINUS", "x": 0, "y": 30, "direction": "output"}
            ],
            "shapes": [
                {"type": "line", "x1": 0, "y1": -30, "x2": 0, "y2": -10},
                {"type": "polygon", "points": [[-10, -10], [10, -10], [0, 10]]},
                {"type": "line", "x1": -10, "y1": 10, "x2": 10, "y2": 10},
                {"type": "line", "x1": 0, "y1": 10, "x2": 0, "y2": 30},
            ],
            "parameters": [
                {"name": "model", "default": "D1N4148", "description": "Model"},
            ],
            "label": {"text": "@name", "x": 15, "y": 0}
        }
        return sym, None
