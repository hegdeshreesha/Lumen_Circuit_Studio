"""
Lumen Circuit Studio — ADE Engine (Analog Design Environment Core)

Advanced simulation management engine with:
- Simulation state management (save/load .sim files)
- Ocean-like Python scripting API
- Multi-run history with hierarchical result storage
- Expression calculator (NumPy-based waveform math)
- Corner + Parametric sweep cascading
- Convergence advisor
- Direct waveform plotting integration
"""
import json
import os
import time
import copy
import threading
import re
import random
from dataclasses import dataclass, field, asdict
from typing import Optional, Callable
from enum import Enum

from lumen.core.database import LibraryDatabase
from lumen.core.netlist import NetlistGenerator, NetlistDirectives
from lumen.core.simulator import SimulatorBridge, SimulationResult
from lumen.core.simulator_runtime import ACTIVE_SIMULATORS
from lumen.core.results_store import ResultsStore, RunManifest, hash_text, hash_files
from lumen.core.pss import build_pss_statement


# ── Analysis Types ─────────────────────────────────────────────

class AnalysisType(Enum):
    OP = ".OP"
    TRAN = ".TRAN"
    AC = ".AC"
    DC = ".DC"
    NOISE = ".NOISE"
    PSS = ".PSS"
    HB = ".HB"
    SP = ".SP"
    PAC = ".PAC"
    PNOISE = ".PNOISE"
    HBAC = ".HBAC"
    HBNOISE = ".HBNOISE"
    HBSP = ".HBSP"
    STB = ".STB"
    HBSTB = ".HBSTB"
    PSSSTB = ".PSSSTB"


ANALYSIS_DEFAULTS = {
    AnalysisType.OP: {},
    AnalysisType.TRAN: {"step": "", "stop": "10u", "start": "0", "maxstep": "", "uic": False},
    AnalysisType.AC: {"bias_op": True, "sweep": "DEC", "points": "100", "fstart": "1", "fstop": "10G"},
    AnalysisType.DC: {"source": "V1", "start": "0", "stop": "1.8", "step": "10m"},
    AnalysisType.NOISE: {"output": "V(out)", "source": "V1", "points": "50",
                         "fstart": "1", "fstop": "1G"},
    AnalysisType.PSS: {
        "mode": "driven",
        "fund": "1G",
        "harmonics": "7",
        "tstab": "",
        "tstab_periods": "",
        "pss_adaptive": False,
        "pss_continuation": False,
        "pss_use_ic": False,
        "pss_continuation_steps": "",
        "pss_residual_goal": "",
    },
    AnalysisType.HB: {"freq": "1G", "harmonics": "7", "maxiter": "100"},
    AnalysisType.SP: {"sweep": "LIN", "points": "201", "fstart": "100M", "fstop": "10G"},
}


@dataclass
class AnalysisSetup:
    """Configuration for a single analysis."""
    analysis_type: AnalysisType
    enabled: bool = True
    params: dict = field(default_factory=dict)

    def to_spice(self) -> str:
        """Generate SPICE analysis statement."""
        cmd = self.analysis_type.value
        params = dict(self.params)

        if self.analysis_type == AnalysisType.OP:
            return cmd

        if self.analysis_type == AnalysisType.TRAN:
            parts = [cmd]
            parts.append(str(params.get("step", "") or "20p"))
            parts.append(str(params.get("stop", "") or "10u"))
            start = str(params.get("start", "") or "0").strip()
            maxstep = str(params.get("maxstep", "") or "").strip()
            if start != "0" or maxstep:
                parts.append(start)
            if maxstep:
                parts.append(maxstep)
            if params.get("uic", False):
                parts.append("UIC")
            return " ".join(parts)

        if self.analysis_type == AnalysisType.AC:
            sweep = params.get("sweep", "DEC")
            points = params.get("points", "100")
            fstart = params.get("fstart", "1")
            fstop = params.get("fstop", "10G")
            ac_line = f"{cmd} {sweep} {points} {fstart} {fstop}"
            return f".OP\n{ac_line}" if params.get("bias_op", True) else ac_line

        if self.analysis_type == AnalysisType.DC:
            src = params.get("source", "V1")
            start = params.get("start", "0")
            stop = params.get("stop", "1.8")
            step = params.get("step", "10m")
            return f"{cmd} {src} {start} {stop} {step}"

        if self.analysis_type == AnalysisType.NOISE:
            output = params.get("output", "V(out)")
            source = params.get("source", "V1")
            points = params.get("points", "50")
            fstart = params.get("fstart", "1")
            fstop = params.get("fstop", "1G")
            return f"{cmd} V({output}) {source} {points} {fstart} {fstop}"

        if self.analysis_type == AnalysisType.PSS:
            return build_pss_statement(params, cmd)

        if self.analysis_type == AnalysisType.HB:
            freq = params.get("freq", "1G")
            harms = params.get("harmonics", "7")
            return f"{cmd} {freq} {harms}"

        # Fallback: key=value pairs
        parts = [cmd]
        for k, v in params.items():
            parts.append(f"{k}={v}")
        return " ".join(parts)


