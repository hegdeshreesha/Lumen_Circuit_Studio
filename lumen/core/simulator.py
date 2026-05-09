"""
Lumen Circuit Studio — Multi-Simulator Bridge

Supports GSPICE, Xyce, and Ngspice backends.
Each simulator has its own executable path, CLI arguments, and output parser.
"""
import subprocess
import os
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SimulationResult:
    """Container for simulation results."""
    success: bool = False
    simulator: str = ""
    netlist_path: str = ""
    output_path: str = ""
    log: str = ""
    raw_output: str = ""
    errors: list[str] = field(default_factory=list)
    waveforms: dict = field(default_factory=dict)
    corner_name: str = ""
    elapsed_time: float = 0.0


# ── Simulator Capabilities ────────────────────────────────────

SIMULATOR_INFO = {
    "GSPICE": {
        "label": "GSPICE (Lumen Native)",
        "analyses": [
            "DC Operating Point", "Transient", "AC Small-Signal", "Noise", "DC Sweep",
            "PSS (Periodic Steady-State)", "Harmonic Balance", "S-Parameters",
            "PAC (Periodic AC)", "PNOISE (Periodic Noise)", "HBAC", "HBNOISE", "HBSP",
            "STB (Stability)", "HBSTB", "PSSSTB",
        ],
        "candidates": [
            r"C:\EDA\GSPICE\build\Release\gspice.exe",
            r"C:\EDA\GSPICE\build\Debug\gspice.exe",
            r"C:\EDA\GSPICE\build\gspice.exe",
            "gspice",
        ],
        "default_timeout": 300,
    },
    "Ngspice": {
        "label": "Ngspice (Open Source)",
        "analyses": [
            "DC Operating Point", "Transient", "AC Small-Signal", "Noise", "DC Sweep",
        ],
        "candidates": [
            r"C:\Program Files\Spice64\bin\ngspice.exe",
            r"C:\ngspice\bin\ngspice.exe",
            "/usr/bin/ngspice",
            "/usr/local/bin/ngspice",
            "ngspice",
        ],
        "default_timeout": 300,
    },
    "Xyce": {
        "label": "Xyce (Sandia National Labs)",
        "analyses": [
            "DC Operating Point", "Transient", "AC Small-Signal", "Noise", "DC Sweep",
            "Harmonic Balance", "S-Parameters",
        ],
        "candidates": [
            r"C:\Program Files\Xyce\bin\Xyce.exe",
            r"C:\Xyce\bin\Xyce.exe",
            "/usr/local/bin/Xyce",
            "Xyce",
        ],
        "default_timeout": 600,
    },
}


def get_supported_analyses(simulator: str) -> list[str]:
    """Return the list of analyses supported by the given simulator."""
    info = SIMULATOR_INFO.get(simulator, {})
    return info.get("analyses", [])


def get_simulator_label(simulator: str) -> str:
    info = SIMULATOR_INFO.get(simulator, {})
    return info.get("label", simulator)


def get_simulator_timeout(simulator: str) -> int:
    info = SIMULATOR_INFO.get(simulator, {})
    return info.get("default_timeout", 300)


