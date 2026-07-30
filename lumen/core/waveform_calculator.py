"""
Lumen Circuit Studio — Waveform Expression Calculator Engine

Provides ADE/Viva-class waveform calculator functions (bandwidth, rise_time,
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


class WaveformCalculator:
    """Waveform expression evaluator for ADE/SigView."""

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