# ── Simulation State ──────────────────────────────────────────

@dataclass
class CornerConfig:
    """A single process/temperature corner."""
    name: str
    temperature: float = 25.0
    voltage: float = 1.8
    process: str = "tt"
    lib_section: str = ""
    enabled: bool = True


@dataclass
class SweepConfig:
    """A parametric sweep variable."""
    variable: str
    start: str = "0"
    stop: str = "1.8"
    step: str = "0.1"
    nested: bool = False
    enabled: bool = True


@dataclass
class OutputConfig:
    """An output expression to save/measure."""
    name: str
    expression: str
    enabled: bool = True
    plot: bool = True


@dataclass
class SimulationState:
    """
    Complete simulation setup state.
    Can be serialized to/from .sim files.
    """
    # Design info
    library: str = ""
    cell: str = ""
    view: str = "schematic"
    description: str = ""

    # Simulator
    simulator: str = "GSPICE"
    simulator_path: str = ""
    threads: int = 4
    timeout: int = 300

    # Analyses
    analyses: list[AnalysisSetup] = field(default_factory=list)

    # Corners
    corners: list[CornerConfig] = field(default_factory=list)
    corner_mode: str = "single"  # single, all, selected

    # Sweeps
    sweeps: list[SweepConfig] = field(default_factory=list)

    # Outputs
    outputs: list[OutputConfig] = field(default_factory=list)

    # Design variables
    design_variables: dict[str, str] = field(default_factory=dict)

    # PDK
    pdk_name: str = ""
    pdk_corner: str = ""

    # Convergence helpers
    nodesets: list[str] = field(default_factory=list)
    ics: list[str] = field(default_factory=list)

    # SPICE options
    options: dict[str, str] = field(default_factory=lambda: {
        "ACCURACY": "HIGH",
        "ADAPTIVE": "1",
        "RELTOL": "3e-4",
        "VNTOL": "300n",
        "ABSTOL": "100f",
        "TRTOL": "1",
        "LTE_RELTOL": "1e-3",
        "TRABSTOL": "300n",
        "ITL4": "80",
    })

    # Measurements
    measures: list[str] = field(default_factory=list)

    # Monte Carlo
    mc_runs: int = 0
    mc_type: str = "DC"
    mc_expression: str = ""

    # Metadata
    created: float = 0.0
    modified: float = 0.0
    run_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SimulationState":
        state = cls()
        for key, value in data.items():
            if hasattr(state, key):
                if key == "analyses":
                    state.analyses = [AnalysisSetup(**a) if isinstance(a, dict) else a
                                      for a in value]
                elif key == "corners":
                    state.corners = [CornerConfig(**c) if isinstance(c, dict) else c
                                     for c in value]
                elif key == "sweeps":
                    state.sweeps = [SweepConfig(**s) if isinstance(s, dict) else s
                                    for s in value]
                elif key == "outputs":
                    state.outputs = [OutputConfig(**o) if isinstance(o, dict) else o
                                     for o in value]
                else:
                    setattr(state, key, value)
        return state