class SimulatorBridge:
    """Unified bridge for GSPICE, Xyce, and Ngspice."""

    def __init__(self, simulator: str = "GSPICE", exe_path: str = ""):
        self.simulator = simulator
        self.info = SIMULATOR_INFO.get(simulator, SIMULATOR_INFO["GSPICE"])

        if exe_path:
            self.exe_path = exe_path
        else:
            self.exe_path = self._find_exe()

        self.work_dir = os.path.join(
            os.path.expanduser("~"), "LumenWorkspace", ".sim")
        os.makedirs(self.work_dir, exist_ok=True)
        self._process: subprocess.Popen | None = None
        self._cancelled = False
        self._cache: dict[str, dict] = {}

    def _find_exe(self) -> str:
        for path in self.info.get("candidates", []):
            if os.path.isfile(path):
                return path
        candidates = self.info.get("candidates", ["gspice"])
        return candidates[-1]

    def is_available(self) -> bool:
        try:
            flag = "--version" if self.simulator != "Xyce" else "-v"
            result = subprocess.run(
                [self.exe_path, flag],
                capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def cancel(self):
        """Cancel a running simulation."""
        self._cancelled = True
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()

    def simulate(self, netlist: str, sim_name: str = "sim",
                 threads: int = 4, callback=None,
                 timeout: int = 0, use_cache: bool = False) -> SimulationResult:
        result = SimulationResult(simulator=self.simulator)
        start_time = time.time()

        netlist_path = os.path.join(self.work_dir, f"{sim_name}.sp")
        output_path = os.path.join(self.work_dir, f"{sim_name}.raw")

        with open(netlist_path, "w") as f:
            f.write(netlist)
        result.netlist_path = netlist_path
        result.output_path = output_path

        # Check cache
        cache_key = self._compute_cache_key(netlist_path, output_path)
        if use_cache and cache_key in self._cache:
            result.waveforms = self._cache[cache_key]
            result.success = True
            result.elapsed_time = time.time() - start_time
            if callback:
                callback(result)
            return result

        if timeout <= 0:
            timeout = get_simulator_timeout(self.simulator)

        cmd = self._build_command(netlist_path, output_path, threads)
        self._cancelled = False

        try:
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=self.work_dir, text=True
            )
            stdout, stderr = self._process.communicate(timeout=timeout)
            result.raw_output = stdout
            result.log = stdout + stderr
            result.success = (self._process.returncode == 0 and not self._cancelled)

            if self._cancelled:
                result.errors.append("Simulation cancelled by user")
            elif self._process.returncode != 0:
                result.errors.append(
                    f"{self.simulator} exited with code {self._process.returncode}")
                if stderr:
                    result.errors.append(stderr.strip())

            if result.success and os.path.isfile(output_path):
                result.waveforms = self._parse_raw(output_path)
                self._cache[cache_key] = result.waveforms

        except FileNotFoundError:
            result.errors.append(f"{self.simulator} not found: {self.exe_path}")
        except subprocess.TimeoutExpired:
            if self._process:
                self._process.kill()
            result.errors.append(f"Simulation timed out ({timeout}s)")

        result.elapsed_time = time.time() - start_time
        self._process = None

        if callback:
            callback(result)
        return result

    def simulate_with_retry(self, netlist: str, sim_name: str = "sim",
                            threads: int = 4, callback=None,
                            timeout: int = 0, max_retries: int = 1,
                            retry_delay: float = 1.0) -> SimulationResult:
        """Run simulation with automatic retry on transient failures."""
        last_result = None
        for attempt in range(max_retries + 1):
            if attempt > 0:
                time.sleep(retry_delay)

            result = self.simulate(
                netlist, sim_name, threads, None, timeout
            )
            last_result = result

            if result.success:
                if attempt > 0:
                    result.log += f"\n[Retry {attempt}/{max_retries} succeeded]"
                if callback:
                    callback(result)
                return result

            # Don't retry on cancellation
            if self._cancelled:
                break

            # Check if error is retryable
            retryable = any(
                err in result.log for err in [
                    "timed out", "connection refused", "resource temporarily unavailable",
                    "interrupted", "signal"
                ]
            )
            if not retryable and attempt < max_retries:
                # For convergence failures, try with modified parameters
                if "convergence" in result.log.lower() or "singular" in result.log.lower():
                    retryable = True

            if not retryable:
                break

        if callback and last_result:
            callback(last_result)
        return last_result

    def _compute_cache_key(self, netlist_path: str, output_path: str) -> str:
        """Compute cache key from netlist and output file metadata."""
        try:
            net_mtime = os.path.getmtime(netlist_path)
            raw_mtime = os.path.getmtime(output_path)
            return f"{netlist_path}:{net_mtime}:{raw_mtime}"
        except OSError:
            return ""

    def _build_command(self, netlist_path, output_path, threads):
        if self.simulator == "GSPICE":
            return [self.exe_path, netlist_path,
                    "--threads", str(threads), "-o", output_path]
        elif self.simulator == "Ngspice":
            return [self.exe_path, "-b", "-r", output_path, netlist_path]
        elif self.simulator == "Xyce":
            return [self.exe_path, netlist_path,
                    "-o", output_path]
        return [self.exe_path, netlist_path]

    def _parse_raw(self, filepath: str) -> dict:
        """Parse SPICE raw output file (ASCII or binary)."""
        try:
            with open(filepath, "rb") as f:
                header = f.read(50)

            if b"Binary:" in header[:50]:
                return self._parse_binary_raw(filepath)
            else:
                return self._parse_ascii_raw(filepath)
        except Exception as e:
            return {"_error": str(e)}

    def _parse_ascii_raw(self, filepath: str) -> dict:
        """Parse ASCII SPICE raw output file."""
        waveforms = {}
        try:
            with open(filepath, "r") as f:
                content = f.read()
            lines = content.strip().split("\n")
            header_done = False
            variables = []
            data_lines = []
            for line in lines:
                s = line.strip()
                if s.startswith("Variables:"):
                    header_done = False
                    continue
                if s.startswith("Values:") or s.startswith("Binary:"):
                    header_done = True
                    continue
                if not header_done:
                    parts = s.split()
                    if len(parts) >= 3 and parts[0].isdigit():
                        variables.append(parts[1])
                else:
                    if s:
                        data_lines.append(s)
            if variables and data_lines:
                n_vars = len(variables)
                values = []
                for line in data_lines:
                    for p in line.split():
                        try:
                            values.append(float(p))
                        except ValueError:
                            pass
                for i, var in enumerate(variables):
                    waveforms[var] = []
                n_pts = len(values) // n_vars if n_vars else 0
                for pt in range(n_pts):
                    for i, var in enumerate(variables):
                        idx = pt * n_vars + i
                        if idx < len(values):
                            waveforms[var].append(values[idx])
        except Exception as e:
            waveforms["_error"] = str(e)
        return waveforms

    def _parse_binary_raw(self, filepath: str) -> dict:
        """Parse binary SPICE raw output file (Ngspice/Xyce format)."""
        waveforms = {}
        try:
            with open(filepath, "rb") as f:
                # Read header section (text until "Binary:" or "Values:")
                header_lines = []
                while True:
                    line = f.readline().decode("ascii", errors="ignore")
                    if not line:
                        break
                    header_lines.append(line)
                    if line.strip().startswith("Binary:") or line.strip().startswith("Values:"):
                        break

                # Parse variable names from header
                variables = []
                for line in header_lines:
                    parts = line.strip().split()
                    if len(parts) >= 3 and parts[0].isdigit():
                        variables.append(parts[1])

                if not variables:
                    return waveforms

                # Read binary data
                data = f.read()

                # Determine format: Ngspice uses double, Xyce may use float
                n_vars = len(variables)
                n_doubles = len(data) // 8
                n_floats = len(data) // 4

                if n_doubles >= n_vars and n_doubles % n_vars == 0:
                    # Double precision (Ngspice)
                    n_points = n_doubles // n_vars
                    fmt = f"<{n_vars * n_points}d"
                    values = struct.unpack(fmt, data[:n_vars * n_points * 8])
                elif n_floats >= n_vars and n_floats % n_vars == 0:
                    # Single precision (some Xyce outputs)
                    n_points = n_floats // n_vars
                    fmt = f"<{n_vars * n_points}f"
                    values = struct.unpack(fmt, data[:n_vars * n_points * 4])
                else:
                    # Try to interpret as doubles anyway
                    n_points = n_doubles // n_vars if n_vars > 0 else 0
                    if n_points > 0:
                        fmt = f"<{n_vars * n_points}d"
                        values = struct.unpack(fmt, data[:n_vars * n_points * 8])
                    else:
                        return waveforms

                for var in variables:
                    waveforms[var] = []

                for pt in range(n_points):
                    for i, var in enumerate(variables):
                        idx = pt * n_vars + i
                        if idx < len(values):
                            waveforms[var].append(values[idx])

        except Exception as e:
            waveforms["_error"] = str(e)
        return waveforms
