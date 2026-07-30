"""Reference simulator comparison helpers.

External Ngspice/Xyce reference runs are disabled in this build.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from lumen.core.simulator import SimulationResult


REFERENCE_SIMULATORS: tuple[str, ...] = ()


@dataclass
class SignalComparison:
    signal: str
    points: int
    max_abs_error: float
    rms_error: float
    max_reference_abs: float
    relative_error: float
    passed: bool


@dataclass
class ReferenceRunComparison:
    simulator: str
    status: str
    message: str = ""
    raw_path: str = ""
    run_dir: str = ""
    signals: list[SignalComparison] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary_line(self) -> str:
        if self.status == "SKIP":
            return f"[Reference {self.simulator}] SKIP: {self.message}"
        if self.status == "FAIL":
            return f"[Reference {self.simulator}] FAIL: {self.message}"
        if not self.signals:
            return f"[Reference {self.simulator}] PASS: {self.message or 'run completed'}"
        worst = max(self.signals, key=lambda item: item.max_abs_error)
        outcome = "PASS" if all(item.passed for item in self.signals) else "CHECK"
        return (
            f"[Reference {self.simulator}] {outcome}: compared {len(self.signals)} signal(s), "
            f"worst {worst.signal} max_abs={worst.max_abs_error:.4g} "
            f"rms={worst.rms_error:.4g} rel={worst.relative_error:.4g}"
        )


class ReferenceComparisonRunner:
    """Compare waveforms against enabled reference simulators."""

    def __init__(self, workspace: str, work_dir: str):
        self.workspace = str(workspace or "")
        self.work_dir = str(work_dir or "")

    def compare(
        self,
        primary_simulator: str,
        netlist: str,
        primary_result: SimulationResult,
        sim_name: str,
        threads: int = 1,
        progress_callback: Callable[[str], None] | None = None,
    ) -> list[ReferenceRunComparison]:
        return []

    def _run_reference(
        self,
        simulator: str,
        netlist: str,
        primary_result: SimulationResult,
        sim_name: str,
        threads: int,
        progress_callback: Callable[[str], None] | None,
    ) -> ReferenceRunComparison:
        return ReferenceRunComparison(
            simulator=simulator,
            status="SKIP",
            message="External Ngspice/Xyce reference runs are disabled in this build.",
        )


def compare_waveforms(primary: dict, reference: dict) -> list[SignalComparison]:
    primary = primary or {}
    reference = reference or {}
    x_primary_name = _x_name(primary)
    x_ref_name = _x_name(reference)
    x_primary = _as_float_list(primary.get(x_primary_name, [])) if x_primary_name else []
    x_ref = _as_float_list(reference.get(x_ref_name, [])) if x_ref_name else []

    ref_by_key = {
        _signal_key(name): name
        for name in reference.keys()
        if not str(name).startswith("_") and name != x_ref_name
    }
    comparisons: list[SignalComparison] = []
    for name, values in primary.items():
        if str(name).startswith("_") or name == x_primary_name:
            continue
        ref_name = ref_by_key.get(_signal_key(name))
        if not ref_name:
            continue
        y_primary = _as_float_list(values)
        y_ref = _as_float_list(reference.get(ref_name, []))
        if not y_primary or not y_ref:
            continue
        if x_primary and x_ref and len(x_ref) == len(y_ref):
            y_ref_aligned = _interp_series(x_ref, y_ref, x_primary[: len(y_primary)])
            y_primary_aligned = y_primary[: len(y_ref_aligned)]
        else:
            n = min(len(y_primary), len(y_ref))
            y_primary_aligned = y_primary[:n]
            y_ref_aligned = y_ref[:n]
        if not y_primary_aligned or not y_ref_aligned:
            continue
        comparisons.append(_compare_signal(str(name), y_primary_aligned, y_ref_aligned))
    return comparisons


def format_reference_report(comparisons: list[ReferenceRunComparison]) -> str:
    if not comparisons:
        return ""
    lines = ["[reference comparison]"]
    for item in comparisons:
        lines.append(item.summary_line())
        for signal in item.signals[:8]:
            mark = "PASS" if signal.passed else "CHECK"
            lines.append(
                f"  {mark} {signal.signal}: n={signal.points} "
                f"max_abs={signal.max_abs_error:.6g} "
                f"rms={signal.rms_error:.6g} rel={signal.relative_error:.6g}"
            )
        for error in item.errors[:3]:
            lines.append(f"  ERROR {error}")
        for warning in item.warnings[:3]:
            lines.append(f"  WARNING {warning}")
    return "\n".join(lines)


def _compare_signal(name: str, primary: list[float], reference: list[float]) -> SignalComparison:
    n = min(len(primary), len(reference))
    diffs = [primary[i] - reference[i] for i in range(n)]
    max_abs = max(abs(value) for value in diffs)
    rms = math.sqrt(sum(value * value for value in diffs) / max(1, n))
    ref_abs = max(abs(value) for value in reference[:n]) if n else 0.0
    dynamic = max(reference[:n]) - min(reference[:n]) if n else 0.0
    scale = max(ref_abs, abs(dynamic), 1.0)
    relative = max_abs / scale
    tolerance = max(1e-3, 0.03 * max(abs(dynamic), 1.0))
    return SignalComparison(
        signal=name,
        points=n,
        max_abs_error=max_abs,
        rms_error=rms,
        max_reference_abs=ref_abs,
        relative_error=relative,
        passed=max_abs <= tolerance,
    )


def _x_name(waveforms: dict) -> str:
    for name in ("time", "frequency", "v-sweep", "sweep"):
        if name in waveforms:
            return name
    return ""


def _signal_key(name: str) -> str:
    text = str(name or "").strip().lower()
    if text.startswith("v(") and text.endswith(")"):
        return text[2:-1].strip()
    return text


def _as_float_list(values) -> list[float]:
    out: list[float] = []
    for value in values or []:
        try:
            out.append(float(value))
        except (TypeError, ValueError):
            pass
    return out


def _interp_series(x: list[float], y: list[float], targets: list[float]) -> list[float]:
    if not x or not y or not targets:
        return []
    n = min(len(x), len(y))
    x = x[:n]
    y = y[:n]
    out: list[float] = []
    j = 0
    for target in targets:
        while j + 1 < n and x[j + 1] < target:
            j += 1
        if target <= x[0]:
            out.append(y[0])
        elif target >= x[-1]:
            out.append(y[-1])
        elif j + 1 < n:
            x0, x1 = x[j], x[j + 1]
            y0, y1 = y[j], y[j + 1]
            alpha = 0.0 if x1 == x0 else (target - x0) / (x1 - x0)
            out.append(y0 + alpha * (y1 - y0))
    return out
