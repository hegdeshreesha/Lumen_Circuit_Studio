"""Shared Periodic Steady-State (PSS) setup helpers."""
from __future__ import annotations

import math
import re
from collections.abc import Mapping


PSS_MODE_DRIVEN = "driven"
PSS_MODE_OSCILLATOR = "oscillator"

_SPICE_NUMBER_RE = re.compile(
    r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
    r"(?:t|g|meg|k|m|u|n|p|f|a)?",
    re.IGNORECASE,
)
_SPICE_MULTIPLIERS = {
    "t": 1e12,
    "g": 1e9,
    "meg": 1e6,
    "k": 1e3,
    "m": 1e-3,
    "u": 1e-6,
    "n": 1e-9,
    "p": 1e-12,
    "f": 1e-15,
    "a": 1e-18,
}


def normalize_pss_mode(value) -> str:
    """Return a stable PSS mode token from current or legacy form values."""
    if isinstance(value, bool):
        return PSS_MODE_OSCILLATOR if value else PSS_MODE_DRIVEN
    token = str(value or "").strip().lower()
    if token in {"1", "yes", "true", "on"}:
        return PSS_MODE_OSCILLATOR
    if any(word in token for word in ("oscillator", "autonomous", "osc")):
        return PSS_MODE_OSCILLATOR
    return PSS_MODE_DRIVEN


def _lookup(values: Mapping, *names: str, default=""):
    for name in names:
        if name in values:
            return values[name]
    return default


def _positive_spice_number(text) -> bool:
    token = str(text or "").strip()
    match = _SPICE_NUMBER_RE.fullmatch(token)
    if not match:
        return False
    suffix_match = re.search(r"[a-zA-Z]+$", token)
    suffix = suffix_match.group(0).lower() if suffix_match else ""
    number_text = token[:-len(suffix)] if suffix else token
    try:
        value = float(number_text) * _SPICE_MULTIPLIERS.get(suffix, 1.0)
    except ValueError:
        return False
    return math.isfinite(value) and value > 0.0


def _present(value) -> bool:
    return str(value or "").strip() != ""


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "yes", "true", "on", "enabled"}


def _option_enabled(values: Mapping, *names: str) -> bool:
    marker = object()
    value = _lookup(values, *names, default=marker)
    return value is not marker and _truthy(value)


def _append_value_option(parts: list[str], key: str, values: Mapping, *names: str) -> None:
    value = str(_lookup(values, *names, default="") or "").strip()
    if value:
        parts.append(f"{key}={value}")


def pss_validation_errors(values: Mapping) -> list[str]:
    """Validate the GSPICE PSS fields and return user-facing messages."""
    fundamental = _lookup(values, "Fund", "fund", default="")
    harmonics = str(_lookup(values, "Harmonics", "harmonics", default="")).strip()
    mode = normalize_pss_mode(
        _lookup(
            values,
            "Mode",
            "mode",
            "Oscillator",
            "oscillator",
            "Autonomous",
            "autonomous",
            default=PSS_MODE_DRIVEN,
        )
    )

    errors = []
    if not _positive_spice_number(fundamental):
        label = "Frequency estimate" if mode == PSS_MODE_OSCILLATOR else "Fundamental frequency"
        errors.append(f"{label} must be a positive SPICE value (for example, 1G).")
    if not re.fullmatch(r"[1-9]\d*", harmonics):
        errors.append("Number of harmonics must be a positive integer.")
    tstab = _lookup(values, "Tstab", "tstab", "TSTAB", "pss_tstab", default="")
    if _present(tstab) and not _positive_spice_number(tstab):
        errors.append("Tstab must be a positive SPICE time value when provided.")
    tstab_periods = str(
        _lookup(
            values,
            "TstabPeriods",
            "Tstab Periods",
            "tstab_periods",
            "pss_tstab_periods",
            default="",
        )
        or ""
    ).strip()
    if tstab_periods and not re.fullmatch(r"[1-9]\d*", tstab_periods):
        errors.append("Tstab periods must be a positive integer when provided.")
    continuation_steps = str(
        _lookup(
            values,
            "ContinuationSteps",
            "Continuation Steps",
            "continuation_steps",
            "pss_continuation_steps",
            default="",
        )
        or ""
    ).strip()
    if continuation_steps and not re.fullmatch(r"[1-9]\d*", continuation_steps):
        errors.append("Continuation steps must be a positive integer when provided.")
    residual_goal = _lookup(
        values,
        "ResidualGoal",
        "Residual Goal",
        "residual_goal",
        "pss_residual_goal",
        "pss_reltol",
        default="",
    )
    if _present(residual_goal) and not _positive_spice_number(residual_goal):
        errors.append("Residual goal must be a positive number when provided.")
    return errors


def build_pss_statement(values: Mapping, command: str = ".PSS") -> str:
    """Build the PSS syntax supported by current GSPICE."""
    fundamental = str(_lookup(values, "Fund", "fund", default="1G") or "1G").strip()
    harmonics = str(_lookup(values, "Harmonics", "harmonics", default="7") or "7").strip()
    mode = normalize_pss_mode(
        _lookup(
            values,
            "Mode",
            "mode",
            "Oscillator",
            "oscillator",
            "Autonomous",
            "autonomous",
            default=PSS_MODE_DRIVEN,
        )
    )
    mode_option = "OSCILLATOR=YES" if mode == PSS_MODE_OSCILLATOR else "DRIVEN"
    parts = [command, fundamental, harmonics, mode_option]
    _append_value_option(parts, "TSTAB", values, "Tstab", "tstab", "TSTAB", "pss_tstab")
    _append_value_option(
        parts,
        "TSTAB_PERIODS",
        values,
        "TstabPeriods",
        "Tstab Periods",
        "tstab_periods",
        "pss_tstab_periods",
    )
    if _option_enabled(values, "Adaptive", "adaptive", "PSSAdaptive", "pss_adaptive"):
        parts.append("PSS_ADAPTIVE=YES")
    if _option_enabled(values, "Continuation", "continuation", "PSSContinuation", "pss_continuation"):
        parts.append("PSS_CONTINUATION=YES")
    _append_value_option(
        parts,
        "PSS_CONTINUATION_STEPS",
        values,
        "ContinuationSteps",
        "Continuation Steps",
        "continuation_steps",
        "pss_continuation_steps",
    )
    _append_value_option(
        parts,
        "PSS_RESIDUAL_GOAL",
        values,
        "ResidualGoal",
        "Residual Goal",
        "residual_goal",
        "pss_residual_goal",
        "pss_reltol",
    )
    return " ".join(parts)
