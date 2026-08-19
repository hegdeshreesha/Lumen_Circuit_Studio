"""
Lumen Circuit Studio — Library Database (CDB)

Manages the library/cell/view hierarchy similar to industry-standard's commercial design database.
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
    Equivalent to industry-standard's cds.lib / commercial design database library system.
    """

    LIB_META = ".lumen_lib.json"
    CELL_META = ".lumen_cell.json"
    REGISTRY_FILE = "lumen_libs.json"
    SCHEMA_STATE = ".lumen_schema.json"
    CURRENT_SCHEMA_VERSION = 2

    def __init__(self, workspace_dir: str):
        self.workspace = Path(workspace_dir)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._migrate_workspace_schema()
        self._libraries: dict[str, LibraryInfo] = {}
        self._load_registry()

    def _schema_state_path(self) -> Path:
        return self.workspace / self.SCHEMA_STATE

    def _migrate_workspace_schema(self):
        """Apply idempotent workspace schema migrations."""
        state_path = self._schema_state_path()
        version = 0
        if state_path.exists():
            try:
                with open(state_path, "r") as f:
                    state = json.load(f)
                version = int(state.get("version", 0))
            except Exception:
                version = 0
        # v1: ensure support directories exist
        if version < 1:
            for rel in ("runs", "logs", "scratch", "exports"):
                (self.workspace / rel).mkdir(parents=True, exist_ok=True)
            version = 1
        # v2: ensure schema marker for primitives refresh behavior
        if version < 2:
            (self.workspace / "primitives").mkdir(parents=True, exist_ok=True)
            version = 2
        try:
            with open(state_path, "w") as f:
                json.dump({"version": version}, f, indent=2)
        except OSError:
            # Workspace can be read-only in restricted environments.
            # Keep running with in-memory schema state instead of crashing.
            pass

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

    def create_cell(self, library: str, cell_name: str, cell_path: str = "") -> Path:
        """Create a new cell directory inside a library.

        Args:
            library: Library name.
            cell_name: Cell name.
            cell_path: Optional explicit path for the cell directory.
                If provided and it does not end with `cell_name`, `cell_name`
                is appended automatically.
        """
        lib = self._libraries.get(library)
        if not lib:
            raise ValueError(f"Library '{library}' not found")
        lib_root = Path(lib.path).resolve()
        if cell_path:
            requested = Path(cell_path).expanduser().resolve()
            target_cell_path = requested if requested.name == cell_name else (requested / cell_name).resolve()
        else:
            target_cell_path = (lib_root / cell_name).resolve()

        # Keep cells anchored under their library root so discovery/open logic stays stable.
        try:
            target_cell_path.relative_to(lib_root)
        except ValueError:
            raise ValueError(
                f"Cell path must be inside library root: {lib_root}\n"
                f"Requested: {target_cell_path}"
            )

        target_cell_path.mkdir(parents=True, exist_ok=True)
        # Write cell metadata
        from datetime import datetime
        now = datetime.now().isoformat()
        meta = {"name": cell_name, "views": [], "created": now, "modified": now}
        with open(target_cell_path / self.CELL_META, "w") as f:
            json.dump(meta, f, indent=2)
        return target_cell_path

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
        """Create/update the built-in primitives library.

        Existing user workspaces may already contain an older primitives library,
        so this method reconciles missing built-ins on every database startup
        without overwriting edited symbols.
        """
        prim_name = "primitives"
        prim_path = self.workspace / prim_name
        if prim_name not in self._libraries:
            info = LibraryInfo(
                name=prim_name,
                path=str(prim_path),
                tech="generic",
                description="Built-in primitive components"
            )
            self._libraries[prim_name] = info
            self._save_registry()
        self._create_primitive_symbols(prim_path, overwrite=False)

    def _create_primitive_symbols(self, lib_path: Path, overwrite: bool = False):
        """Create the standard primitive component symbols."""
        lib_path.mkdir(parents=True, exist_ok=True)
        # Write lib metadata
        meta = {"name": "primitives", "tech": "generic",
                "description": "Built-in primitive components"}
        meta_path = lib_path / self.LIB_META
        if overwrite or not meta_path.exists():
            with open(meta_path, "w") as f:
                json.dump(meta, f, indent=2)

        for name, (sym_data, sch_data) in self._primitive_catalog().items():
            self._write_primitive_symbol(lib_path, name, sym_data, sch_data, overwrite)

    def _write_primitive_symbol(self, lib_path: Path, name: str, sym_data: dict,
                                sch_data: Optional[dict] = None,
                                overwrite: bool = False):
        sym_data = dict(sym_data)
        sym_data.setdefault("type", "symbol")
        sym_data["name"] = name
        sym_data["library"] = "primitives"
        sym_data["builtin"] = True
        sym_data["builtin_version"] = "0.3"

        cell_dir = lib_path / name
        cell_dir.mkdir(exist_ok=True)
        views = ["symbol"]
        if sch_data is not None:
            views.append("schematic")

        meta_path = cell_dir / self.CELL_META
        symbol_path = cell_dir / "symbol.lumen.json"
        schematic_path = cell_dir / "schematic.lumen.json"

        if overwrite or not meta_path.exists():
            with open(meta_path, "w") as f:
                json.dump({"name": name, "views": views}, f, indent=2)
        if overwrite or not symbol_path.exists() or self._should_refresh_primitive_symbol(symbol_path):
            with open(symbol_path, "w") as f:
                json.dump(sym_data, f, indent=2)
        if sch_data is not None and (overwrite or not schematic_path.exists()):
            with open(schematic_path, "w") as f:
                json.dump(sch_data, f, indent=2)

    def _should_refresh_primitive_symbol(self, symbol_path: Path) -> bool:
        """Refresh generated built-ins while allowing explicit user protection."""
        try:
            with open(symbol_path, "r") as f:
                data = json.load(f)
        except Exception:
            return True
        if data.get("user_modified") or data.get("protect_from_builtin_refresh"):
            return False
        return data.get("library") == "primitives"

    def _primitive_catalog(self):
        """Return Lumen's analogLib-style built-in primitive catalog."""
        catalog = {
            # Passive devices
            "res": self._primitive_resistor(),
            "res_var": self._primitive_variable_resistor(),
            "cap": self._primitive_capacitor(),
            "cap_var": self._primitive_variable_capacitor(),
            "ind": self._primitive_inductor(),
            "mutual_ind": self._primitive_mutual_inductor(),

            # Independent sources
            "vsource": self._primitive_vsource(),
            "isource": self._primitive_isource(),
            "vdc": self._primitive_vdc(),
            "idc": self._primitive_idc(),
            "vac": self._primitive_vac(),
            "iac": self._primitive_iac(),
            "vpulse": self._primitive_vpulse(),
            "ipulse": self._primitive_ipulse(),
            "vsin": self._primitive_vsin(),
            "isin": self._primitive_isin(),
            "vpwl": self._primitive_vpwl(),
            "ipwl": self._primitive_ipwl(),

            # Supplies, ports, and probes
            "gnd": self._primitive_gnd(),
            "vdd": self._primitive_vdd(),
            "vss": self._primitive_vss(),
            "port": self._primitive_port(),
            "opin": self._primitive_opin(),
            "ipin": self._primitive_ipin(),
            "iopin": self._primitive_iopin(),
            "no_conn": self._primitive_no_conn(),
            "iprobe": self._primitive_iprobe(),

            # Semiconductor primitives
            "nmos": self._primitive_nmos(),
            "pmos": self._primitive_pmos(),
            "nmos3": self._primitive_nmos3(),
            "pmos3": self._primitive_pmos3(),
            "diode": self._primitive_diode(),
            "zener": self._primitive_zener(),
            "led": self._primitive_led(),
            "npn": self._primitive_npn(),
            "pnp": self._primitive_pnp(),
            "njfet": self._primitive_njfet(),
            "pjfet": self._primitive_pjfet(),
            "nmes": self._primitive_nmes(),
            "pmes": self._primitive_pmes(),

            # Controlled sources and behavioral elements
            "vcvs": self._primitive_vcvs(),
            "vccs": self._primitive_vccs(),
            "cccs": self._primitive_cccs(),
            "ccvs": self._primitive_ccvs(),
            "bsource_v": self._primitive_bsource_v(),
            "bsource_i": self._primitive_bsource_i(),

            # Switches and distributed elements
            "sw_v": self._primitive_voltage_switch(),
            "sw_i": self._primitive_current_switch(),
            "tline": self._primitive_tline(),
        }
        for name, component in self._qucs_compat_catalog().items():
            catalog.setdefault(name, component)
        return catalog

    # ── Primitive Symbol Definitions ──────────────────────────
    # Each returns (symbol_data, schematic_data) — schematic is None for primitives

    def _qucs_compat_catalog(self) -> dict[str, tuple[dict, None]]:
        """Return additional QUCS-compatible primitives not yet modeled natively."""
        descriptors = [
            # Lumped components
            {"name": "dc_block", "prefix": "X", "spice": "DCBLOCK", "pins": ["PLUS", "MINUS"], "abbr": "DCB", "category": "lumped components", "params": [("C", "1uF", "capacitance in Farad")]},
            {"name": "dc_feed", "prefix": "X", "spice": "DCFEED", "pins": ["PLUS", "MINUS"], "abbr": "DCF", "category": "lumped components", "params": [("L", "1uH", "inductance in Henry")]},
            {"name": "bias_t", "prefix": "X", "spice": "BIAST", "pins": ["RF_IN", "RF_OUT", "DC_IN"], "abbr": "BT", "category": "lumped components", "params": [("L", "1uH", "inductance"), ("C", "1uF", "capacitance")]},
            {"name": "attenuator", "prefix": "X", "spice": "ATTENUATOR", "pins": ["IN", "OUT"], "abbr": "ATT", "category": "lumped components", "params": [("L", "10dB", "attenuation"), ("Zref", "50", "reference impedance")]},
            {"name": "isolator", "prefix": "X", "spice": "ISOLATOR", "pins": ["IN", "OUT"], "abbr": "ISO", "category": "lumped components", "params": [("Z1", "50", "input impedance"), ("Z2", "50", "output impedance")]},
            {"name": "circulator", "prefix": "X", "spice": "CIRCULATOR", "pins": ["P1", "P2", "P3"], "abbr": "CIR", "category": "lumped components", "params": [("Zref", "50", "reference impedance")]},
            {"name": "phase_shifter", "prefix": "X", "spice": "PSHIFT", "pins": ["IN", "OUT"], "abbr": "PHI", "category": "lumped components", "params": [("phi", "90", "phase in degree"), ("Zref", "50", "reference impedance")]},
            {"name": "coupler_ideal", "prefix": "X", "spice": "COUPLER", "pins": ["P1", "P2", "P3", "P4"], "abbr": "CPL", "category": "lumped components", "params": [("k", "0.7071", "coupling factor"), ("phi", "180", "phase shift")]},
            {"name": "hybrid", "prefix": "X", "spice": "HYBRID", "pins": ["P1", "P2", "P3", "P4"], "abbr": "HYB", "category": "lumped components", "params": [("phi", "90", "phase shift"), ("Zref", "50", "reference impedance")]},
            {"name": "voltage_probe", "prefix": "PR", "spice": "VPROBE", "pins": ["NODE"], "abbr": "VP", "category": "lumped components"},
            {"name": "time_switch", "prefix": "S", "spice": "TSW", "pins": ["PLUS", "MINUS"], "abbr": "TSW", "category": "lumped components", "params": [("t_open", "1n", "open time"), ("t_close", "2n", "close time")]},
            {"name": "relay", "prefix": "W", "spice": "RELAY", "pins": ["PLUS", "MINUS", "CTRL_P", "CTRL_N"], "abbr": "RLY", "category": "lumped components", "params": [("model", "CSW", "relay model")]},
            {"name": "transformer_ideal", "prefix": "TR", "spice": "TR", "pins": ["P1", "N1", "P2", "N2"], "abbr": "TR", "category": "lumped components", "params": [("T", "1", "turn ratio")]},
            {"name": "transformer_sym", "prefix": "TR", "spice": "STR", "pins": ["P1", "N1", "P2", "N2", "P3", "N3"], "abbr": "STR", "category": "lumped components", "params": [("T1", "1", "coil ratio 1"), ("T2", "1", "coil ratio 2")]},
            {"name": "mutual_ind_3", "prefix": "K", "spice": "MUT3", "pins": ["L1", "L2", "L3"], "abbr": "K3", "category": "lumped components", "params": [("L1", "1m", "inductor 1"), ("L2", "1m", "inductor 2"), ("L3", "1m", "inductor 3")]},

            # Sources
            {"name": "ac_power", "prefix": "P", "spice": "PAC", "pins": ["PLUS", "MINUS"], "abbr": "PAC", "category": "sources", "params": [("P", "0dBm", "power"), ("Z", "50", "reference impedance")]},
            {"name": "am_vsource", "prefix": "V", "spice": "VAM", "pins": ["PLUS", "MINUS"], "abbr": "AM", "category": "sources", "params": [("Uo", "0", "offset"), ("Uac", "1", "carrier amplitude"), ("fm", "1k", "modulation frequency")]},
            {"name": "pm_vsource", "prefix": "V", "spice": "VPM", "pins": ["PLUS", "MINUS"], "abbr": "PM", "category": "sources", "params": [("Uo", "0", "offset"), ("Uac", "1", "carrier amplitude"), ("fm", "1k", "modulation frequency")]},
            {"name": "noise_vsource", "prefix": "V", "spice": "VNOISE", "pins": ["PLUS", "MINUS"], "abbr": "VN", "category": "sources", "params": [("En", "1n", "noise density")]},
            {"name": "noise_isource", "prefix": "I", "spice": "INOISE", "pins": ["PLUS", "MINUS"], "abbr": "IN", "category": "sources", "params": [("In", "1p", "noise density")]},
            {"name": "pulse_vsingle", "prefix": "V", "spice": "VPULSE1", "pins": ["PLUS", "MINUS"], "abbr": "PV1", "category": "sources", "params": [("v1", "0", "low"), ("v2", "1", "high"), ("td", "1n", "delay")]},
            {"name": "pulse_isingle", "prefix": "I", "spice": "IPULSE1", "pins": ["PLUS", "MINUS"], "abbr": "PI1", "category": "sources", "params": [("i1", "0", "low"), ("i2", "1m", "high"), ("td", "1n", "delay")]},
            {"name": "pulse_vrect", "prefix": "V", "spice": "VPULSE_RECT", "pins": ["PLUS", "MINUS"], "abbr": "PVR", "category": "sources", "params": [("v1", "0", "low"), ("v2", "1", "high"), ("pw", "10n", "pulse width"), ("per", "20n", "period")]},
            {"name": "pulse_irect", "prefix": "I", "spice": "IPULSE_RECT", "pins": ["PLUS", "MINUS"], "abbr": "PIR", "category": "sources", "params": [("i1", "0", "low"), ("i2", "1m", "high"), ("pw", "10n", "pulse width"), ("per", "20n", "period")]},
            {"name": "pulse_vexp", "prefix": "V", "spice": "VPULSE_EXP", "pins": ["PLUS", "MINUS"], "abbr": "PVE", "category": "sources", "params": [("v1", "0", "initial"), ("v2", "1", "final"), ("tau", "1n", "time constant")]},
            {"name": "pulse_iexp", "prefix": "I", "spice": "IPULSE_EXP", "pins": ["PLUS", "MINUS"], "abbr": "PIE", "category": "sources", "params": [("i1", "0", "initial"), ("i2", "1m", "final"), ("tau", "1n", "time constant")]},
            {"name": "file_vsource", "prefix": "V", "spice": "VFILE", "pins": ["PLUS", "MINUS"], "abbr": "VF", "category": "sources", "params": [("File", "vfile.dat", "sample file path")]},
            {"name": "file_isource", "prefix": "I", "spice": "IFILE", "pins": ["PLUS", "MINUS"], "abbr": "IF", "category": "sources", "params": [("File", "ifile.dat", "sample file path")]},
            {"name": "noise_corr", "prefix": "N", "spice": "NCORR", "pins": ["OUT1", "OUT2"], "abbr": "NC", "category": "sources", "params": [("rho", "0.5", "correlation coefficient")]},
            {"name": "noise_corr_v", "prefix": "V", "spice": "VNCORR", "pins": ["OUT1", "OUT2"], "abbr": "VC", "category": "sources", "params": [("rho", "0.5", "correlation coefficient")]},
            {"name": "noise_corr_i", "prefix": "I", "spice": "INCORR", "pins": ["OUT1", "OUT2"], "abbr": "IC", "category": "sources", "params": [("rho", "0.5", "correlation coefficient")]},

            # Nonlinear
            {"name": "diac", "prefix": "D", "spice": "DIAC", "pins": ["A1", "A2"], "abbr": "DIAC", "category": "nonlinear components", "params": [("Vbo", "30", "breakover voltage")]},
            {"name": "thyristor", "prefix": "SCR", "spice": "THYRISTOR", "pins": ["A", "K", "G"], "abbr": "SCR", "category": "nonlinear components", "params": [("model", "SCR", "thyristor model")]},
            {"name": "triac", "prefix": "TRI", "spice": "TRIAC", "pins": ["MT1", "MT2", "G"], "abbr": "TRI", "category": "nonlinear components", "params": [("model", "TRIAC", "triac model")]},
            {"name": "mos_depl", "prefix": "M", "spice": "MOS_DEPL", "pins": ["D", "G", "S"], "abbr": "DMOS", "category": "nonlinear components", "params": [("model", "DMOS", "depletion MOS model")]},
            {"name": "mos_bulk", "prefix": "M", "spice": "MOS_BULK", "pins": ["D", "G", "S", "B"], "abbr": "MOSB", "category": "nonlinear components", "params": [("model", "MOS", "bulk MOS model"), ("W", "1u", "width"), ("L", "180n", "length")]},
            {"name": "hjt_sub", "prefix": "Q", "spice": "HJT_SUB", "pins": ["C", "B", "E", "SUB"], "abbr": "HJT", "category": "nonlinear components", "params": [("model", "BJT", "bipolar with substrate model")]},
            {"name": "fbh_hbt_va", "prefix": "X", "spice": "FBH_HBT_VA", "pins": ["C", "B", "E"], "abbr": "FBH", "category": "nonlinear components"},
            {"name": "hicum_l2_21_va", "prefix": "X", "spice": "HICUM_L2_21_VA", "pins": ["C", "B", "E"], "abbr": "H21", "category": "nonlinear components"},
            {"name": "hicum_l2_22_va", "prefix": "X", "spice": "HICUM_L2_22_VA", "pins": ["C", "B", "E"], "abbr": "H22", "category": "nonlinear components"},
            {"name": "hicum_l2_23_va", "prefix": "X", "spice": "HICUM_L2_23_VA", "pins": ["C", "B", "E"], "abbr": "H23", "category": "nonlinear components"},
            {"name": "hicum_l0_112_va", "prefix": "X", "spice": "HICUM_L0_112_VA", "pins": ["C", "B", "E"], "abbr": "H0112", "category": "nonlinear components"},
            {"name": "hicum_l0_12_va", "prefix": "X", "spice": "HICUM_L0_12_VA", "pins": ["C", "B", "E"], "abbr": "H012", "category": "nonlinear components"},
            {"name": "mesfet_va", "prefix": "X", "spice": "MESFET_VA", "pins": ["D", "G", "S"], "abbr": "MES", "category": "nonlinear components"},
            {"name": "ekv26mos_va", "prefix": "X", "spice": "EKV26MOS_VA", "pins": ["D", "G", "S", "B"], "abbr": "EKV", "category": "nonlinear components"},
            {"name": "opamp_mod_va", "prefix": "X", "spice": "OPAMP_MOD_VA", "pins": ["INP", "INN", "OUT", "VDD", "VSS"], "abbr": "OPM", "category": "nonlinear components"},
            {"name": "log_amp_va", "prefix": "X", "spice": "LOGAMP_VA", "pins": ["INP", "INN", "OUT"], "abbr": "LOG", "category": "nonlinear components"},
            {"name": "pot_va", "prefix": "X", "spice": "POT_VA", "pins": ["A", "W", "B"], "abbr": "POT", "category": "nonlinear components"},
            {"name": "photodiode_va", "prefix": "X", "spice": "PHOTODIODE_VA", "pins": ["A", "K", "LUX"], "abbr": "PD", "category": "nonlinear components"},
            {"name": "phototransistor_va", "prefix": "X", "spice": "PHOTOTRANSISTOR_VA", "pins": ["C", "E", "LUX"], "abbr": "PT", "category": "nonlinear components"},

            # System
            {"name": "eqn_device", "prefix": "EDD", "spice": "EDD", "pins": ["P1", "N1", "P2", "N2"], "abbr": "EDD", "category": "system components", "params": [("Expr", "I(P1,N1)=0", "equation expression")]},
            {"name": "eqn_rf_device", "prefix": "ERF", "spice": "ERF", "pins": ["P1", "P2", "P3", "P4"], "abbr": "ERF", "category": "system components", "params": [("Matrix", "S", "RF parameter type")]},
            {"name": "eqn_rf_2port", "prefix": "ER2", "spice": "ERF2", "pins": ["IN", "OUT"], "abbr": "ER2", "category": "system components", "params": [("Matrix", "S", "2-port parameter type")]},
            {"name": "sparam_file", "prefix": "SP", "spice": "SPFILE", "pins": ["P1", "P2"], "abbr": "S2P", "category": "system components", "params": [("File", "network.s2p", "S-parameter file path")]},
            {"name": "spice_netlist", "prefix": "X", "spice": "SPICE_NETLIST", "pins": ["A", "B"], "abbr": "SPICE", "category": "system components", "params": [("File", "subckt.cir", "SPICE netlist file path")]},
            {"name": "subckt_file", "prefix": "X", "spice": "SUB_FILE", "pins": ["A", "B"], "abbr": "SUB", "category": "system components", "params": [("File", "sub.sch", "Qucs schematic file path")]},
            {"name": "vhdl_file", "prefix": "U", "spice": "VHDL_FILE", "pins": ["IN", "OUT"], "abbr": "VHDL", "category": "system components", "params": [("File", "module.vhdl", "VHDL file path")]},
            {"name": "verilog_file", "prefix": "U", "spice": "VERILOG_FILE", "pins": ["IN", "OUT"], "abbr": "VER", "category": "system components", "params": [("File", "module.v", "Verilog file path")]},

            # Digital
            {"name": "digital_source", "prefix": "S", "spice": "DIGI_SOURCE", "pins": ["OUT"], "abbr": "DSRC", "category": "digital components", "params": [("init", "low", "initial value"), ("times", "1ns;1ns", "toggle times"), ("V", "1V", "high level")]},
            {"name": "gate_or", "prefix": "Y", "spice": "OR", "pins": ["A", "B", "Y"], "abbr": "OR", "category": "digital components"},
            {"name": "gate_nor", "prefix": "Y", "spice": "NOR", "pins": ["A", "B", "Y"], "abbr": "NOR", "category": "digital components"},
            {"name": "gate_and", "prefix": "Y", "spice": "AND", "pins": ["A", "B", "Y"], "abbr": "AND", "category": "digital components"},
            {"name": "gate_nand", "prefix": "Y", "spice": "NAND", "pins": ["A", "B", "Y"], "abbr": "NAND", "category": "digital components"},
            {"name": "gate_xor", "prefix": "Y", "spice": "XOR", "pins": ["A", "B", "Y"], "abbr": "XOR", "category": "digital components"},
            {"name": "gate_xnor", "prefix": "Y", "spice": "XNOR", "pins": ["A", "B", "Y"], "abbr": "XNOR", "category": "digital components"},
            {"name": "inverter_dig", "prefix": "Y", "spice": "INV", "pins": ["A", "Y"], "abbr": "NOT", "category": "digital components"},
            {"name": "buffer_dig", "prefix": "Y", "spice": "BUF", "pins": ["A", "Y"], "abbr": "BUF", "category": "digital components"},
            {"name": "dff", "prefix": "Y", "spice": "DFF", "pins": ["D", "CLK", "Q", "QN"], "abbr": "DFF", "category": "digital components"},
            {"name": "rsff", "prefix": "Y", "spice": "RSFF", "pins": ["R", "S", "Q", "QN"], "abbr": "RS", "category": "digital components"},
            {"name": "jkff", "prefix": "Y", "spice": "JKFF", "pins": ["J", "K", "CLK", "Q", "QN"], "abbr": "JK", "category": "digital components"},
            {"name": "logic0", "prefix": "Y", "spice": "LOGIC0", "pins": ["Y"], "abbr": "0", "category": "digital components"},
            {"name": "logic1", "prefix": "Y", "spice": "LOGIC1", "pins": ["Y"], "abbr": "1", "category": "digital components"},
            {"name": "tff_sr", "prefix": "Y", "spice": "TFF_SR", "pins": ["T", "CLK", "S", "R", "Q"], "abbr": "TFF", "category": "digital components"},
            {"name": "jkff_sr", "prefix": "Y", "spice": "JKFF_SR", "pins": ["J", "K", "CLK", "S", "R", "Q"], "abbr": "JKSR", "category": "digital components"},
            {"name": "dff_sr", "prefix": "Y", "spice": "DFF_SR", "pins": ["D", "CLK", "S", "R", "Q"], "abbr": "DSR", "category": "digital components"},
            {"name": "priority_encoder", "prefix": "Y", "spice": "PRIO_ENC", "pins": ["I0", "I1", "I2", "I3", "Y1", "Y0"], "abbr": "ENC", "category": "digital components"},
            {"name": "grey_to_bin", "prefix": "Y", "spice": "GREY2BIN", "pins": ["G0", "G1", "G2", "G3", "B0", "B1", "B2", "B3"], "abbr": "G2B", "category": "digital components"},
            {"name": "bin_to_grey", "prefix": "Y", "spice": "BIN2GREY", "pins": ["B0", "B1", "B2", "B3", "G0", "G1", "G2", "G3"], "abbr": "B2G", "category": "digital components"},
            {"name": "d_latch", "prefix": "Y", "spice": "DLATCH", "pins": ["D", "EN", "Q"], "abbr": "LAT", "category": "digital components"},
            {"name": "d2a_level", "prefix": "Y", "spice": "DLS_1TON", "pins": ["DIN", "AOUT"], "abbr": "D2A", "category": "digital components", "params": [("LEVEL", "5V", "analog voltage level"), ("Delay", "1ns", "time delay")]},
            {"name": "a2d_level", "prefix": "Y", "spice": "DLS_NTO1", "pins": ["AIN", "DOUT"], "abbr": "A2D", "category": "digital components", "params": [("LEVEL", "5V", "threshold level"), ("Delay", "1ns", "time delay")]},
            {"name": "mux2to1", "prefix": "Y", "spice": "MUX2TO1", "pins": ["I0", "I1", "S", "Y"], "abbr": "MUX2", "category": "digital components"},
            {"name": "mux4to1", "prefix": "Y", "spice": "MUX4TO1", "pins": ["I0", "I1", "I2", "I3", "S0", "S1", "Y"], "abbr": "MUX4", "category": "digital components"},
            {"name": "mux8to1", "prefix": "Y", "spice": "MUX8TO1", "pins": ["I0", "I1", "I2", "I3", "I4", "I5", "I6", "I7", "S0", "S1", "S2", "Y"], "abbr": "MUX8", "category": "digital components"},
            {"name": "demux2to4", "prefix": "Y", "spice": "DEMUX2TO4", "pins": ["IN", "S0", "S1", "Y0", "Y1", "Y2", "Y3"], "abbr": "DMX2", "category": "digital components"},
            {"name": "demux3to8", "prefix": "Y", "spice": "DEMUX3TO8", "pins": ["IN", "S0", "S1", "S2", "Y0", "Y1", "Y2", "Y3", "Y4", "Y5", "Y6", "Y7"], "abbr": "DMX3", "category": "digital components"},
            {"name": "demux4to16", "prefix": "Y", "spice": "DEMUX4TO16", "pins": ["IN", "S0", "S1", "S2", "S3", "Y0", "Y1", "Y2", "Y3", "Y4", "Y5", "Y6", "Y7", "Y8", "Y9", "Y10", "Y11", "Y12", "Y13", "Y14", "Y15"], "abbr": "DMX4", "category": "digital components"},
            {"name": "andor4x2", "prefix": "Y", "spice": "ANDOR4X2", "pins": ["A0", "A1", "A2", "A3", "B0", "B1", "Y"], "abbr": "4x2", "category": "digital components"},
            {"name": "andor4x3", "prefix": "Y", "spice": "ANDOR4X3", "pins": ["A0", "A1", "A2", "A3", "B0", "B1", "B2", "Y"], "abbr": "4x3", "category": "digital components"},
            {"name": "andor4x4", "prefix": "Y", "spice": "ANDOR4X4", "pins": ["A0", "A1", "A2", "A3", "B0", "B1", "B2", "B3", "Y"], "abbr": "4x4", "category": "digital components"},
            {"name": "pattern2bit", "prefix": "Y", "spice": "PAT2", "pins": ["Y0", "Y1"], "abbr": "PAT2", "category": "digital components", "params": [("Number", "0", "pattern value")]},
            {"name": "pattern3bit", "prefix": "Y", "spice": "PAT3", "pins": ["Y0", "Y1", "Y2"], "abbr": "PAT3", "category": "digital components", "params": [("Number", "0", "pattern value")]},
            {"name": "pattern4bit", "prefix": "Y", "spice": "PAT4", "pins": ["Y0", "Y1", "Y2", "Y3"], "abbr": "PAT4", "category": "digital components", "params": [("Number", "0", "pattern value")]},
            {"name": "comp_1bit", "prefix": "Y", "spice": "COMP1", "pins": ["A", "B", "GT", "EQ", "LT"], "abbr": "CMP1", "category": "digital components"},
            {"name": "comp_2bit", "prefix": "Y", "spice": "COMP2", "pins": ["A0", "A1", "B0", "B1", "GT", "EQ", "LT"], "abbr": "CMP2", "category": "digital components"},
            {"name": "comp_4bit", "prefix": "Y", "spice": "COMP4", "pins": ["A0", "A1", "A2", "A3", "B0", "B1", "B2", "B3", "GT", "EQ", "LT"], "abbr": "CMP4", "category": "digital components"},
            {"name": "half_adder_1bit", "prefix": "Y", "spice": "HADD1", "pins": ["A", "B", "SUM", "COUT"], "abbr": "HA", "category": "digital components"},
            {"name": "full_adder_1bit", "prefix": "Y", "spice": "FADD1", "pins": ["A", "B", "CIN", "SUM", "COUT"], "abbr": "FA1", "category": "digital components"},
            {"name": "full_adder_2bit", "prefix": "Y", "spice": "FADD2", "pins": ["A0", "A1", "B0", "B1", "CIN", "S0", "S1", "COUT"], "abbr": "FA2", "category": "digital components"},
        ]

        catalog: dict[str, tuple[dict, None]] = {}
        for spec in descriptors:
            params = [{"name": p[0], "default": p[1], "description": p[2]} for p in spec.get("params", [])]
            catalog[spec["name"]] = self._qucs_block_component(
                spec["name"],
                spec.get("prefix", "X"),
                spec.get("spice", spec["name"]),
                spec.get("pins", []),
                params,
                spec.get("abbr", ""),
                spec.get("category", ""),
            )
        return catalog

    def _qucs_block_component(self, name: str, prefix: str, spice_model: str,
                              pin_names: list[str], parameters: list[dict],
                              abbrev: str = "", category: str = ""):
        """Build a simple QUCS-compatible block symbol from pin metadata."""
        pin_defs: list[dict] = []
        n = max(1, len(pin_names))
        left_count = (n + 1) // 2
        right_count = n - left_count
        max_side = max(left_count, right_count, 1)
        pitch = 16
        half_span = max(16, (max_side - 1) * pitch // 2)
        rect_x1, rect_x2 = -24, 24
        rect_y1, rect_y2 = -half_span - 10, half_span + 10

        def side_y(index: int, count: int) -> int:
            if count <= 1:
                return 0
            return int(round((-((count - 1) / 2.0) + index) * pitch))

        shapes = [{"type": "rect", "x": rect_x1, "y": rect_y1, "w": rect_x2 - rect_x1, "h": rect_y2 - rect_y1}]

        left_names = pin_names[:left_count]
        right_names = pin_names[left_count:]

        for idx, pname in enumerate(left_names):
            y = side_y(idx, len(left_names))
            pin_defs.append({"name": pname, "x": -44, "y": y, "direction": "input"})
            shapes.append({"type": "line", "x1": -44, "y1": y, "x2": rect_x1, "y2": y})

        for idx, pname in enumerate(right_names):
            y = side_y(idx, len(right_names))
            pin_defs.append({"name": pname, "x": 44, "y": y, "direction": "output"})
            shapes.append({"type": "line", "x1": rect_x2, "y1": y, "x2": 44, "y2": y})

        if not right_names and left_names:
            pin_defs[0]["direction"] = "inout"

        marker = abbrev or name.upper()[:5]
        shapes.append({"type": "text", "text": marker, "x": -16, "y": -6, "size": 8, "bold": True})

        symbol, _ = self._primitive_symbol(
            name=name,
            prefix=prefix,
            spice_model=spice_model,
            pins=pin_defs,
            shapes=shapes,
            parameters=parameters,
            label={"text": "@name", "x": 28, "y": -6},
            description=f"QUCS-compatible {category} primitive".strip(),
        )
        symbol["qucs_compatible"] = True
        symbol["qucs_category"] = category
        return symbol, None

    def _primitive_symbol(self, name: str, prefix: str, spice_model: str,
                          pins: list[dict], shapes: list[dict],
                          parameters: list[dict], label: dict,
                          description: str = ""):
        sym = {
            "type": "symbol",
            "name": name,
            "library": "primitives",
            "builtin": True,
            "builtin_version": "0.3",
            "prefix": prefix,
            "spice_model": spice_model,
            "pins": pins,
            "shapes": shapes,
            "parameters": parameters,
            "label": label,
        }
        if description:
            sym["description"] = description
        return sym, None

    def _two_terminal_pins(self, top: str = "PLUS", bottom: str = "MINUS"):
        return [
            {"name": top, "x": 0, "y": -40, "direction": "inout"},
            {"name": bottom, "x": 0, "y": 40, "direction": "inout"},
        ]

    def _two_terminal_source_shapes(self, current: bool = False):
        shapes = [
            {"type": "line", "x1": 0, "y1": -40, "x2": 0, "y2": -20},
            {"type": "circle", "cx": 0, "cy": 0, "r": 20},
            {"type": "line", "x1": 0, "y1": 20, "x2": 0, "y2": 40},
        ]
        if current:
            shapes.extend([
                {"type": "line", "x1": 0, "y1": -12, "x2": 0, "y2": 12},
                {"type": "line", "x1": -4, "y1": -6, "x2": 0, "y2": -12},
                {"type": "line", "x1": 4, "y1": -6, "x2": 0, "y2": -12},
            ])
        else:
            shapes.extend([
                {"type": "line", "x1": 0, "y1": -14, "x2": 0, "y2": -6},
                {"type": "line", "x1": -4, "y1": -10, "x2": 4, "y2": -10},
                {"type": "line", "x1": -4, "y1": 10, "x2": 4, "y2": 10},
            ])
        return shapes

    def _text_shape(self, text: str, x: float, y: float,
                    size: int = 8, bold: bool = True) -> dict:
        return {
            "type": "text",
            "text": text,
            "x": x,
            "y": y,
            "size": size,
            "bold": bold,
        }

    def _source_parameters(self, mode: str):
        ac_params = [
            {"name": "acmag", "default": "", "description": "AC magnitude"},
            {"name": "acphase", "default": "0", "description": "AC phase"},
        ]
        if mode == "dc":
            return [
                {"name": "dc", "default": "1.0", "description": "DC value"},
                *ac_params,
            ]
        if mode == "ac":
            return [
                {"name": "dc", "default": "0", "description": "DC value"},
                {"name": "acmag", "default": "1", "description": "AC magnitude"},
                {"name": "acphase", "default": "0", "description": "AC phase"},
            ]
        if mode == "pulse":
            return [
                {"name": "dc", "default": "0", "description": "DC value"},
                *ac_params,
                {"name": "v1", "default": "0", "description": "Initial value"},
                {"name": "v2", "default": "1.8", "description": "Pulsed value"},
                {"name": "td", "default": "0", "description": "Delay"},
                {"name": "tr", "default": "1n", "description": "Rise time"},
                {"name": "tf", "default": "1n", "description": "Fall time"},
                {"name": "pw", "default": "5n", "description": "Pulse width"},
                {"name": "per", "default": "10n", "description": "Period"},
            ]
        if mode == "sin":
            return [
                {"name": "dc", "default": "0", "description": "DC value"},
                *ac_params,
                {"name": "vo", "default": "0", "description": "Offset"},
                {"name": "va", "default": "1", "description": "Amplitude"},
                {"name": "freq", "default": "1k", "description": "Frequency"},
                {"name": "td", "default": "0", "description": "Delay"},
                {"name": "theta", "default": "0", "description": "Damping"},
                {"name": "phase", "default": "0", "description": "Phase"},
            ]
        if mode == "pwl":
            return [
                {"name": "dc", "default": "0", "description": "DC value"},
                *ac_params,
                {"name": "points", "default": "0 0 1n 1", "description": "PWL time/value pairs"},
            ]
        return []

    def _primitive_source_variant(self, name: str, prefix: str, spice_model: str,
                                  mode: str, current: bool = False):
        label_value = {
            "dc": "DC=@dc",
            "ac": "AC=@acmag",
            "pulse": "PULSE",
            "sin": "SIN @freq",
            "pwl": "PWL",
        }.get(mode, "")
        shapes = self._two_terminal_source_shapes(current=current)
        if mode == "dc":
            shapes.append(self._text_shape("DC", -9, -8, 8))
        elif mode == "ac":
            shapes.extend([
                {"type": "polyline", "points": [[-12, 0], [-6, -7], [0, 0], [6, 7], [12, 0]]},
                self._text_shape("AC", -9, 6, 7),
            ])
        elif mode == "pulse":
            shapes.extend([
                {"type": "polyline", "points": [[-13, 7], [-7, 7], [-7, -7], [7, -7], [7, 7], [13, 7]]},
                self._text_shape("P", -4, -2, 7),
            ])
        elif mode == "sin":
            shapes.extend([
                {"type": "polyline", "points": [[-14, 0], [-7, -8], [0, 0], [7, 8], [14, 0]]},
                self._text_shape("sin", -11, 6, 6),
            ])
        elif mode == "pwl":
            shapes.extend([
                {"type": "polyline", "points": [[-14, 8], [-6, 4], [0, -8], [8, -2], [14, -10]]},
                self._text_shape("PWL", -12, 6, 6),
            ])
        return self._primitive_symbol(
            name, prefix, spice_model,
            self._two_terminal_pins(),
            shapes,
            self._source_parameters(mode),
            {"text": f"@name\\n{label_value}", "x": 25, "y": 0},
        )

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
                {"type": "text", "text": "V", "x": -5, "y": -5, "size": 8, "bold": True},
            ],
            "parameters": [
                {"name": "dc", "default": "1.8", "description": "DC voltage"},
                {"name": "acmag", "default": "", "description": "AC magnitude"},
                {"name": "acphase", "default": "0", "description": "AC phase"},
            ],
            "label": {"text": "@name\\nDC=@dc", "x": 25, "y": 0}
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
                {"type": "text", "text": "I", "x": -3, "y": -5, "size": 8, "bold": True},
            ],
            "parameters": [
                {"name": "dc", "default": "1m", "description": "DC current"},
                {"name": "acmag", "default": "", "description": "AC magnitude"},
                {"name": "acphase", "default": "0", "description": "AC phase"},
            ],
            "label": {"text": "@name\\nDC=@dc", "x": 25, "y": 0}
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
                {"type": "text", "text": "D", "x": 24, "y": -42, "size": 6, "bold": True},
                {"type": "text", "text": "G", "x": -34, "y": -9, "size": 6, "bold": True},
                {"type": "text", "text": "S", "x": 24, "y": 26, "size": 6, "bold": True},
                {"type": "text", "text": "B", "x": 43, "y": -9, "size": 6, "bold": True},
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
                {"type": "text", "text": "S", "x": 24, "y": -42, "size": 6, "bold": True},
                {"type": "text", "text": "G", "x": -34, "y": -9, "size": 6, "bold": True},
                {"type": "text", "text": "D", "x": 24, "y": 26, "size": 6, "bold": True},
                {"type": "text", "text": "B", "x": 43, "y": -9, "size": 6, "bold": True},
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
                {"type": "text", "text": "+", "x": 7, "y": -32, "size": 7, "bold": True},
                {"type": "text", "text": "-", "x": 7, "y": 18, "size": 7, "bold": True},
            ],
            "parameters": [
                {"name": "model", "default": "D1N4148", "description": "Model"},
            ],
            "label": {"text": "@name", "x": 15, "y": 0}
        }
        return sym, None

    def _primitive_variable_resistor(self):
        sym, _ = self._primitive_resistor()
        sym = dict(sym)
        sym["name"] = "res_var"
        sym["shapes"] = list(sym["shapes"]) + [
            {"type": "line", "x1": -18, "y1": 18, "x2": 18, "y2": -18},
            {"type": "line", "x1": 18, "y1": -18, "x2": 10, "y2": -17},
            {"type": "line", "x1": 18, "y1": -18, "x2": 17, "y2": -10},
        ]
        return sym, None

    def _primitive_variable_capacitor(self):
        sym, _ = self._primitive_capacitor()
        sym = dict(sym)
        sym["name"] = "cap_var"
        sym["shapes"] = list(sym["shapes"]) + [
            {"type": "line", "x1": -18, "y1": 18, "x2": 18, "y2": -18},
            {"type": "line", "x1": 18, "y1": -18, "x2": 10, "y2": -17},
            {"type": "line", "x1": 18, "y1": -18, "x2": 17, "y2": -10},
        ]
        return sym, None

    def _primitive_mutual_inductor(self):
        return self._primitive_symbol(
            "mutual_ind", "K", "K",
            [],
            [
                {"type": "arc", "cx": -14, "cy": -12, "rx": 6, "ry": 6, "start": 90, "span": 180},
                {"type": "arc", "cx": -14, "cy": 0, "rx": 6, "ry": 6, "start": 90, "span": 180},
                {"type": "arc", "cx": -14, "cy": 12, "rx": 6, "ry": 6, "start": 90, "span": 180},
                {"type": "arc", "cx": 14, "cy": -12, "rx": 6, "ry": 6, "start": 270, "span": 180},
                {"type": "arc", "cx": 14, "cy": 0, "rx": 6, "ry": 6, "start": 270, "span": 180},
                {"type": "arc", "cx": 14, "cy": 12, "rx": 6, "ry": 6, "start": 270, "span": 180},
                {"type": "line", "x1": -2, "y1": -28, "x2": -2, "y2": 28},
                {"type": "line", "x1": 2, "y1": -28, "x2": 2, "y2": 28},
            ],
            [
                {"name": "L1", "default": "L0", "description": "First inductor instance"},
                {"name": "L2", "default": "L1", "description": "Second inductor instance"},
                {"name": "K", "default": "0.99", "description": "Coupling coefficient"},
            ],
            {"text": "@name\\nK=@K", "x": 24, "y": -5},
        )

    def _primitive_vdc(self):
        return self._primitive_source_variant("vdc", "V", "VDC", "dc")

    def _primitive_idc(self):
        return self._primitive_source_variant("idc", "I", "IDC", "dc", current=True)

    def _primitive_vac(self):
        return self._primitive_source_variant("vac", "V", "VAC", "ac")

    def _primitive_iac(self):
        return self._primitive_source_variant("iac", "I", "IAC", "ac", current=True)

    def _primitive_vpulse(self):
        return self._primitive_source_variant("vpulse", "V", "VPULSE", "pulse")

    def _primitive_ipulse(self):
        return self._primitive_source_variant("ipulse", "I", "IPULSE", "pulse", current=True)

    def _primitive_vsin(self):
        return self._primitive_source_variant("vsin", "V", "VSIN", "sin")

    def _primitive_isin(self):
        return self._primitive_source_variant("isin", "I", "ISIN", "sin", current=True)

    def _primitive_vpwl(self):
        return self._primitive_source_variant("vpwl", "V", "VPWL", "pwl")

    def _primitive_ipwl(self):
        return self._primitive_source_variant("ipwl", "I", "IPWL", "pwl", current=True)

    def _primitive_vss(self):
        return self._primitive_symbol(
            "vss", "", "vss",
            [{"name": "VSS", "x": 0, "y": -10, "direction": "inout", "net_name": "VSS"}],
            [
                {"type": "line", "x1": 0, "y1": -10, "x2": 0, "y2": 0},
                {"type": "line", "x1": -12, "y1": 0, "x2": 12, "y2": 0},
                {"type": "line", "x1": -8, "y1": 5, "x2": 8, "y2": 5},
            ],
            [],
            {"text": "VSS", "x": 10, "y": 0},
        )

    def _primitive_port(self):
        return self._one_pin_symbol("port", "PORT", "PORT", "port")

    def _primitive_opin(self):
        return self._one_pin_symbol("opin", "OUT", "PORT", "port")

    def _primitive_ipin(self):
        return self._one_pin_symbol("ipin", "IN", "PORT", "port")

    def _primitive_iopin(self):
        return self._one_pin_symbol("iopin", "IO", "PORT", "port")

    def _primitive_no_conn(self):
        return self._primitive_symbol(
            "no_conn", "", "no_conn",
            [{"name": "NC", "x": 0, "y": 0, "direction": "inout"}],
            [
                {"type": "line", "x1": -8, "y1": -8, "x2": 8, "y2": 8},
                {"type": "line", "x1": -8, "y1": 8, "x2": 8, "y2": -8},
            ],
            [],
            {"text": "NC", "x": 10, "y": -10},
        )

    def _one_pin_symbol(self, name: str, pin_name: str, label: str, spice_model: str):
        return self._primitive_symbol(
            name, "", spice_model,
            [{"name": pin_name, "x": 0, "y": 0, "direction": "inout"}],
            [
                {"type": "line", "x1": 0, "y1": 0, "x2": 22, "y2": 0},
                {"type": "polygon", "points": [[22, -8], [42, 0], [22, 8]]},
                {"type": "text", "text": pin_name, "x": 7, "y": -22, "size": 7, "bold": True},
            ],
            [{"name": "net", "default": "", "description": "Optional forced net name"}],
            {"text": label, "x": 8, "y": -22},
        )

    def _primitive_iprobe(self):
        return self._primitive_symbol(
            "iprobe", "V", "IPROBE",
            self._two_terminal_pins(),
            [
                {"type": "line", "x1": 0, "y1": -40, "x2": 0, "y2": -20},
                {"type": "circle", "cx": 0, "cy": 0, "r": 20},
                {"type": "line", "x1": -10, "y1": 0, "x2": 10, "y2": 0},
                {"type": "line", "x1": 0, "y1": 20, "x2": 0, "y2": 40},
                {"type": "text", "text": "I", "x": -3, "y": -16, "size": 8, "bold": True},
                {"type": "text", "text": "0V", "x": -9, "y": 4, "size": 6, "bold": True},
            ],
            [],
            {"text": "@name\\nI probe", "x": 25, "y": 0},
        )

    def _primitive_nmos3(self):
        sym, _ = self._primitive_nmos()
        sym = dict(sym)
        sym["name"] = "nmos3"
        sym["spice_model"] = "nmos3"
        sym["pins"] = [p for p in sym["pins"] if p["name"] != "B"]
        return sym, None

    def _primitive_pmos3(self):
        sym, _ = self._primitive_pmos()
        sym = dict(sym)
        sym["name"] = "pmos3"
        sym["spice_model"] = "pmos3"
        sym["pins"] = [p for p in sym["pins"] if p["name"] != "B"]
        return sym, None

    def _primitive_zener(self):
        sym, _ = self._primitive_diode()
        sym = dict(sym)
        sym["name"] = "zener"
        sym["parameters"] = [{"name": "model", "default": "DZ", "description": "Zener model"}]
        sym["shapes"] = list(sym["shapes"]) + [
            {"type": "line", "x1": -10, "y1": 10, "x2": -16, "y2": 4},
            {"type": "line", "x1": 10, "y1": 10, "x2": 16, "y2": 16},
        ]
        return sym, None

    def _primitive_led(self):
        sym, _ = self._primitive_diode()
        sym = dict(sym)
        sym["name"] = "led"
        sym["parameters"] = [{"name": "model", "default": "LED", "description": "LED model"}]
        sym["shapes"] = list(sym["shapes"]) + [
            {"type": "line", "x1": 16, "y1": -12, "x2": 28, "y2": -24},
            {"type": "line", "x1": 28, "y1": -24, "x2": 22, "y2": -22},
            {"type": "line", "x1": 28, "y1": -24, "x2": 26, "y2": -18},
            {"type": "line", "x1": 18, "y1": 2, "x2": 30, "y2": -10},
            {"type": "line", "x1": 30, "y1": -10, "x2": 24, "y2": -8},
            {"type": "line", "x1": 30, "y1": -10, "x2": 28, "y2": -4},
        ]
        return sym, None

    def _primitive_npn(self):
        return self._bjt_symbol("npn", "NPN", outward=True)

    def _primitive_pnp(self):
        return self._bjt_symbol("pnp", "PNP", outward=False)

    def _bjt_symbol(self, name: str, model: str, outward: bool):
        arrow = [[8, 14, 18, 24], [18, 24, 10, 22], [18, 24, 16, 16]]
        if not outward:
            arrow = [[18, 24, 8, 14], [8, 14, 16, 16], [8, 14, 10, 22]]
        shapes = [
            {"type": "line", "x1": -30, "y1": 0, "x2": -4, "y2": 0},
            {"type": "line", "x1": -4, "y1": -22, "x2": -4, "y2": 22},
            {"type": "line", "x1": -4, "y1": -10, "x2": 24, "y2": -32},
            {"type": "line", "x1": 24, "y1": -32, "x2": 24, "y2": -40},
            {"type": "line", "x1": -4, "y1": 10, "x2": 24, "y2": 32},
            {"type": "line", "x1": 24, "y1": 32, "x2": 24, "y2": 40},
            {"type": "text", "text": "C", "x": 28, "y": -44, "size": 6, "bold": True},
            {"type": "text", "text": "B", "x": -42, "y": -9, "size": 6, "bold": True},
            {"type": "text", "text": "E", "x": 28, "y": 30, "size": 6, "bold": True},
        ] + [{"type": "line", "x1": a, "y1": b, "x2": c, "y2": d} for a, b, c, d in arrow]
        return self._primitive_symbol(
            name, "Q", "Q",
            [
                {"name": "C", "x": 24, "y": -40, "direction": "inout"},
                {"name": "B", "x": -30, "y": 0, "direction": "input"},
                {"name": "E", "x": 24, "y": 40, "direction": "inout"},
            ],
            shapes,
            [
                {"name": "model", "default": model, "description": "BJT model"},
                {"name": "area", "default": "", "description": "Area multiplier"},
            ],
            {"text": "@name\\n@model", "x": 32, "y": -8},
        )

    def _primitive_njfet(self):
        return self._fet3_symbol("njfet", "J", "J", "NJF", gate_arrow_in=True)

    def _primitive_pjfet(self):
        return self._fet3_symbol("pjfet", "J", "J", "PJF", gate_arrow_in=False)

    def _primitive_nmes(self):
        return self._fet3_symbol("nmes", "Z", "Z", "NMF", gate_arrow_in=True)

    def _primitive_pmes(self):
        return self._fet3_symbol("pmes", "Z", "Z", "PMF", gate_arrow_in=False)

    def _fet3_symbol(self, name: str, prefix: str, spice_model: str,
                     model: str, gate_arrow_in: bool):
        arrow = [[-18, 0, -6, 0], [-6, 0, -12, -4], [-6, 0, -12, 4]]
        if not gate_arrow_in:
            arrow = [[-6, 0, -18, 0], [-18, 0, -12, -4], [-18, 0, -12, 4]]
        shapes = [
            {"type": "line", "x1": -30, "y1": 0, "x2": -6, "y2": 0},
            {"type": "line", "x1": 0, "y1": -28, "x2": 0, "y2": 28},
            {"type": "line", "x1": 0, "y1": -20, "x2": 24, "y2": -20},
            {"type": "line", "x1": 24, "y1": -20, "x2": 24, "y2": -40},
            {"type": "line", "x1": 0, "y1": 20, "x2": 24, "y2": 20},
            {"type": "line", "x1": 24, "y1": 20, "x2": 24, "y2": 40},
            {"type": "text", "text": "D", "x": 28, "y": -44, "size": 6, "bold": True},
            {"type": "text", "text": "G", "x": -42, "y": -9, "size": 6, "bold": True},
            {"type": "text", "text": "S", "x": 28, "y": 30, "size": 6, "bold": True},
        ] + [{"type": "line", "x1": a, "y1": b, "x2": c, "y2": d} for a, b, c, d in arrow]
        return self._primitive_symbol(
            name, prefix, spice_model,
            [
                {"name": "D", "x": 24, "y": -40, "direction": "inout"},
                {"name": "G", "x": -30, "y": 0, "direction": "input"},
                {"name": "S", "x": 24, "y": 40, "direction": "inout"},
            ],
            shapes,
            [
                {"name": "model", "default": model, "description": "Device model"},
                {"name": "area", "default": "", "description": "Area multiplier"},
            ],
            {"text": "@name\\n@model", "x": 32, "y": -8},
        )

    def _controlled_source(self, name: str, prefix: str, spice_model: str, param_name: str):
        return self._primitive_symbol(
            name, prefix, spice_model,
            [
                {"name": "PLUS", "x": 0, "y": -40, "direction": "inout"},
                {"name": "MINUS", "x": 0, "y": 40, "direction": "inout"},
                {"name": "CPLUS", "x": -45, "y": -20, "direction": "input"},
                {"name": "CMINUS", "x": -45, "y": 20, "direction": "input"},
            ],
            [
                {"type": "line", "x1": 0, "y1": -40, "x2": 0, "y2": -24},
                {"type": "polygon", "points": [[0, -24], [24, 0], [0, 24], [-24, 0]]},
                {"type": "line", "x1": 0, "y1": 24, "x2": 0, "y2": 40},
                {"type": "line", "x1": -45, "y1": -20, "x2": -24, "y2": -20},
                {"type": "line", "x1": -45, "y1": 20, "x2": -24, "y2": 20},
                {"type": "text", "text": prefix, "x": -5, "y": -8, "size": 8, "bold": True},
                {"type": "text", "text": "+", "x": 5, "y": -21, "size": 7, "bold": True},
                {"type": "text", "text": "-", "x": 7, "y": 7, "size": 7, "bold": True},
                {"type": "text", "text": "+", "x": -40, "y": -34, "size": 7, "bold": True},
                {"type": "text", "text": "-", "x": -38, "y": 18, "size": 7, "bold": True},
            ],
            [{"name": param_name, "default": "1", "description": "Gain/transconductance"}],
            {"text": f"@name\\n@{param_name}", "x": 28, "y": -8},
        )

    def _primitive_vcvs(self):
        return self._controlled_source("vcvs", "E", "E", "gain")

    def _primitive_vccs(self):
        return self._controlled_source("vccs", "G", "G", "gm")

    def _primitive_cccs(self):
        return self._primitive_symbol(
            "cccs", "F", "F",
            self._two_terminal_pins(),
            self._two_terminal_source_shapes(current=True),
            [
                {"name": "vsource", "default": "V0", "description": "Controlling voltage source"},
                {"name": "gain", "default": "1", "description": "Current gain"},
            ],
            {"text": "@name\\nF=@gain", "x": 25, "y": 0},
        )

    def _primitive_ccvs(self):
        return self._primitive_symbol(
            "ccvs", "H", "H",
            self._two_terminal_pins(),
            self._two_terminal_source_shapes(),
            [
                {"name": "vsource", "default": "V0", "description": "Controlling voltage source"},
                {"name": "rm", "default": "1", "description": "Transresistance"},
            ],
            {"text": "@name\\nH=@rm", "x": 25, "y": 0},
        )

    def _primitive_bsource_v(self):
        return self._primitive_symbol(
            "bsource_v", "B", "BV",
            self._two_terminal_pins(),
            [{"type": "rect", "x": -18, "y": -24, "w": 36, "h": 48},
             {"type": "line", "x1": 0, "y1": -40, "x2": 0, "y2": -24},
             {"type": "line", "x1": 0, "y1": 24, "x2": 0, "y2": 40},
             {"type": "text", "text": "Bv", "x": -9, "y": -8, "size": 8, "bold": True}],
            [{"name": "expr", "default": "0", "description": "Voltage expression"}],
            {"text": "@name\\nV=@expr", "x": 25, "y": 0},
        )

    def _primitive_bsource_i(self):
        return self._primitive_symbol(
            "bsource_i", "B", "BI",
            self._two_terminal_pins(),
            [{"type": "rect", "x": -18, "y": -24, "w": 36, "h": 48},
             {"type": "line", "x1": 0, "y1": -40, "x2": 0, "y2": -24},
             {"type": "line", "x1": 0, "y1": 24, "x2": 0, "y2": 40},
             {"type": "text", "text": "Bi", "x": -9, "y": -8, "size": 8, "bold": True}],
            [{"name": "expr", "default": "0", "description": "Current expression"}],
            {"text": "@name\\nI=@expr", "x": 25, "y": 0},
        )

    def _primitive_voltage_switch(self):
        return self._primitive_symbol(
            "sw_v", "S", "S",
            [
                {"name": "PLUS", "x": 0, "y": -40, "direction": "inout"},
                {"name": "MINUS", "x": 0, "y": 40, "direction": "inout"},
                {"name": "CPLUS", "x": -40, "y": -15, "direction": "input"},
                {"name": "CMINUS", "x": -40, "y": 15, "direction": "input"},
            ],
            [
                {"type": "line", "x1": 0, "y1": -40, "x2": 0, "y2": -12},
                {"type": "line", "x1": 0, "y1": 12, "x2": 0, "y2": 40},
                {"type": "line", "x1": 0, "y1": -12, "x2": 16, "y2": 8},
                {"type": "line", "x1": -40, "y1": -15, "x2": -16, "y2": -15},
                {"type": "line", "x1": -40, "y1": 15, "x2": -16, "y2": 15},
                {"type": "text", "text": "S", "x": 20, "y": -7, "size": 8, "bold": True},
                {"type": "text", "text": "ctl", "x": -42, "y": -2, "size": 6, "bold": True},
            ],
            [{"name": "model", "default": "SW", "description": "Switch model"}],
            {"text": "@name\\n@model", "x": 22, "y": 0},
        )

    def _primitive_current_switch(self):
        return self._primitive_symbol(
            "sw_i", "W", "W",
            self._two_terminal_pins(),
            [
                {"type": "line", "x1": 0, "y1": -40, "x2": 0, "y2": -12},
                {"type": "line", "x1": 0, "y1": 12, "x2": 0, "y2": 40},
                {"type": "line", "x1": 0, "y1": -12, "x2": 16, "y2": 8},
                {"type": "text", "text": "W", "x": 20, "y": -7, "size": 8, "bold": True},
            ],
            [
                {"name": "vsource", "default": "V0", "description": "Controlling voltage source"},
                {"name": "model", "default": "CSW", "description": "Switch model"},
            ],
            {"text": "@name\\n@model", "x": 22, "y": 0},
        )

    def _primitive_tline(self):
        return self._primitive_symbol(
            "tline", "T", "T",
            [
                {"name": "A", "x": -40, "y": -20, "direction": "inout"},
                {"name": "B", "x": -40, "y": 20, "direction": "inout"},
                {"name": "C", "x": 40, "y": -20, "direction": "inout"},
                {"name": "D", "x": 40, "y": 20, "direction": "inout"},
            ],
            [
                {"type": "line", "x1": -40, "y1": -20, "x2": 40, "y2": -20},
                {"type": "line", "x1": -40, "y1": 20, "x2": 40, "y2": 20},
                {"type": "rect", "x": -28, "y": -30, "w": 56, "h": 60},
                {"type": "text", "text": "TLINE", "x": -19, "y": -8, "size": 7, "bold": True},
            ],
            [
                {"name": "Z0", "default": "50", "description": "Characteristic impedance"},
                {"name": "TD", "default": "1n", "description": "Delay"},
            ],
            {"text": "@name\\nZ0=@Z0", "x": 45, "y": -8},
        )