# ── Run Result ────────────────────────────────────────────────

@dataclass
class RunRecord:
    """A single simulation run result."""
    run_id: str
    corner_name: str
    sweep_values: dict
    analysis: str
    timestamp: float
    success: bool
    netlist_path: str
    output_path: str
    log: str
    errors: list[str]
    elapsed_time: float
    waveforms: dict  # signal_name -> list[float]
    waveforms_x: dict  # signal_name -> list[float] (x-axis)


# ── Expression Calculator ─────────────────────────────────────

class ExpressionCalculator:
    """
    NumPy-based waveform expression calculator.
    Supports: V(node), I(source), dB(), phase(), group_delay(),
    abs(), real(), imag(), fft(), deriv(), integ(), +, -, *, /, math functions.
    """

    def __init__(self):
        self._numpy = None  # Lazy import

    def _ensure_numpy(self):
        if self._numpy is None:
            try:
                import numpy as np
                self._numpy = np
            except ImportError:
                raise ImportError("NumPy required for expression calculator. "
                                  "Install with: pip install numpy")

    def evaluate(self, expression: str, waveforms: dict) -> Optional[dict]:
        """
        Evaluate a mathematical expression on waveform data.
        
        Args:
            expression: e.g., "dB(V(out))", "V(out)/V(in)", "phase(V(out))"
            waveforms: Dict of signal_name -> list of y-values
            
        Returns:
            Dict with "x" and "y" keys, or None if evaluation fails.
        """
        self._ensure_numpy()
        np = self._numpy

        # Basic cases
        expr = expression.strip()

        # Direct signal reference
        if expr in waveforms:
            x_data = self._find_x_axis(waveforms)
            return {"x": x_data, "y": waveforms[expr], "name": expr}

        # V(node) / I(source) pattern
        v_match = re.match(r'^V\((\w+)\)$', expr)
        if v_match:
            node = v_match.group(1)
            if expr in waveforms:
                x_data = self._find_x_axis(waveforms)
                return {"x": x_data, "y": waveforms[expr], "name": expr}
            # Try other naming conventions
            for key in waveforms:
                if node in key:
                    x_data = self._find_x_axis(waveforms)
                    return {"x": x_data, "y": waveforms[key], "name": expr}
            return None

        i_match = re.match(r'^I\((\w+)\)$', expr)
        if i_match:
            src = i_match.group(1)
            for key in waveforms:
                if src in key and ("i" in key.lower() or "I" in key):
                    x_data = self._find_x_axis(waveforms)
                    return {"x": x_data, "y": waveforms[key], "name": expr}
            return None

        # Nested function calls: fn(signal)
        func_match = re.match(r'(\w+)\((.+)\)$', expr)
        if func_match:
            func_name = func_match.group(1).lower()
            inner = func_match.group(2)

            # Evaluate inner expression recursively
            inner_result = self.evaluate(inner, waveforms)
            if inner_result is None:
                return None

            y = np.array(inner_result["y"])
            x = inner_result["x"]

            # Apply function
            if func_name == "db" or func_name == "dB":
                y_result = 20 * np.log10(np.maximum(np.abs(y), 1e-30))
            elif func_name == "phase":
                y_result = np.angle(y, deg=True)
            elif func_name == "abs":
                y_result = np.abs(y)
            elif func_name == "real":
                y_result = np.real(y)
            elif func_name == "imag":
                y_result = np.imag(y)
            elif func_name == "deriv" or func_name == "derivative":
                y_result = np.gradient(y, x)
            elif func_name == "integ" or func_name == "integral":
                y_result = np.cumsum(y) * (x[1] - x[0]) if len(x) > 1 else y
            elif func_name == "fft":
                n = len(y)
                freq = np.fft.fftfreq(n, d=(x[1] - x[0]) if len(x) > 1 else 1)
                y_result = np.fft.fft(y)
                # Return positive frequencies only
                pos = freq >= 0
                x = freq[pos]
                y_result = np.abs(y_result[pos])
            elif func_name == "neg" or func_name == "negative":
                y_result = -y
            elif func_name == "delay" or func_name == "group_delay":
                # Simple group delay approximation
                phase = np.unwrap(np.angle(y))
                y_result = -np.gradient(phase, x) / (2 * np.pi)
            elif func_name == "sqrt":
                y_result = np.sqrt(np.abs(y))
            elif func_name == "sin":
                y_result = np.sin(y)
            elif func_name == "cos":
                y_result = np.cos(y)
            elif func_name == "tan":
                y_result = np.tan(y)
            elif func_name == "exp":
                y_result = np.exp(y)
            elif func_name == "log":
                y_result = np.log(np.maximum(np.abs(y), 1e-30))
            elif func_name == "log10":
                y_result = np.log10(np.maximum(np.abs(y), 1e-30))
            else:
                return None

            return {"x": x, "y": y_result.tolist(), "name": expr}

        # Binary operators: A - B, A / B, A * B
        for op, np_op in [("+", np.add), ("-", np.subtract),
                          ("*", np.multiply), ("/", np.divide)]:
            if op in expr:
                parts = expr.split(op, 1)
                left = self.evaluate(parts[0].strip(), waveforms)
                right = self.evaluate(parts[1].strip(), waveforms)
                if left is not None and right is not None:
                    ly = np.array(left["y"])
                    ry = np.array(right["y"])
                    # Pad or truncate to match lengths
                    min_len = min(len(ly), len(ry))
                    y_result = np_op(ly[:min_len], ry[:min_len])
                    return {"x": left["x"][:min_len],
                            "y": y_result.tolist(), "name": expr}
                return None

        # Direct number
        try:
            val = float(expr)
            return {"x": [], "y": [val], "name": expr}
        except ValueError:
            pass

        return None

    def _find_x_axis(self, waveforms: dict) -> list:
        """Find the x-axis data from waveforms."""
        for candidate in ["time", "frequency", "v-sweep", "sweep", "freq"]:
            if candidate in waveforms:
                return waveforms[candidate]
        # Use first signal's length as index
        for name, data in waveforms.items():
            if isinstance(data, list) and len(data) > 0:
                return list(range(len(data)))
        return []


