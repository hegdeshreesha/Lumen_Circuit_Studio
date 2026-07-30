"""IHP SG13G2 schematic-to-KLayout PCell correspondence.

The IHP PDK already ships the authoritative netlist import templates.  This
module reads those templates without importing KLayout's ``pya`` module and
turns them into a stable, serializable catalog for Lumen's UI and Layout-XL
handoff code.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import runpy
from typing import Any, Optional


PCELL_LIBRARY = "SG13_dev"


# Lumen symbol/cell name -> (IHP netlist model, SG13_dev PCell).
# RF symbols intentionally netlist with the base MOS model plus rfmode=1,
# exactly like the official IHP Xschem symbols and import templates.
DEVICE_MAP: dict[str, tuple[str, str, dict[str, Any]]] = {
    "sg13_lv_nmos": ("sg13_lv_nmos", "nmos", {}),
    "sg13_lv_pmos": ("sg13_lv_pmos", "pmos", {}),
    "sg13_hv_nmos": ("sg13_hv_nmos", "nmosHV", {}),
    "sg13_hv_pmos": ("sg13_hv_pmos", "pmosHV", {}),
    "sg13_lv_rf_nmos": ("sg13_lv_nmos", "rfnmos", {"rfmode": 1}),
    "sg13_lv_rf_pmos": ("sg13_lv_pmos", "rfpmos", {"rfmode": 1}),
    "sg13_hv_rf_nmos": ("sg13_hv_nmos", "rfnmosHV", {"rfmode": 1}),
    "sg13_hv_rf_pmos": ("sg13_hv_pmos", "rfpmosHV", {"rfmode": 1}),
    "cap_cmim": ("cap_cmim", "cmim", {}),
    "cap_rfcmim": ("cap_rfcmim", "rfcmim", {}),
    "npn13G2": ("npn13G2", "npn13G2", {}),
    "npn13G2l": ("npn13G2l", "npn13G2L", {}),
    "npn13G2v": ("npn13G2v", "npn13G2V", {}),
    "rhigh": ("rhigh", "rhigh", {}),
    "rppd": ("rppd", "rppd", {}),
    "rsil": ("rsil", "rsil", {}),
    "bondpad": ("bondpad", "bondpad", {}),
    "dantenna": ("dantenna", "dantenna", {}),
    "dpantenna": ("dpantenna", "dpantenna", {}),
    "ntap1": ("ntap1", "ntap1", {}),
    "ptap1": ("ptap1", "ptap1", {}),
    "sg13_hv_svaricap": ("sg13_hv_svaricap", "SVaricap", {}),
    "schottky_nbl1": ("schottky_nbl1", "schottky", {}),
    "isolbox": ("isolbox", "isolbox", {}),
    "pnpMPA": ("pnpMPA", "pnpMPA", {}),
}

DEVICE_TERMINALS: dict[str, list[str]] = {
    "sg13_lv_nmos": ["D", "G", "S", "B"],
    "sg13_lv_pmos": ["D", "G", "S", "B"],
    "sg13_hv_nmos": ["D", "G", "S", "B"],
    "sg13_hv_pmos": ["D", "G", "S", "B"],
    "sg13_lv_rf_nmos": ["D", "G", "S", "B"],
    "sg13_lv_rf_pmos": ["D", "G", "S", "B"],
    "sg13_hv_rf_nmos": ["D", "G", "S", "B"],
    "sg13_hv_rf_pmos": ["D", "G", "S", "B"],
    "cap_cmim": ["c0", "c1"],
    "cap_rfcmim": ["c0", "c1", "bn"],
    "npn13G2": ["C", "B", "E", "S"],
    "npn13G2l": ["C", "B", "E", "S"],
    "npn13G2v": ["C", "B", "E", "S"],
    "rhigh": ["P", "M"],
    "rppd": ["P", "M"],
    "rsil": ["P", "M"],
}


@dataclass(frozen=True)
class IHPDeviceCorrespondence:
    symbol: str
    model: str
    pcell_library: str
    pcell_name: str
    parameters: list[dict]
    default_parameters: dict[str, Any]
    forced_parameters: dict[str, Any]
    terminals: list[str]
    multiplicity_parameter: str = "m"
    source: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class IHPDeviceResolution:
    supported: bool
    symbol: str
    model: str = ""
    pcell_library: str = ""
    pcell_name: str = ""
    pcell_parameters: Optional[dict[str, Any]] = None
    terminals: Optional[list[str]] = None
    multiplicity: int = 1
    message: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _load_templates(template_path: str | Path) -> list[dict]:
    """Load the data-only IHP template module (it imports only ``re``)."""
    path = Path(template_path)
    if not path.is_file():
        return []
    try:
        data = runpy.run_path(str(path))
    except (OSError, RuntimeError, SyntaxError):
        return []
    templates = data.get("templates", [])
    return templates if isinstance(templates, list) else []


def build_device_catalog(template_path: str | Path) -> list[IHPDeviceCorrespondence]:
    """Build the Lumen correspondence catalog from the installed PDK version."""
    templates = _load_templates(template_path)
    by_pcell: dict[str, dict] = {}
    for template in templates:
        pcell_name = str(template.get("pcell_name", ""))
        # The ESD PCell has several model-specific templates.  ESD cells are
        # still visible through the raw PDK template count, but are not Lumen
        # schematic primitives yet.
        if pcell_name and pcell_name not in by_pcell:
            by_pcell[pcell_name] = template

    result: list[IHPDeviceCorrespondence] = []
    for symbol, (model, pcell_name, forced) in DEVICE_MAP.items():
        template = by_pcell.get(pcell_name)
        if not template:
            continue
        result.append(
            IHPDeviceCorrespondence(
                symbol=symbol,
                model=model,
                pcell_library=str(template.get("pcell_library", PCELL_LIBRARY)),
                pcell_name=pcell_name,
                parameters=[dict(item) for item in template.get("params", [])],
                default_parameters=dict(template.get("default_params", {})),
                forced_parameters=dict(forced),
                terminals=list(DEVICE_TERMINALS.get(symbol, [])),
                source=str(Path(template_path)),
            )
        )
    return result


def resolve_device(
    symbol_or_model: str,
    parameters: Optional[dict[str, Any]],
    template_path: str | Path,
) -> IHPDeviceResolution:
    """Resolve a Lumen schematic instance to the exact SG13_dev PCell variant."""
    requested = str(symbol_or_model or "").strip()
    key = requested.lower()
    catalog = build_device_catalog(template_path)
    match = next(
        (
            item
            for item in catalog
            if item.symbol.lower() == key
            or (item.model.lower() == key and "_rf_" not in item.symbol.lower())
        ),
        None,
    )
    if not match:
        return IHPDeviceResolution(
            supported=False,
            symbol=requested,
            message=f"No IHP SG13G2 PCell correspondence for '{requested}'.",
        )

    supplied = {str(k).lower(): v for k, v in (parameters or {}).items()}
    pcell_params = dict(match.default_parameters)
    for descriptor in match.parameters:
        name = str(descriptor.get("name", ""))
        if name and name.lower() in supplied:
            pcell_params[name] = supplied[name.lower()]
    pcell_params.update(match.forced_parameters)

    multiplicity = 1
    raw_m = pcell_params.pop(match.multiplicity_parameter, 1)
    try:
        multiplicity = max(1, int(raw_m))
    except (TypeError, ValueError):
        return IHPDeviceResolution(
            supported=False,
            symbol=match.symbol,
            model=match.model,
            message=f"Invalid multiplicity m={raw_m!r} for '{requested}'.",
        )

    return IHPDeviceResolution(
        supported=True,
        symbol=match.symbol,
        model=match.model,
        pcell_library=match.pcell_library,
        pcell_name=match.pcell_name,
        pcell_parameters=pcell_params,
        terminals=list(match.terminals),
        multiplicity=multiplicity,
        message=f"{match.symbol} -> {match.pcell_library}::{match.pcell_name}",
    )
