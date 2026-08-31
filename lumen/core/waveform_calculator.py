"""
Lumen Circuit Studio — Waveform Expression Calculator Engine

Provides Simulation Cockpit waveform calculator functions (bandwidth, rise_time,
phase_margin, delay, RMS, peak-to-peak) for simulation output analysis.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Union, Tuple


class WaveformVector:
    """Represents a time/frequency-domain vector (x_data, y_data)."""

    def __init__(self, x_data: List[float], y_data: List[float], name: str = "signal"):
        if len(x_data) != len(y_data):
            raise ValueError(f"Length mismatch: x ({len(x_data)}) vs y ({len(y_data)})")
        self.x = [float(v) for v in x_data]
        self.y = [float(v) for v in y_data]
        self.name = name

    def __len__(self) -> int:
        return len(self.x)

    def max_value(self) -> float:
        return max(self.y) if self.y else 0.0

    def min_value(self) -> float:
        return min(self.y) if self.y else 0.0

    def peak_to_peak(self) -> float:
        return self.max_value() - self.min_value()

    def mean(self) -> float:
        return sum(self.y) / len(self.y) if self.y else 0.0

    def rms(self) -> float:
        if not self.y:
            return 0.0
        square_sum = sum(v * v for v in self.y)
        return math.sqrt(square_sum / len(self.y))

    def final_value(self) -> float:
        return self.y[-1] if self.y else 0.0

    def value_at(self, x_value: float) -> float:
        """Return linearly interpolated value at x_value."""
        if not self.x or not self.y:
            return 0.0
        target = float(x_value)
        if target <= self.x[0]:
            return self.y[0]
        if target >= self.x[-1]:
            return self.y[-1]
        for i in range(len(self.x) - 1):
            x0, x1 = self.x[i], self.x[i + 1]
            if x0 <= target <= x1:
                y0, y1 = self.y[i], self.y[i + 1]
                if x1 == x0:
                    return y0
                return y0 + (target - x0) * (y1 - y0) / (x1 - x0)
        return self.y[-1]


def gamma_to_impedance(gamma: complex, z0: float = 50.0) -> complex:
    """Convert reflection coefficient to impedance."""
    denom = 1.0 - gamma
    if abs(denom) == 0.0:
        return complex(math.inf, math.inf)
    return float(z0) * (1.0 + gamma) / denom


def gamma_to_admittance(gamma: complex, z0: float = 50.0) -> complex:
    """Convert reflection coefficient to admittance."""
    z = gamma_to_impedance(gamma, z0)
    if abs(z) == 0.0:
        return complex(math.inf, math.inf)
    return 1.0 / z


def polar_to_complex(magnitude: float, phase_deg: float = 0.0) -> complex:
    """Convert magnitude/phase in degrees to a complex value."""
    return complex(float(magnitude) * math.cos(math.radians(float(phase_deg))), float(magnitude) * math.sin(math.radians(float(phase_deg))))


def noise_figure_from_params_db(
    nfmin_db: float,
    rn_ohm: float,
    gamma_opt: complex,
    gamma_source: complex,
    z0: float = 50.0,
) -> float:
    """Return two-port noise figure from NFmin/Rn/Gammaopt/Gammas."""
    if abs(gamma_source) >= 1.0:
        return math.inf
    fmin = 10.0 ** (float(nfmin_db) / 10.0)
    denom = (1.0 - abs(gamma_source) ** 2) * abs(1.0 + gamma_opt) ** 2
    if denom <= 0.0 or z0 <= 0.0:
        return math.nan
    factor = fmin + (4.0 * float(rn_ohm) / float(z0)) * abs(gamma_source - gamma_opt) ** 2 / denom
    return 10.0 * math.log10(factor) if factor > 0.0 else math.nan


def noise_circle(gamma_opt: complex, nfmin_db: float, rn_ohm: float, target_nf_db: float, z0: float = 50.0) -> tuple[complex, float]:
    """Return center/radius for a constant-noise-figure circle."""
    if rn_ohm <= 0.0 or z0 <= 0.0:
        return complex(math.nan, math.nan), math.nan
    fmin = 10.0 ** (float(nfmin_db) / 10.0)
    target = 10.0 ** (float(target_nf_db) / 10.0)
    n_factor = (target - fmin) * abs(1.0 + gamma_opt) ** 2 / (4.0 * float(rn_ohm) / float(z0))
    if n_factor < 0.0:
        return complex(math.nan, math.nan), math.nan
    center = gamma_opt / (1.0 + n_factor)
    radius = math.sqrt(n_factor * n_factor + n_factor * (1.0 - abs(gamma_opt) ** 2)) / (1.0 + n_factor)
    return center, radius


def real_l_match(load_ohm: float, frequency_hz: float, z0: float = 50.0) -> tuple[float, float]:
    """Return series reactance and shunt susceptance for a real-load L match."""
    r_load = float(load_ohm)
    freq = float(frequency_hz)
    if r_load <= 0.0 or z0 <= 0.0 or freq <= 0.0 or abs(r_load - z0) < 1e-15:
        return 0.0, 0.0
    if r_load < z0:
        q = math.sqrt(z0 / r_load - 1.0)
        return q * r_load, q / z0
    q = math.sqrt(r_load / z0 - 1.0)
    return q * z0, q / r_load


def real_l_match_components(load_ohm: float, frequency_hz: float, z0: float = 50.0) -> dict[str, float]:
    """Return low-pass L-match series inductance and shunt capacitance values."""
    xs, bp = real_l_match(load_ohm, frequency_hz, z0)
    omega = 2.0 * math.pi * float(frequency_hz)
    return {
        "series_L_H": xs / omega if omega else math.nan,
        "shunt_C_F": bp / omega if omega else math.nan,
        "series_X_ohm": xs,
        "shunt_B_siemens": bp,
    }


def stability_circle(
    s11: complex,
    s12: complex,
    s21: complex,
    s22: complex,
    plane: str = "source",
) -> tuple[complex, float]:
    """Return source or load stability-circle center/radius."""
    delta = s11 * s22 - s12 * s21
    if str(plane).lower().startswith("load"):
        denom = abs(s22) ** 2 - abs(delta) ** 2
        center = (s22 - delta * s11.conjugate()).conjugate() / denom if denom else complex(math.nan, math.nan)
    else:
        denom = abs(s11) ** 2 - abs(delta) ** 2
        center = (s11 - delta * s22.conjugate()).conjugate() / denom if denom else complex(math.nan, math.nan)
    radius = abs(s12 * s21 / denom) if denom else math.nan
    return center, radius


def constant_vswr_radius(vswr: float) -> float:
    """Return Smith-chart reflection-coefficient radius for a VSWR circle."""
    value = float(vswr)
    return (value - 1.0) / (value + 1.0) if value >= 1.0 else math.nan


def parse_touchstone(path: str) -> dict[str, list[float]]:
    """Parse Touchstone .sNp files into frequency, Sij magnitude, and phase vectors."""
    scale = 1.0
    fmt = "MA"
    n_ports = 0
    suffix = str(path).lower().rsplit(".", 1)[-1]
    if len(suffix) >= 3 and suffix[0] == "s" and suffix[-1] == "p" and suffix[1:-1].isdigit():
        n_ports = int(suffix[1:-1])
    rows: list[float] = []
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        for raw in fh:
            line = raw.split("!", 1)[0].strip()
            if not line:
                continue
            if line.startswith("#"):
                tokens = line.upper().split()
                if "HZ" in tokens:
                    scale = 1.0
                elif "KHZ" in tokens:
                    scale = 1e3
                elif "MHZ" in tokens:
                    scale = 1e6
                elif "GHZ" in tokens:
                    scale = 1e9
                for candidate in ("MA", "DB", "RI"):
                    if candidate in tokens:
                        fmt = candidate
                continue
            rows.extend(float(token) for token in line.split())
    if n_ports <= 0:
        raise ValueError(f"Cannot infer Touchstone port count from filename: {path}")
    per_point = 1 + 2 * n_ports * n_ports
    waveforms: dict[str, list[float]] = {"frequency": []}
    pairs = (
        [(0, 0), (1, 0), (0, 1), (1, 1)]
        if n_ports == 2
        else [(row, col) for row in range(n_ports) for col in range(n_ports)]
    )
    for row, col in pairs:
        name = f"S{row + 1}{col + 1}"
        waveforms[name] = []
        waveforms[f"phase({name})"] = []
    for start in range(0, len(rows), per_point):
        point = rows[start:start + per_point]
        if len(point) < per_point:
            break
        waveforms["frequency"].append(point[0] * scale)
        idx = 1
        for row, col in pairs:
            a, b = point[idx], point[idx + 1]
            idx += 2
            if fmt == "DB":
                mag, phase = 10.0 ** (a / 20.0), b
            elif fmt == "RI":
                value = complex(a, b)
                mag, phase = abs(value), math.degrees(math.atan2(value.imag, value.real))
            else:
                mag, phase = a, b
            name = f"S{row + 1}{col + 1}"
            waveforms[name].append(mag)
            waveforms[f"phase({name})"].append(phase)
    return waveforms


class WaveformCalculator:
    """Waveform expression evaluator for Simulation Cockpit/SigView."""

    def __init__(self, waveforms: Dict[str, Tuple[List[float], List[float]]]):
        """
        waveforms map: signal_name -> (x_vector, y_vector)
        """
        self.signals: Dict[str, WaveformVector] = {}
        for sig_name, (x_vec, y_vec) in waveforms.items():
            self.signals[sig_name] = WaveformVector(x_vec, y_vec, name=sig_name)

    def v(self, net_name: str) -> WaveformVector:
        """Get voltage waveform vector for a net."""
        candidates = [net_name, f"v({net_name})", f"V({net_name})", f"/{net_name}"]
        for c in candidates:
            if c in self.signals:
                return self.signals[c]
        raise KeyError(f"Waveform signal '{net_name}' not found in simulation results.")

    def signal(self, name: str) -> WaveformVector:
        """Get a waveform vector by exact or case-insensitive signal name."""
        text = str(name or "").strip()
        if text in self.signals:
            return self.signals[text]
        lower_map = {key.lower(): key for key in self.signals}
        hit = lower_map.get(text.lower())
        if hit:
            return self.signals[hit]
        raise KeyError(f"Waveform signal '{name}' not found in simulation results.")

    def bandwidth_3db(self, net_name: str) -> float:
        """Calculate 3dB bandwidth from AC frequency response vector."""
        vec = self.v(net_name)
        if not vec.x or not vec.y:
            return 0.0

        max_val = vec.max_value()
        target_val = max_val - 3.0  # Assumes y is in dB, or max_val / sqrt(2)

        for i in range(len(vec.y) - 1):
            if vec.y[i] >= target_val >= vec.y[i + 1] or vec.y[i] <= target_val <= vec.y[i + 1]:
                # Linear interpolation
                x1, x2 = vec.x[i], vec.x[i + 1]
                y1, y2 = vec.y[i], vec.y[i + 1]
                if y2 == y1:
                    return x1
                return x1 + (target_val - y1) * (x2 - x1) / (y2 - y1)
        return vec.x[-1]

    def rise_time(self, net_name: str, low_pct: float = 0.1, high_pct: float = 0.9) -> float:
        """Calculate 10%-90% rise time."""
        vec = self.v(net_name)
        if len(vec) < 2:
            return 0.0

        min_val = vec.min_value()
        max_val = vec.max_value()
        v_low = min_val + (max_val - min_val) * low_pct
        v_high = min_val + (max_val - min_val) * high_pct

        t_low, t_high = None, None
        for i in range(len(vec) - 1):
            if t_low is None and vec.y[i] <= v_low <= vec.y[i + 1]:
                t_low = vec.x[i] + (v_low - vec.y[i]) * (vec.x[i + 1] - vec.x[i]) / (vec.y[i + 1] - vec.y[i])
            if t_high is None and vec.y[i] <= v_high <= vec.y[i + 1]:
                t_high = vec.x[i] + (v_high - vec.y[i]) * (vec.x[i + 1] - vec.x[i]) / (vec.y[i + 1] - vec.y[i])

        if t_low is not None and t_high is not None:
            return abs(t_high - t_low)
        return 0.0

    def propagation_delay(self, in_net: str, out_net: str, threshold_pct: float = 0.5) -> float:
        """Calculate propagation delay between input and output crossing threshold."""
        v_in = self.v(in_net)
        v_out = self.v(out_net)

        th_in = v_in.min_value() + (v_in.max_value() - v_in.min_value()) * threshold_pct
        th_out = v_out.min_value() + (v_out.max_value() - v_out.min_value()) * threshold_pct

        t_in, t_out = None, None
        for i in range(len(v_in) - 1):
            if t_in is None and (v_in.y[i] <= th_in <= v_in.y[i + 1] or v_in.y[i] >= th_in >= v_in.y[i + 1]):
                t_in = v_in.x[i]
                break

        for i in range(len(v_out) - 1):
            if t_out is None and (v_out.y[i] <= th_out <= v_out.y[i + 1] or v_out.y[i] >= th_out >= v_out.y[i + 1]):
                t_out = v_out.x[i]
                break

        if t_in is not None and t_out is not None:
            return abs(t_out - t_in)
        return 0.0

    def scalar(self, net_name: str, metric: str = "final") -> float:
        """Return an ADE-style scalar metric for one waveform."""
        vec = self.v(net_name)
        key = str(metric or "final").strip().lower()
        if key in {"final", "last"}:
            return vec.final_value()
        if key == "min":
            return vec.min_value()
        if key == "max":
            return vec.max_value()
        if key in {"mean", "avg", "average"}:
            return vec.mean()
        if key in {"pp", "peak_to_peak", "peak-to-peak"}:
            return vec.peak_to_peak()
        if key == "rms":
            return vec.rms()
        raise ValueError(f"Unsupported scalar metric: {metric}")

    def value_at(self, net_name: str, x_value: float) -> float:
        """Return a waveform value at a time/frequency point."""
        return self.v(net_name).value_at(float(x_value))

    def gain_db(self, out_net: str, in_net: str) -> WaveformVector:
        """Return AC voltage gain in dB across frequency."""
        vout = self.v(out_net)
        vin = self.v(in_net)
        n = min(len(vout.x), len(vout.y), len(vin.y))
        y = []
        for out_v, in_v in zip(vout.y[:n], vin.y[:n]):
            ratio = abs(out_v / in_v) if in_v else math.nan
            y.append(20.0 * math.log10(ratio) if ratio > 0.0 else math.nan)
        return WaveformVector(vout.x[:n], y, name=f"gain_db({out_net},{in_net})")

    def gain_db_at(self, out_net: str, in_net: str, frequency: float) -> float:
        """Return interpolated AC voltage gain in dB at frequency."""
        return self.gain_db(out_net, in_net).value_at(float(frequency))

    def sparam_db(self, name: str) -> WaveformVector:
        """Return S-parameter magnitude in dB for a real magnitude vector."""
        vec = self.signal(name)
        y = [20.0 * math.log10(abs(value)) if value else math.nan for value in vec.y]
        return WaveformVector(vec.x[:], y, name=f"{name}_db")

    def sparam_db_at(self, name: str, frequency: float) -> float:
        """Return interpolated S-parameter magnitude in dB at frequency."""
        return self.sparam_db(name).value_at(float(frequency))

    def _complex_signal(self, name: str) -> list[complex]:
        mag = self.signal(name)
        phase_name = f"phase({name})"
        try:
            phase = self.signal(phase_name)
        except KeyError:
            return [complex(value, 0.0) for value in mag.y]
        n = min(len(mag.y), len(phase.y))
        return [
            complex(mag.y[i] * math.cos(math.radians(phase.y[i])), mag.y[i] * math.sin(math.radians(phase.y[i])))
            for i in range(n)
        ]

    def stability_k_factor(self, s11: str = "S11", s12: str = "S12", s21: str = "S21", s22: str = "S22") -> WaveformVector:
        """Return Rollet K factor from two-port S-parameters."""
        axis = self.signal(s11).x
        a11, a12, a21, a22 = (self._complex_signal(name) for name in (s11, s12, s21, s22))
        n = min(len(axis), len(a11), len(a12), len(a21), len(a22))
        y = []
        for v11, v12, v21, v22 in zip(a11[:n], a12[:n], a21[:n], a22[:n]):
            delta = v11 * v22 - v12 * v21
            denom = 2.0 * abs(v12 * v21)
            y.append((1.0 - abs(v11) ** 2 - abs(v22) ** 2 + abs(delta) ** 2) / denom if denom else math.inf)
        return WaveformVector(axis[:n], y, name="stability_k")

    def mu_factor(self, s11: str = "S11", s12: str = "S12", s21: str = "S21", s22: str = "S22") -> WaveformVector:
        """Return Edwards-Sinsky mu stability factor."""
        axis = self.signal(s11).x
        a11, a12, a21, a22 = (self._complex_signal(name) for name in (s11, s12, s21, s22))
        n = min(len(axis), len(a11), len(a12), len(a21), len(a22))
        y = []
        for v11, v12, v21, v22 in zip(a11[:n], a12[:n], a21[:n], a22[:n]):
            delta = v11 * v22 - v12 * v21
            denom = abs(v22 - delta * v11.conjugate()) + abs(v12 * v21)
            y.append((1.0 - abs(v11) ** 2) / denom if denom else math.inf)
        return WaveformVector(axis[:n], y, name="mu_factor")

    def input_match_gamma(self, gamma_load: complex = 0.0, s11: str = "S11", s12: str = "S12", s21: str = "S21", s22: str = "S22") -> tuple[WaveformVector, WaveformVector]:
        """Return conjugate source match target from a load reflection coefficient."""
        axis = self.signal(s11).x
        a11, a12, a21, a22 = (self._complex_signal(name) for name in (s11, s12, s21, s22))
        n = min(len(axis), len(a11), len(a12), len(a21), len(a22))
        targets = []
        for v11, v12, v21, v22 in zip(a11[:n], a12[:n], a21[:n], a22[:n]):
            denom = 1.0 - v22 * gamma_load
            gamma_in = v11 + (v12 * v21 * gamma_load / denom if denom else complex(math.nan, math.nan))
            targets.append(gamma_in.conjugate())
        return (
            WaveformVector(axis[:n], [abs(value) for value in targets], name="gamma_source_match"),
            WaveformVector(axis[:n], [math.degrees(math.atan2(value.imag, value.real)) for value in targets], name="phase(gamma_source_match)"),
        )

    def output_match_gamma(self, gamma_source: complex = 0.0, s11: str = "S11", s12: str = "S12", s21: str = "S21", s22: str = "S22") -> tuple[WaveformVector, WaveformVector]:
        """Return conjugate load match target from a source reflection coefficient."""
        axis = self.signal(s11).x
        a11, a12, a21, a22 = (self._complex_signal(name) for name in (s11, s12, s21, s22))
        n = min(len(axis), len(a11), len(a12), len(a21), len(a22))
        targets = []
        for v11, v12, v21, v22 in zip(a11[:n], a12[:n], a21[:n], a22[:n]):
            denom = 1.0 - v11 * gamma_source
            gamma_out = v22 + (v12 * v21 * gamma_source / denom if denom else complex(math.nan, math.nan))
            targets.append(gamma_out.conjugate())
        return (
            WaveformVector(axis[:n], [abs(value) for value in targets], name="gamma_load_match"),
            WaveformVector(axis[:n], [math.degrees(math.atan2(value.imag, value.real)) for value in targets], name="phase(gamma_load_match)"),
        )

    def transducer_gain_db(
        self,
        gamma_source: complex = 0.0,
        gamma_load: complex = 0.0,
        s11: str = "S11",
        s12: str = "S12",
        s21: str = "S21",
        s22: str = "S22",
    ) -> WaveformVector:
        """Return two-port transducer gain in dB for source/load reflection coefficients."""
        axis = self.signal(s11).x
        a11, a12, a21, a22 = (self._complex_signal(name) for name in (s11, s12, s21, s22))
        n = min(len(axis), len(a11), len(a12), len(a21), len(a22))
        y = []
        for v11, v12, v21, v22 in zip(a11[:n], a12[:n], a21[:n], a22[:n]):
            denom = abs((1.0 - v11 * gamma_source) * (1.0 - v22 * gamma_load) - v12 * v21 * gamma_source * gamma_load) ** 2
            gain = abs(v21) ** 2 * (1.0 - abs(gamma_source) ** 2) * (1.0 - abs(gamma_load) ** 2) / denom if denom else math.nan
            y.append(10.0 * math.log10(gain) if gain > 0.0 else math.nan)
        return WaveformVector(axis[:n], y, name="transducer_gain_db")

    def noise_figure_from_params_db(
        self,
        nfmin_db: str = "NFmin(dB)",
        rn_ohm: str = "Rn(ohm)",
        gamma_opt_mag: str = "Gammaopt",
        gamma_source: complex = 0.0,
        gamma_opt_phase: str = "phase(Gammaopt)",
        z0: float = 50.0,
    ) -> WaveformVector:
        """Return noise figure from swept NFmin/Rn/Gammaopt noise parameters."""
        nfmin = self.signal(nfmin_db)
        rn = self.signal(rn_ohm)
        gopt = self.signal(gamma_opt_mag)
        try:
            gopt_phase = self.signal(gamma_opt_phase)
        except KeyError:
            gopt_phase = WaveformVector(gopt.x, [0.0] * len(gopt.y), gamma_opt_phase)
        n = min(len(nfmin.x), len(nfmin.y), len(rn.y), len(gopt.y), len(gopt_phase.y))
        y = [
            noise_figure_from_params_db(nf, r, polar_to_complex(gm, gp), gamma_source, z0)
            for nf, r, gm, gp in zip(nfmin.y[:n], rn.y[:n], gopt.y[:n], gopt_phase.y[:n])
        ]
        return WaveformVector(nfmin.x[:n], y, name="noise_figure_db")

    def stability_circle_radius(self, plane: str = "source", s11: str = "S11", s12: str = "S12", s21: str = "S21", s22: str = "S22") -> WaveformVector:
        """Return source/load stability-circle radius across frequency."""
        axis = self.signal(s11).x
        a11, a12, a21, a22 = (self._complex_signal(name) for name in (s11, s12, s21, s22))
        n = min(len(axis), len(a11), len(a12), len(a21), len(a22))
        y = [stability_circle(v11, v12, v21, v22, plane)[1] for v11, v12, v21, v22 in zip(a11[:n], a12[:n], a21[:n], a22[:n])]
        return WaveformVector(axis[:n], y, name=f"{plane}_stability_radius")

    def stability_circle_center(self, plane: str = "source", part: str = "mag", s11: str = "S11", s12: str = "S12", s21: str = "S21", s22: str = "S22") -> WaveformVector:
        """Return source/load stability-circle center magnitude or phase."""
        axis = self.signal(s11).x
        a11, a12, a21, a22 = (self._complex_signal(name) for name in (s11, s12, s21, s22))
        n = min(len(axis), len(a11), len(a12), len(a21), len(a22))
        centers = [stability_circle(v11, v12, v21, v22, plane)[0] for v11, v12, v21, v22 in zip(a11[:n], a12[:n], a21[:n], a22[:n])]
        if str(part).lower().startswith("phase"):
            y = [math.degrees(math.atan2(value.imag, value.real)) for value in centers]
        else:
            y = [abs(value) for value in centers]
        return WaveformVector(axis[:n], y, name=f"{plane}_stability_center_{part}")

    def return_loss_db(self, name: str = "S11") -> WaveformVector:
        """Return positive return loss in dB from an S-parameter magnitude."""
        s_db = self.sparam_db(name)
        return WaveformVector(s_db.x[:], [-value if math.isfinite(value) else value for value in s_db.y], name=f"return_loss_db({name})")

    def return_loss_db_at(self, name: str = "S11", frequency: float = 0.0) -> float:
        """Return interpolated positive return loss in dB at frequency."""
        return self.return_loss_db(name).value_at(float(frequency))

    def vswr(self, name: str = "S11") -> WaveformVector:
        """Return voltage standing-wave ratio from reflection coefficient magnitude."""
        gamma = self.signal(name)
        y = []
        for value in gamma.y:
            mag = abs(value)
            y.append((1.0 + mag) / (1.0 - mag) if mag < 1.0 else math.inf)
        return WaveformVector(gamma.x[:], y, name=f"vswr({name})")

    def impedance_from_gamma(self, name: str = "S11", z0: float = 50.0) -> tuple[WaveformVector, WaveformVector]:
        """Return resistance/reactance vectors from an S-parameter reflection coefficient."""
        mag = self.signal(name)
        values = self._complex_signal(name)
        n = min(len(mag.x), len(values))
        z_values = [gamma_to_impedance(gamma, z0) for gamma in values[:n]]
        return (
            WaveformVector(mag.x[:n], [z.real for z in z_values], name=f"real_z({name})"),
            WaveformVector(mag.x[:n], [z.imag for z in z_values], name=f"imag_z({name})"),
        )

    def admittance_from_gamma(self, name: str = "S11", z0: float = 50.0) -> tuple[WaveformVector, WaveformVector]:
        """Return conductance/susceptance vectors from an S-parameter reflection coefficient."""
        mag = self.signal(name)
        values = self._complex_signal(name)
        n = min(len(mag.x), len(values))
        y_values = [gamma_to_admittance(gamma, z0) for gamma in values[:n]]
        return (
            WaveformVector(mag.x[:n], [value.real for value in y_values], name=f"real_y({name})"),
            WaveformVector(mag.x[:n], [value.imag for value in y_values], name=f"imag_y({name})"),
        )

    def pae_percent(self, pout_w: str = "Pout(W)", pin_w: str = "Pin(W)", pdc_w: str = "Pdc(W)") -> WaveformVector:
        """Return power-added efficiency from RF output/input and DC power in watts."""
        pout = self.signal(pout_w)
        pin = self.signal(pin_w)
        pdc = self.signal(pdc_w)
        n = min(len(pout.x), len(pout.y), len(pin.y), len(pdc.y))
        y = [
            100.0 * (out_v - in_v) / dc_v if dc_v else math.nan
            for out_v, in_v, dc_v in zip(pout.y[:n], pin.y[:n], pdc.y[:n])
        ]
        return WaveformVector(pout.x[:n], y, name="pae_percent")

    def p1db_input_dbm(self, pin_dbm: str = "Pin(dBm)", pout_dbm: str = "Pout(dBm)") -> float:
        """Return input power at 1 dB compression from swept Pin/Pout dBm vectors."""
        pin = self.signal(pin_dbm)
        pout = self.signal(pout_dbm)
        n = min(len(pin.y), len(pout.y))
        if n < 2:
            return math.nan
        small_signal_gain = pout.y[0] - pin.y[0]
        compression = [(pout.y[i] - pin.y[i]) - small_signal_gain for i in range(n)]
        for i in range(n - 1):
            c0, c1 = compression[i], compression[i + 1]
            if c0 >= -1.0 >= c1 or c0 <= -1.0 <= c1:
                p0, p1 = pin.y[i], pin.y[i + 1]
                return p0 if c1 == c0 else p0 + (-1.0 - c0) * (p1 - p0) / (c1 - c0)
        return math.nan

    def output_ip3_dbm(self, fundamental_dbm: str = "Pfund(dBm)", im3_dbm: str = "Pim3(dBm)") -> WaveformVector:
        """Return output IP3 estimate from fundamental and IM3 output power vectors."""
        fund = self.signal(fundamental_dbm)
        im3 = self.signal(im3_dbm)
        n = min(len(fund.x), len(fund.y), len(im3.y))
        y = [f + 0.5 * (f - i3) for f, i3 in zip(fund.y[:n], im3.y[:n])]
        return WaveformVector(fund.x[:n], y, name="OIP3_dBm")

    def input_ip3_dbm(self, pin_dbm: str = "Pin(dBm)", fundamental_dbm: str = "Pfund(dBm)", im3_dbm: str = "Pim3(dBm)") -> WaveformVector:
        """Return input IP3 estimate from input, fundamental, and IM3 power vectors."""
        pin = self.signal(pin_dbm)
        fund = self.signal(fundamental_dbm)
        im3 = self.signal(im3_dbm)
        n = min(len(pin.x), len(pin.y), len(fund.y), len(im3.y))
        y = [p + 0.5 * (f - i3) for p, f, i3 in zip(pin.y[:n], fund.y[:n], im3.y[:n])]
        return WaveformVector(pin.x[:n], y, name="IIP3_dBm")

    def optimum_gamma(self, metric: str, gamma_mag: str = "GammaL", gamma_phase: str = "phase(GammaL)") -> dict[str, float]:
        """Return the swept reflection coefficient that maximizes a metric."""
        metric_vec = self.signal(metric)
        gamma = self.signal(gamma_mag)
        try:
            phase = self.signal(gamma_phase)
        except KeyError:
            phase = WaveformVector(gamma.x, [0.0] * len(gamma.y), gamma_phase)
        n = min(len(metric_vec.y), len(gamma.y), len(phase.y))
        best = None
        for i in range(n):
            value = metric_vec.y[i]
            if isinstance(value, (int, float)) and math.isfinite(value) and (best is None or value > best[0]):
                best = (value, gamma.y[i], phase.y[i], metric_vec.x[i] if i < len(metric_vec.x) else float(i))
        if best is None:
            return {"metric": math.nan, "gamma": math.nan, "phase": math.nan, "x": math.nan}
        return {"metric": best[0], "gamma": best[1], "phase": best[2], "x": best[3]}

    def lna_noise_figure_db(
        self,
        out_net: str,
        in_net: str,
        onoise_psd_signal: str = "onoise_psd(V^2/Hz)",
        source_resistance: float = 50.0,
        temperature: float = 300.0,
    ) -> WaveformVector:
        """Approximate input-referred NF from output noise PSD and voltage gain."""
        vout = self.v(out_net)
        vin = self.v(in_net)
        noise = self.v(onoise_psd_signal)
        n = min(len(vout.x), len(vout.y), len(vin.y), len(noise.y))
        k_boltzmann = 1.380649e-23
        source_noise_psd = 4.0 * k_boltzmann * float(temperature) * float(source_resistance)
        y = []
        for out_v, in_v, noise_psd in zip(vout.y[:n], vin.y[:n], noise.y[:n]):
            gain = abs(out_v / in_v) if in_v else math.nan
            referred = noise_psd / (gain * gain) if gain and gain > 0.0 else math.nan
            factor = referred / source_noise_psd if source_noise_psd > 0.0 else math.nan
            y.append(10.0 * math.log10(factor) if factor > 0.0 else math.nan)
        return WaveformVector(vout.x[:n], y, name=f"nf_db({out_net},{in_net})")

    def lna_noise_figure_db_at(
        self,
        out_net: str,
        in_net: str,
        frequency: float,
        onoise_psd_signal: str = "onoise_psd(V^2/Hz)",
        source_resistance: float = 50.0,
        temperature: float = 300.0,
    ) -> float:
        """Return approximate input-referred NF in dB at frequency."""
        return self.lna_noise_figure_db(
            out_net,
            in_net,
            onoise_psd_signal,
            source_resistance,
            temperature,
        ).value_at(float(frequency))

    def crossing_time(self, net_name: str, threshold: float, edge: str = "either") -> float:
        """Return the first interpolated threshold crossing time."""
        vec = self.v(net_name)
        edge = str(edge or "either").strip().lower()
        for i in range(len(vec.y) - 1):
            y1, y2 = vec.y[i], vec.y[i + 1]
            rising = y1 <= threshold <= y2 and y2 != y1
            falling = y1 >= threshold >= y2 and y2 != y1
            if edge == "rising" and not rising:
                continue
            if edge == "falling" and not falling:
                continue
            if edge not in {"rising", "falling"} and not (rising or falling):
                continue
            return vec.x[i] + (threshold - y1) * (vec.x[i + 1] - vec.x[i]) / (y2 - y1)
        return 0.0

    def clip(self, net_name: str, t_start: float, t_stop: float) -> WaveformVector:
        """Clip waveform to range [t_start, t_stop]."""
        vec = self.v(net_name)
        new_x, new_y = [], []
        for xi, yi in zip(vec.x, vec.y):
            if t_start <= xi <= t_stop:
                new_x.append(xi)
                new_y.append(yi)
        return WaveformVector(new_x, new_y, name=f"clip({vec.name},{t_start},{t_stop})")

    def deriv(self, net_name: str) -> WaveformVector:
        """Calculate derivative dy/dx."""
        vec = self.v(net_name)
        if len(vec) < 2:
            return WaveformVector([], [], name=f"deriv({vec.name})")
        dx_arr, dy_arr = [], []
        for i in range(len(vec) - 1):
            dx = vec.x[i + 1] - vec.x[i]
            dy = vec.y[i + 1] - vec.y[i]
            if dx != 0:
                dx_arr.append(vec.x[i])
                dy_arr.append(dy / dx)
        return WaveformVector(dx_arr, dy_arr, name=f"deriv({vec.name})")

    def integ(self, net_name: str) -> WaveformVector:
        """Calculate integral integral(y dx) using trapezoidal rule."""
        vec = self.v(net_name)
        if len(vec) < 2:
            return WaveformVector([], [], name=f"integ({vec.name})")
        ix_arr, iy_arr = [vec.x[0]], [0.0]
        acc = 0.0
        for i in range(len(vec) - 1):
            dx = vec.x[i + 1] - vec.x[i]
            avg_y = (vec.y[i + 1] + vec.y[i]) / 2.0
            acc += avg_y * dx
            ix_arr.append(vec.x[i + 1])
            iy_arr.append(acc)
        return WaveformVector(ix_arr, iy_arr, name=f"integ({vec.name})")

    def eye_diagram(self, net_name: str, symbol_period: float) -> List[WaveformVector]:
        """Fold transient waveform by symbol_period T to construct Eye Diagram traces."""
        vec = self.v(net_name)
        if not vec.x or symbol_period <= 0:
            return []

        traces = []
        start_t = vec.x[0]
        end_t = vec.x[-1]

        t_curr = start_t
        idx = 0
        while t_curr + 2 * symbol_period <= end_t:
            segment_x, segment_y = [], []
            t_win_end = t_curr + 2 * symbol_period
            while idx < len(vec) and vec.x[idx] <= t_win_end:
                rel_x = vec.x[idx] - t_curr
                segment_x.append(rel_x)
                segment_y.append(vec.y[idx])
                idx += 1

            if segment_x:
                traces.append(WaveformVector(segment_x, segment_y, name=f"eye_{len(traces)}"))
            t_curr += symbol_period
            # rewinding index to overlap
            while idx > 0 and vec.x[idx - 1] >= t_curr:
                idx -= 1

        return traces