# ── Convergence Advisor ───────────────────────────────────────

class ConvergenceAdvisor:
    """Analyzes simulation failures and suggests fixes."""

    SUGGESTIONS = {
        "singular": "Matrix singular — check for floating nodes, unconnected nets, "
                     "or sources in series with inductors",
        "no dc path": "No DC path to ground — add large resistor (e.g., R=1G) from node to GND",
        "timestep too small": "Timestep too small — increase max timestep or use .OPTIONS ITL=100",
        "iteration limit": "Iteration limit reached — try .OPTIONS ITL=500 or RELTOL=1e-3",
        "convergence": "Convergence failure — try adding .NODESET, .IC, or reducing GMIN steps",
        "timeout": "Simulation timeout — increase timeout or simplify circuit",
        "floating": "Floating node detected — connect all nodes to ground through high resistance",
        "internal": "Internal error — check model file paths and syntax",
    }

    @classmethod
    def analyze(cls, result: SimulationResult) -> list[dict]:
        """Analyze simulation result and return fix suggestions."""
        suggestions = []

        if result.success:
            return suggestions

        log_lower = result.log.lower()

        for keyword, suggestion in cls.SUGGESTIONS.items():
            if keyword in log_lower:
                suggestions.append({
                    "issue": keyword,
                    "suggestion": suggestion,
                    "severity": "high" if keyword in ("singular", "no dc path")
                               else "medium",
                })

        # Add general suggestions if none matched
        if not suggestions:
            if result.errors:
                for err in result.errors:
                    suggestions.append({
                        "issue": "unknown",
                        "suggestion": f"Check error: {err}",
                        "severity": "medium",
                    })
            else:
                suggestions.append({
                    "issue": "unknown",
                    "suggestion": "Check netlist syntax, model paths, and simulation settings",
                    "severity": "low",
                })

        return suggestions


# ── ADE Session ───────────────────────────────────────────────

