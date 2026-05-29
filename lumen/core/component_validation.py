"""Component parameter validation utilities."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


_NUM_RE = re.compile(
    r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([A-Za-z]+)?\s*$"
)

_SCALE = {
    "t": 1e12,
    "g": 1e9,
    "meg": 1e6,
    "k": 1e3,
    "mil": 25.4e-6,
    "m": 1e-3,
    "u": 1e-6,
    "n": 1e-9,
    "p": 1e-12,
    "f": 1e-15,
    "a": 1e-18,
}

_UNIT_ONLY_SUFFIXES = {
    "db",
    "dbm",
    "deg",
    "rad",
    "ohm",
    "v",
    "a",
    "w",
    "s",
    "hz",
}


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def parse_spice_number(raw: Any) -> float:
    """Parse a SPICE numeric string with common scale suffixes."""
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    m = _NUM_RE.match(text)
    if not m:
        raise ValueError(f"Not a numeric SPICE value: {raw}")
    base = float(m.group(1))
    suffix = (m.group(2) or "").lower()
    if not suffix:
        return base
    if suffix in _UNIT_ONLY_SUFFIXES:
        return base
    if suffix in _SCALE:
        return base * _SCALE[suffix]
    # ngspice convention: M means milli, MEG means mega.
    if suffix == "m":
        return base * 1e-3
    if suffix == "meg":
        return base * 1e6
    # Allow unit annotations after the scale, e.g. 1kHz or 10uF.
    for key, factor in sorted(_SCALE.items(), key=lambda kv: -len(kv[0])):
        if suffix.startswith(key):
            return base * factor
    raise ValueError(f"Unsupported SPICE scale suffix in value: {raw}")


def validate_symbol_params(symbol: dict, params: dict, instance_name: str = "") -> ValidationReport:
    """Validate a parameter map against symbol metadata."""
    report = ValidationReport()
    declared = symbol.get("parameters", []) if isinstance(symbol, dict) else []
    if not isinstance(params, dict):
        report.errors.append(f"{instance_name}: parameter payload must be a dict.")
        return report

    declared_names = set()
    for spec in declared:
        if not isinstance(spec, dict):
            continue
        pname = str(spec.get("name", "")).strip()
        if not pname:
            continue
        declared_names.add(pname)
        value = params.get(pname, spec.get("default", ""))
        if value in ("", None):
            continue
        ptype = str(spec.get("type", "")).lower()
        requires_numeric = bool(spec.get("numeric", False))
        # Heuristic typing from default value.
        if not ptype and isinstance(spec.get("default", None), (int, float)):
            ptype = "number"
        if ptype in ("int", "integer", "float", "double", "number") or requires_numeric:
            try:
                numeric = parse_spice_number(value)
            except ValueError:
                report.errors.append(
                    f"{instance_name}: parameter '{pname}' expects numeric value, got '{value}'."
                )
                continue
            vmin = spec.get("min", None)
            vmax = spec.get("max", None)
            if isinstance(vmin, (int, float)) and numeric < float(vmin):
                report.errors.append(
                    f"{instance_name}: parameter '{pname}'={value} below min {vmin}."
                )
            if isinstance(vmax, (int, float)) and numeric > float(vmax):
                report.errors.append(
                    f"{instance_name}: parameter '{pname}'={value} above max {vmax}."
                )
        enum_vals = spec.get("enum", None)
        if isinstance(enum_vals, list) and value not in enum_vals:
            report.errors.append(
                f"{instance_name}: parameter '{pname}' must be one of {enum_vals}, got '{value}'."
            )

    for given in params.keys():
        if given not in declared_names:
            report.warnings.append(
                f"{instance_name}: undeclared parameter '{given}' will be passed through."
            )
    return report