class ADESession:
    """
    A simulation session — the central ADE object.
    
    Ocean-like usage:
        session = ADESession(db, "my_lib", "amp")
        session.add_analysis(AnalysisType.TRAN, stop="10u")
        session.set_output("vout", "V(out)")
        session.set_output("vin", "V(in)")
        result = session.run()
        session.plot("vout")
    """

    def __init__(self, db: LibraryDatabase, library: str, cell: str,
                 view: str = "schematic"):
        self.db = db
        self.state = SimulationState(
            library=library,
            cell=cell,
            view=view,
            created=time.time(),
        )

        # Results storage
        self._results: dict[str, list[RunRecord]] = {}  # analysis_name -> runs
        self._run_history: list[RunRecord] = []

        # Callbacks
        self._on_run_callback: Optional[Callable] = None
        self._on_progress_callback: Optional[Callable] = None

        # Expression calculator
        self._calc = ExpressionCalculator()

    # PDK registry (lazy)
        self._pdk_registry = None
        self._results_store = ResultsStore(str(getattr(self.db, "workspace", "")))

    def _get_pdk_registry(self):
        if self._pdk_registry is None:
            from lumen.core.pdk_service import get_registry
            workspace = str(getattr(self.db, "workspace", ""))
            self._pdk_registry = get_registry(workspace)
        return self._pdk_registry

    # ── Configuration Methods (Ocean-like API) ────────────────

    def add_analysis(self, analysis_type: AnalysisType, **params) -> "ADESession":
        """Add an analysis to the simulation setup."""
        defaults = dict(ANALYSIS_DEFAULTS.get(analysis_type, {}))
        defaults.update(params)
        self.state.analyses.append(AnalysisSetup(
            analysis_type=analysis_type,
            params=defaults,
        ))
        return self  # Enable chaining: session.add_analysis(...).add_analysis(...)

    def remove_analysis(self, index: int = -1) -> bool:
        """Remove an analysis by index or last one."""
        if self.state.analyses:
            if index < 0:
                self.state.analyses.pop()
            elif index < len(self.state.analyses):
                self.state.analyses.pop(index)
            return True
        return False

    def set_simulator(self, simulator: str = "GSPICE", path: str = "") -> "ADESession":
        self.state.simulator = simulator if simulator in ACTIVE_SIMULATORS else "GSPICE"
        self.state.simulator_path = path if self.state.simulator == simulator else ""
        return self

    def _active_simulator(self) -> tuple[str, str]:
        if self.state.simulator in ACTIVE_SIMULATORS:
            return self.state.simulator, self.state.simulator_path
        self.state.simulator = "GSPICE"
        self.state.simulator_path = ""
        return self.state.simulator, self.state.simulator_path

    def set_threads(self, n: int) -> "ADESession":
        self.state.threads = max(1, min(64, n))
        return self

    def set_timeout(self, seconds: int) -> "ADESession":
        self.state.timeout = max(10, seconds)
        return self

    def set_output(self, name: str, expression: str, plot: bool = True) -> "ADESession":
        """Add an output expression to save."""
        # Remove if already exists
        self.state.outputs = [o for o in self.state.outputs if o.name != name]
        self.state.outputs.append(OutputConfig(name, expression, enabled=True, plot=plot))
        return self

    def remove_output(self, name: str) -> bool:
        old_count = len(self.state.outputs)
        self.state.outputs = [o for o in self.state.outputs if o.name != name]
        return len(self.state.outputs) < old_count

    def add_corner(self, name: str, temperature: float = 25.0,
                   voltage: float = 1.8, process: str = "tt") -> "ADESession":
        self.state.corners.append(CornerConfig(
            name=name, temperature=temperature,
            voltage=voltage, process=process,
        ))
        return self

    def set_corner_mode(self, mode: str) -> "ADESession":
        """Set corner mode: 'single', 'all', or 'selected'."""
        if mode in ("single", "all", "selected"):
            self.state.corner_mode = mode
        return self

    def add_sweep(self, variable: str, start: str = "0",
                  stop: str = "1.8", step: str = "0.1") -> "ADESession":
        self.state.sweeps.append(SweepConfig(variable, start, stop, step))
        return self

    def set_design_variable(self, name: str, value: str) -> "ADESession":
        self.state.design_variables[name] = value
        return self

    def set_pdk(self, name: str, corner: str = "") -> "ADESession":
        self.state.pdk_name = name
        self.state.pdk_corner = corner
        return self

    def add_nodeset(self, node: str, voltage: str) -> "ADESession":
        self.state.nodesets.append(f".NODESET {node}={voltage}")
        return self

    def add_ic(self, node: str, voltage: str) -> "ADESession":
        self.state.ics.append(f".IC {node}={voltage}")
        return self

    def set_option(self, name: str, value: str) -> "ADESession":
        self.state.options[name] = value
        return self

    def add_measure(self, meas_line: str) -> "ADESession":
        self.state.measures.append(meas_line)
        return self

    # ── Save / Load State ────────────────────────────────────

    def save_state(self, filepath: str) -> bool:
        """Save simulation state to a .sim file."""
        data = self.state.to_dict()
        try:
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)
            return True
        except OSError:
            return False

    def load_state(self, filepath: str) -> bool:
        """Load simulation state from a .sim file."""
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
            self.state = SimulationState.from_dict(data)
            return True
        except (OSError, json.JSONDecodeError):
            return False

    # ── Netlist Generation ───────────────────────────────────

    def _build_netlist(self, corner: Optional[CornerConfig] = None,
                       sweep_values: dict = None) -> str:
        """Build the complete SPICE netlist for the current state."""
        gen = NetlistGenerator(self.db)
        simulator, _simulator_path = self._active_simulator()
        gen.set_target_simulator(simulator)
        directives = NetlistDirectives()

        # Design variables
        if self.state.design_variables:
            directives.params.update(self.state.design_variables)

        # Sweep values override
        if sweep_values:
            directives.params.update(sweep_values)

        # Options
        if self.state.options:
            directives.options.update(self.state.options)

        # Measurements
        directives.measures = list(self.state.measures)

        # Convergence helpers
        directives.nodesets = list(self.state.nodesets)
        directives.ics = list(self.state.ics)

        # PDK model includes
        if self.state.pdk_name:
            pdk_registry = self._get_pdk_registry()
            pdk = pdk_registry.get_pdk(self.state.pdk_name)
            if pdk:
                # Support both legacy models_path and new root_path
                model_path = pdk.models_path
                if model_path and os.path.isdir(model_path):
                    if corner and corner.lib_section:
                        directives.libs.append(
                            f"{os.path.join(model_path, 'models.lib')} {corner.lib_section}"
                        )
                    else:
                        for mf in pdk.model_files:
                            if mf.path.endswith(".lib"):
                                directives.libs.append(mf.path)

        # Corner temperature override
        if corner:
            directives.temp = corner.temperature
            # Override supply voltage via design variable
            if "VDD" in self.state.design_variables:
                pass  # Keep existing VDD

        gen._directives = directives

        # Generate base netlist
        base = gen.generate(self.state.library, self.state.cell, self.state.view)
        lines = base.rstrip().split("\n")

        # Remove .END and append analyses
        while lines and (lines[-1].strip() == ".END" or lines[-1].strip() == ""):
            lines.pop()

        # Analyses
        for analysis in self.state.analyses:
            if analysis.enabled:
                lines.append("")
                lines.append(f"* Analysis: {analysis.analysis_type.value}")
                lines.append(analysis.to_spice())

        # Parametric sweeps
        for sweep in self.state.sweeps:
            if sweep.enabled:
                lines.append("")
                lines.append(f".STEP PARAM {sweep.variable} {sweep.start} {sweep.stop} {sweep.step}")

        # Outputs (SAVE directives)
        for output in self.state.outputs:
            if output.enabled:
                lines.append(f".SAVE {output.expression}")

        lines.append("")
        lines.append(".END")
        return "\n".join(lines)

    # ── Run Simulation ───────────────────────────────────────

    def _extract_model_paths(self, netlist: str) -> list[str]:
        """Extract .include/.lib file references from a netlist."""
        paths: list[str] = []
        for raw in (netlist or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            up = line.upper()
            if up.startswith(".INCLUDE"):
                parts = line.split(maxsplit=1)
                if len(parts) > 1:
                    paths.append(parts[1].strip().strip('"'))
            elif up.startswith(".LIB"):
                parts = line.split(maxsplit=2)
                if len(parts) > 1:
                    paths.append(parts[1].strip().strip('"'))
        return paths

    def run(self, callback: Optional[Callable] = None) -> list[RunRecord]:
        """
        Run the simulation according to the current state.
        
        This runs all analyses for all corners/sweeps and returns results.
        
        Args:
            callback: Optional callback called after each run completes.
            
        Returns:
            List of RunRecord objects.
        """
        self.state.run_count += 1
        self.state.modified = time.time()
        all_runs = []

        # Determine what to simulate
        corners = self._get_active_corners()

        for corner in corners:
            # Build netlist for this corner
            netlist = self._build_netlist(corner)

            # Create simulator bridge
            simulator, simulator_path = self._active_simulator()
            bridge = SimulatorBridge(simulator, simulator_path)

            # Run simulation
            result = bridge.simulate(
                netlist=netlist,
                sim_name=f"{self.state.cell}_{corner.name}_{self.state.run_count}",
                threads=self.state.threads,
                timeout=self.state.timeout,
            )

            # Create run record
            for analysis in self.state.analyses:
                if not analysis.enabled:
                    continue

                record = RunRecord(
                    run_id=f"run{len(self._run_history) + 1}",
                    corner_name=corner.name,
                    sweep_values={},
                    analysis=analysis.analysis_type.value,
                    timestamp=time.time(),
                    success=result.success,
                    netlist_path=result.netlist_path,
                    output_path=result.output_path,
                    log=result.log,
                    errors=list(result.errors),
                    elapsed_time=result.elapsed_time,
                    waveforms=result.waveforms,
                    waveforms_x={},
                )

                # Extract x-axis data
                for candidate in ["time", "frequency", "v-sweep"]:
                    if candidate in result.waveforms:
                        record.waveforms_x[candidate] = result.waveforms[candidate]
                        break

                all_runs.append(record)
                self._run_history.append(record)

                # Store by analysis type
                key = analysis.analysis_type.value
                if key not in self._results:
                    self._results[key] = []
                self._results[key].append(record)
                manifest = RunManifest(
                    run_id=record.run_id,
                    simulator=self.state.simulator,
                    design=f"{self.state.library}/{self.state.cell}/{self.state.view}",
                    corner=corner.name,
                    analysis=analysis.analysis_type.value,
                    seed=0,
                    deck_hash=hash_text(netlist),
                    model_hash=hash_files(self._extract_model_paths(netlist)),
                    elapsed_time=record.elapsed_time,
                    success=record.success,
                )
                self._results_store.record(
                    {
                        "run_id": record.run_id,
                        "success": record.success,
                        "elapsed_time": record.elapsed_time,
                        "analysis": record.analysis,
                        "corner": record.corner_name,
                        "waveforms": record.waveforms,
                    },
                    manifest,
                )

            if callback:
                callback(result)

        return all_runs

    def run_async(self, callback: Optional[Callable] = None) -> threading.Thread:
        """Run simulation in a background thread."""
        thread = threading.Thread(target=lambda: self.run(callback), daemon=True)
        thread.start()
        return thread

    def _get_active_corners(self) -> list[CornerConfig]:
        """Get the list of corners to simulate."""
        if self.state.corner_mode == "single":
            # Use first enabled corner, or default
            for c in self.state.corners:
                if c.enabled:
                    return [c]
            return [CornerConfig("default", 25.0, 1.8, "tt")]
        elif self.state.corner_mode == "all":
            return [c for c in self.state.corners if c.enabled]
        else:  # selected
            return [c for c in self.state.corners if c.enabled]

    def get_run_history(self) -> list[RunRecord]:
        """Get all run history records."""
        return list(self._run_history)

    def get_results(self, analysis: str = "") -> list[RunRecord]:
        """Get results, optionally filtered by analysis type."""
        if analysis:
            return self._results.get(analysis, [])
        return self._run_history

    def get_waveforms(self, run_index: int = -1) -> dict:
        """Get waveforms from a specific run."""
        if not self._run_history:
            return {}
        record = self._run_history[run_index] if run_index < len(self._run_history) \
                 else self._run_history[-1]
        return record.waveforms

    def clear_results(self):
        """Clear all simulation results."""
        self._results.clear()
        self._run_history.clear()

    def compare_runs(self, run_id_a: str, run_id_b: str) -> dict:
        """Compare two runs from the persistent results database."""
        return self._results_store.compare(run_id_a, run_id_b)

    # ── Expression Evaluation ─────────────────────────────────

    def evaluate(self, expression: str, run_index: int = -1) -> Optional[dict]:
        """Evaluate an expression on a run's waveforms."""
        waveforms = self.get_waveforms(run_index)
        if not waveforms:
            return None
        return self._calc.evaluate(expression, waveforms)

    # ── Run Comparison ───────────────────────────────────────

    def compare_corners(self, signal: str) -> list[dict]:
        """Compare a signal across all corners."""
        results = []
        for record in self._run_history:
            if signal in record.waveforms:
                results.append({
                    "corner": record.corner_name,
                    "run_id": record.run_id,
                    "data": record.waveforms[signal],
                })
        return results

    def run_statistical_signoff(self, mc_runs: int = 8, seed: int = 1,
                                sigma_fraction: float = 0.03) -> dict:
        """Run multi-corner Monte Carlo signoff over numeric design variables."""
        rng = random.Random(seed)
        base_vars = dict(self.state.design_variables)
        corners = self._get_active_corners()
        if not corners:
            corners = [CornerConfig("default", 25.0, 1.8, "tt")]

        summary = {
            "seed": seed,
            "mc_runs": mc_runs,
            "runs": 0,
            "passes": 0,
            "fails": 0,
            "corners": [c.name for c in corners],
            "details": [],
        }

        for corner in corners:
            for idx in range(max(1, mc_runs)):
                perturbed = {}
                for key, raw in base_vars.items():
                    text = str(raw)
                    m = re.match(r"^\s*([+-]?\d+(?:\.\d+)?)\s*$", text)
                    if m:
                        base = float(m.group(1))
                        delta = rng.gauss(0.0, sigma_fraction)
                        perturbed[key] = f"{base * (1.0 + delta):.6g}"
                    else:
                        perturbed[key] = raw
                netlist = self._build_netlist(corner, perturbed)
                simulator, simulator_path = self._active_simulator()
                bridge = SimulatorBridge(simulator, simulator_path)
                result = bridge.simulate(
                    netlist=netlist,
                    sim_name=f"{self.state.cell}_{corner.name}_mc{idx + 1}",
                    threads=self.state.threads,
                    timeout=self.state.timeout,
                )
                summary["runs"] += 1
                if result.success:
                    summary["passes"] += 1
                else:
                    summary["fails"] += 1
                summary["details"].append({
                    "corner": corner.name,
                    "index": idx + 1,
                    "success": bool(result.success),
                    "elapsed_time": float(result.elapsed_time),
                    "errors": list(result.errors),
                })

        self.state.design_variables = base_vars
        summary["pass_rate"] = (summary["passes"] / summary["runs"]) if summary["runs"] else 0.0
        return summary

    # ── Convergence Analysis ──────────────────────────────────

    def analyze_convergence(self, run_index: int = -1) -> list[dict]:
        """Analyze the last (or specified) run for convergence issues."""
        if not self._run_history:
            return []
        record = self._run_history[run_index] if run_index < len(self._run_history) \
                 else self._run_history[-1]

        # Create a SimulationResult from the run record
        sim_result = SimulationResult(
            success=record.success,
            simulator=self.state.simulator,
            netlist_path=record.netlist_path,
            output_path=record.output_path,
            log=record.log,
            errors=list(record.errors),
            elapsed_time=record.elapsed_time,
        )

        return ConvergenceAdvisor.analyze(sim_result)
