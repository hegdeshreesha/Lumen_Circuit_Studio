"""
Lumen Circuit Studio — Multi-Simulator Bridge

Supports GSPICE, Xyce, and Ngspice backends.
Each simulator has its own executable path, CLI arguments, and output parser.
"""
import subprocess
import os
import shutil
import struct
import threading
import time
import re
import tempfile
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SimulationResult:
    """Container for simulation results."""
    success: bool = False
    simulator: str = ""
    netlist_path: str = ""
    output_path: str = ""
    run_dir: str = ""
    log: str = ""
    raw_output: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    waveforms: dict = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    corner_name: str = ""
    elapsed_time: float = 0.0
    return_code: int = 0
    command: list[str] = field(default_factory=list)


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


def ensure_direct_run_analysis(netlist: str, default_tran: str = ".TRAN 1n 10u") -> tuple[str, str]:
    """Append a conservative analysis for schematic toolbar quick-runs.

    SimENV owns explicit analyses. The schematic Run button is a convenience path,
    so if the generated schematic deck has no analysis directive we add one rather
    than launching a run that can only produce confusing single-point output.
    """
    text = str(netlist or "")
    if re.search(r"(?im)^\s*\.(OP|TRAN|AC|DC|NOISE|PSS|HB|SP|PAC|PNOISE|HBAC|HBNOISE|HBSP|STB|HBSTB|PSSSTB)\b", text):
        return text, ""

    has_dynamic_source = bool(
        re.search(r"(?im)^\s*[VI]\S*\s+\S+\s+\S+.*\b(PULSE|SIN|PWL|EXP|SFFM)\s*\(", text)
    )
    analysis = default_tran if has_dynamic_source else ".OP"
    note = (
        f"Added default {analysis} for schematic quick-run "
        "because no analysis was present in the deck."
    )

    lines = text.rstrip().splitlines()
    while lines and lines[-1].strip().upper() == ".END":
        lines.pop()
    lines.append("")
    lines.append("* Lumen quick-run analysis")
    lines.append(analysis)
    lines.append(".END")
    lines.append("")
    return "\n".join(lines), note


class SimulatorBridge:
    """Unified bridge for GSPICE, Xyce, and Ngspice."""

    def __init__(self, simulator: str = "GSPICE", exe_path: str = "", work_dir: str = ""):
        self.simulator = simulator
        self.info = SIMULATOR_INFO.get(simulator, SIMULATOR_INFO["GSPICE"])

        if exe_path:
            self.exe_path = exe_path
        else:
            self.exe_path = self._find_exe()

        self.work_dir = self._select_work_dir(work_dir)
        self._process: subprocess.Popen | None = None
        self._cancelled = False
        self._cache: dict[str, dict] = {}

    def _select_work_dir(self, preferred_dir: str = "") -> str:
        """Pick a writable directory for simulator input and output files."""
        candidates = [
            preferred_dir,
            os.environ.get("LUMEN_SIM_DIR", ""),
            os.path.join(os.path.expanduser("~"), "LumenWorkspace", ".sim"),
            r"C:\EDA\LumenCircuitStudio\scratch\sim",
            os.path.join(tempfile.gettempdir(), "LumenCircuitStudio", "sim"),
        ]
        for path in candidates:
            if not path:
                continue
            try:
                os.makedirs(path, exist_ok=True)
                probe = os.path.join(path, ".write_test")
                with open(probe, "w", encoding="utf-8") as f:
                    f.write("ok")
                os.remove(probe)
                return path
            except OSError:
                continue
        return tempfile.gettempdir()

    def _find_exe(self) -> str:
        # Highest-priority explicit overrides.
        env_override = {
            "GSPICE": os.environ.get("LUMEN_GSPICE_EXE", ""),
            "Ngspice": os.environ.get("LUMEN_NGSPICE_EXE", ""),
            "Xyce": os.environ.get("LUMEN_XYCE_EXE", ""),
        }.get(self.simulator, "")
        for candidate in [env_override, os.environ.get("LUMEN_SIM_EXE", "")]:
            if candidate:
                resolved = self._resolve_executable(candidate)
                if resolved:
                    return resolved

        for path in self.info.get("candidates", []):
            resolved = self._resolve_executable(path)
            if resolved:
                return resolved

        # GSPICE local fallback scan in common workspace roots.
        if self.simulator == "GSPICE":
            scanned = self._scan_for_gspice()
            if scanned:
                return scanned

        candidates = self.info.get("candidates", ["gspice"])
        return candidates[-1]

    def is_available(self) -> bool:
        resolved = self._resolve_executable(self.exe_path)
        if not resolved:
            return False
        self.exe_path = resolved

        probes = {
            "GSPICE": [[resolved, "--version"], [resolved, "-v"]],
            "Ngspice": [[resolved, "--version"], [resolved, "-v"]],
            "Xyce": [[resolved, "-v"], [resolved, "--version"]],
        }.get(self.simulator, [[resolved, "--version"]])

        for cmd in probes:
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=5)
            except FileNotFoundError:
                continue
            except subprocess.TimeoutExpired:
                # If process launches but doesn't return quickly, treat as available.
                return True

            combined = f"{result.stdout}\n{result.stderr}".lower()
            if result.returncode == 0:
                return True
            if self.simulator.lower() in combined:
                return True
            if os.path.basename(resolved).lower() in combined:
                return True

        # Avoid false-negative when executable is present but version flags differ.
        return bool(os.path.isfile(resolved) or shutil.which(resolved))

    @staticmethod
    def _resolve_executable(candidate: str) -> str:
        candidate = str(candidate or "").strip().strip('"')
        if not candidate:
            return ""
        if os.path.isfile(candidate):
            return candidate
        found = shutil.which(candidate)
        return found or ""

    def _scan_for_gspice(self) -> str:
        """Search common local roots for gspice.exe as a fallback."""
        roots = [
            r"C:\EDA\GSPICE",
            r"C:\EDA\Gspice",
            r"C:\EDA",
        ]
        for root in roots:
            if not os.path.isdir(root):
                continue
            try:
                for base, _dirs, files in os.walk(root):
                    if "gspice.exe" in [f.lower() for f in files]:
                        return os.path.join(base, "gspice.exe")
            except OSError:
                continue
        return ""

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
                 threads: int = 1, callback=None,
                 timeout: int = 0, use_cache: bool = False) -> SimulationResult:
        result = SimulationResult(simulator=self.simulator)
        start_time = time.time()

        safe_sim_name = self._safe_sim_name(sim_name)
        base_work_dir = self.work_dir
        run_dir = self._create_run_dir(base_work_dir, safe_sim_name, start_time)
        self.work_dir = run_dir
        netlist_path = os.path.join(run_dir, "input.sp")
        output_path = os.path.join(run_dir, "waveforms.raw")
        stdout_path = os.path.join(run_dir, "stdout.log")
        stderr_path = os.path.join(run_dir, "stderr.log")
        manifest_path = os.path.join(run_dir, "run_manifest.json")

        sim_netlist, compatibility_notes = self._prepare_netlist_for_simulator(netlist)
        has_ac_analysis = bool(re.search(r"(?im)^\s*\.AC\b", sim_netlist))
        has_dynamic_sources = bool(re.search(r"(?im)^\s*[VI]\S*\s+\S+\s+\S+.*\b(PULSE|SIN|PWL|EXP|SFFM)\(", sim_netlist))
        node_aliases = self._extract_gspice_node_aliases(sim_netlist) if self.simulator == "GSPICE" else {}

        result.netlist_path = netlist_path
        result.output_path = output_path
        result.run_dir = run_dir
        result.artifacts["run_dir"] = run_dir
        result.artifacts["manifest"] = manifest_path
        result.log = f"Input deck: {netlist_path}\n"
        for note in compatibility_notes:
            result.log += f"{note}\n"

        try:
            with open(netlist_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(sim_netlist)
        except OSError as exc:
            result.errors.append(f"Could not write simulator input deck: {exc}")
            result.elapsed_time = time.time() - start_time
            self._write_run_manifest(result, manifest_path)
            self.work_dir = base_work_dir
            if callback:
                callback(result)
            return result

        # Check cache
        cache_key = self._compute_cache_key(netlist_path, output_path)
        if use_cache and cache_key in self._cache:
            result.waveforms = self._cache[cache_key]
            result.success = True
            result.elapsed_time = time.time() - start_time
            self._write_run_manifest(result, manifest_path)
            self.work_dir = base_work_dir
            if callback:
                callback(result)
            return result

        if timeout <= 0:
            timeout = get_simulator_timeout(self.simulator)

        requested_threads = max(1, int(threads or 1))
        cmd = self._build_command(netlist_path, output_path, requested_threads)
        result.command = cmd
        result.log += f"Command: {' '.join(cmd)}\n"
        self._cancelled = False

        preflight_errors = self._preflight_checks()
        if preflight_errors:
            result.errors.extend(preflight_errors)
            result.elapsed_time = time.time() - start_time
            self._write_run_manifest(result, manifest_path)
            self.work_dir = base_work_dir
            if callback:
                callback(result)
            return result

        try:
            def _run_command(run_cmd: list[str]) -> tuple[str, str, int]:
                self._process = subprocess.Popen(
                    run_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    cwd=self.work_dir, text=True
                )
                out, err = self._process.communicate(timeout=timeout)
                code = int(self._process.returncode or 0)
                return out, err, code

            stdout, stderr, return_code = _run_command(cmd)
            self._write_text_artifact(stdout_path, stdout)
            self._write_text_artifact(stderr_path, stderr)
            result.artifacts["stdout"] = stdout_path
            result.artifacts["stderr"] = stderr_path
            result.raw_output = stdout
            result.return_code = return_code
            if stdout:
                result.log += "\n[stdout]\n" + stdout
            if stderr:
                result.log += "\n[stderr]\n" + stderr
            result.success = (return_code == 0 and not self._cancelled)

            # Some GSPICE builds can crash in multi-thread mode on specific decks.
            # Auto-retry once with --threads 1 for stability.
            if (
                self.simulator == "GSPICE"
                and requested_threads > 1
                and self._is_windows_crash_code(return_code)
                and not self._cancelled
            ):
                safe_cmd = self._build_command(netlist_path, output_path, 1)
                result.log += (
                    "\n[retry]\n"
                    f"{self.simulator} crashed with exit code {return_code} "
                    f"using --threads {requested_threads}; retrying with --threads 1.\n"
                    f"Retry Command: {' '.join(safe_cmd)}\n"
                )
                stdout, stderr, return_code = _run_command(safe_cmd)
                self._write_text_artifact(stdout_path, stdout)
                self._write_text_artifact(stderr_path, stderr)
                result.raw_output = stdout
                result.return_code = return_code
                result.command = safe_cmd
                result.success = (return_code == 0 and not self._cancelled)
                if stdout:
                    result.log += "\n[stdout retry]\n" + stdout
                if stderr:
                    result.log += "\n[stderr retry]\n" + stderr

            # Last-resort crash shield for decks that trigger parser crashes.
            if (
                self.simulator == "GSPICE"
                and self._is_windows_crash_code(return_code)
                and not self._cancelled
            ):
                crash_safe_netlist, crash_safe_notes = self._build_crash_safe_netlist(sim_netlist)
                if crash_safe_notes:
                    for note in crash_safe_notes:
                        result.log += f"{note}\n"
                        result.warnings.append(note)
                if crash_safe_netlist and crash_safe_netlist != sim_netlist:
                    crash_safe_path = os.path.join(self.work_dir, f"{safe_sim_name}_safe.sp")
                    try:
                        with open(crash_safe_path, "w", encoding="utf-8", newline="\n") as f:
                            f.write(crash_safe_netlist)
                        safe_cmd = self._build_command(crash_safe_path, output_path, 1)
                        result.log += (
                            "\n[crash-safe retry]\n"
                            f"Retrying with simplified compatibility deck: {crash_safe_path}\n"
                            f"Retry Command: {' '.join(safe_cmd)}\n"
                        )
                        stdout, stderr, return_code = _run_command(safe_cmd)
                        self._write_text_artifact(stdout_path, stdout)
                        self._write_text_artifact(stderr_path, stderr)
                        result.raw_output = stdout
                        result.return_code = return_code
                        result.command = safe_cmd
                        result.success = (return_code == 0 and not self._cancelled)
                        if stdout:
                            result.log += "\n[stdout crash-safe]\n" + stdout
                        if stderr:
                            result.log += "\n[stderr crash-safe]\n" + stderr
                    except OSError as exc:
                        result.warnings.append(
                            f"Crash-safe retry could not write simplified deck: {exc}"
                        )

            # Diagnostic fallback: identify element lines that independently crash GSPICE.
            if (
                self.simulator == "GSPICE"
                and self._is_windows_crash_code(return_code)
                and not self._cancelled
            ):
                bad_lines = self._find_crash_lines(sim_netlist, safe_sim_name, timeout)
                if bad_lines:
                    result.warnings.append(
                        f"[GSPICE crash isolate] {len(bad_lines)} suspect netlist line(s) detected."
                    )
                    for line in bad_lines[:8]:
                        result.warnings.append(f"[GSPICE crash isolate] {line}")
                        result.errors.append(f"[GSPICE crash isolate] {line}")
                    result.errors.append(
                        "GSPICE parser crash reproduced on isolated line test. "
                        "Remove or simplify the reported element line(s)."
                    )
                else:
                    result.errors.append(
                        "GSPICE parser crash could not be isolated to a single element line. "
                        "Please share the generated .sp deck for deeper triage."
                    )

            if self._cancelled:
                result.errors.append("Simulation cancelled by user")
            elif return_code != 0:
                result.errors.append(
                    f"{self.simulator} exited with code {return_code}")
                if stderr:
                    result.errors.append(stderr.strip())
                if self._is_windows_crash_code(return_code):
                    nt_code = int(return_code) & 0xFFFFFFFF
                    result.errors.append(
                        f"{self.simulator} crashed at process level "
                        f"(Windows status 0x{nt_code:08X}). "
                        "Try a simpler deck or update/rebuild the simulator."
                    )
                    if self.simulator == "GSPICE":
                        if has_ac_analysis:
                            result.errors.append(
                                "This GSPICE build appears unstable for .AC analysis "
                                "(reproduced crash on minimal AC test deck)."
                            )
                        if has_dynamic_sources:
                            result.errors.append(
                                "This GSPICE build appears unstable for dynamic sources "
                                "(PULSE/SIN/PWL/EXP/SFFM) in transient decks."
                            )

            fatal_lines, warning_lines = self._collect_output_diagnostics(stdout, stderr)
            result.warnings.extend(warning_lines)
            if warning_lines:
                result.log += "\n[diagnostics]\n" + "\n".join(f"WARNING: {line}" for line in warning_lines) + "\n"
            if fatal_lines:
                result.errors.extend(fatal_lines)
                result.success = False

            if result.success:
                resolved_output = self._resolve_output_file_path(
                    requested_output=output_path,
                    netlist_path=netlist_path,
                    safe_sim_name=safe_sim_name,
                    started_at=start_time,
                )
                if resolved_output:
                    result.output_path = resolved_output
                else:
                    result.output_path = ""
                    if self.simulator == "GSPICE":
                        result.warnings.append(
                            "RAW output file was not generated by this GSPICE run; "
                            "waveforms were read from simulator stdout."
                        )

                if self.simulator == "GSPICE":
                    result.waveforms = self._parse_gspice_stdout(stdout, node_aliases)
                    if not result.output_path and result.waveforms:
                        if self._write_ascii_raw_fallback(output_path, result.waveforms):
                            result.output_path = output_path
                            result.warnings.append(
                                "GSPICE did not emit RAW directly; Lumen wrote an ASCII RAW fallback from stdout waveforms."
                            )
                        else:
                            result.warnings.append(
                                "GSPICE stdout did not contain sweep waveform vectors "
                                "(time/frequency with multiple points), so RAW fallback was not written."
                            )
                elif result.output_path and os.path.isfile(result.output_path):
                    result.waveforms = self._parse_raw(result.output_path)
                if result.waveforms:
                    csv_path = os.path.join(run_dir, "waveforms.csv")
                    if self._write_waveform_csv(csv_path, result.waveforms):
                        result.artifacts["csv"] = csv_path
                        result.artifacts["waveforms"] = csv_path
                        result.log += f"Waveform CSV: {csv_path}\n"
                if result.output_path and os.path.isfile(result.output_path):
                    result.artifacts["raw"] = result.output_path
                    result.artifacts.setdefault("waveforms", result.output_path)
                self._cache[cache_key] = result.waveforms

        except FileNotFoundError:
            result.errors.append(f"{self.simulator} not found: {self.exe_path}")
        except OSError as exc:
            result.errors.append(f"Could not launch {self.simulator}: {exc}")
        except subprocess.TimeoutExpired:
            if self._process:
                self._process.kill()
            result.errors.append(f"Simulation timed out ({timeout}s)")

        result.elapsed_time = time.time() - start_time
        self._write_run_manifest(result, manifest_path)
        result.log += f"Run folder: {run_dir}\n"
        result.log += f"Run manifest: {manifest_path}\n"
        self._process = None
        self.work_dir = base_work_dir

        if callback:
            callback(result)
        return result

    def _create_run_dir(self, base_dir: str, safe_sim_name: str, started_at: float) -> str:
        """Create a stable per-run artifact directory."""
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(started_at))
        root = os.path.join(base_dir, safe_sim_name)
        os.makedirs(root, exist_ok=True)
        candidate = os.path.join(root, stamp)
        suffix = 1
        while os.path.exists(candidate):
            suffix += 1
            candidate = os.path.join(root, f"{stamp}_{suffix:02d}")
        os.makedirs(candidate, exist_ok=True)

        latest_path = os.path.join(root, "latest_run.txt")
        self._write_text_artifact(latest_path, candidate)
        return candidate

    @staticmethod
    def _write_text_artifact(path: str, text: str) -> None:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text or "")
        except OSError:
            pass

    def _write_run_manifest(self, result: SimulationResult, manifest_path: str) -> None:
        """Write a small manifest so tools can reopen this run reliably."""
        try:
            payload = {
                "format": "lumen-sim-run",
                "version": 1,
                "simulator": result.simulator,
                "success": result.success,
                "return_code": result.return_code,
                "elapsed_time": result.elapsed_time,
                "run_dir": result.run_dir,
                "netlist_path": result.netlist_path,
                "output_path": result.output_path,
                "artifacts": result.artifacts,
                "signals": [k for k in result.waveforms.keys() if not str(k).startswith("_")],
                "command": result.command,
                "errors": result.errors,
                "warnings": result.warnings,
            }
            os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
            with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(payload, f, indent=2)
        except OSError:
            pass

    def _build_crash_safe_netlist(self, netlist: str) -> tuple[str, list[str]]:
        """Build a conservative GSPICE deck by stripping crash-prone constructs."""
        if self.simulator != "GSPICE":
            return netlist, []

        allowed_prefixes = {"R", "C", "L", "V", "I", "D", "Q", "M"}
        allowed_directives = {
            ".OP", ".TRAN", ".AC", ".DC", ".NOISE",
            ".TEMP", ".OPTIONS", ".OPTION", ".PARAM",
            ".PRINT", ".MEASURE", ".MEAS", ".IC", ".NODESET",
            ".END",
        }
        risky_tokens = (
            "TABLE(", "POLY(", "LAPLACE", "PWL(", "SFFM(",
            "{", "}", "VALUE=", "ADEV",
        )

        stripped = 0
        out_lines: list[str] = []
        for raw in netlist.splitlines():
            s = raw.strip()
            if not s or s.startswith(("*", "$")):
                out_lines.append(raw)
                continue

            head = s.split()[0]
            upper = head.upper()

            if upper.startswith("."):
                if upper in allowed_directives:
                    out_lines.append(raw)
                else:
                    out_lines.append(f"* crash-safe stripped directive: {raw}")
                    stripped += 1
                continue

            first = upper[0]
            if first in allowed_prefixes and not any(tok in s.upper() for tok in risky_tokens):
                out_lines.append(raw)
            else:
                out_lines.append(f"* crash-safe stripped element: {raw}")
                stripped += 1

        if not any(line.strip().upper() == ".END" for line in out_lines):
            out_lines.append(".END")

        notes: list[str] = []
        if stripped:
            notes.append(
                f"[GSPICE crash-safe] Stripped {stripped} line(s) with risky/unsupported constructs and retried."
            )
        return ("\n".join(out_lines) + "\n"), notes

    def _find_crash_lines(self, netlist: str, safe_sim_name: str, timeout: int) -> list[str]:
        """Try element lines one-by-one to isolate parser-crashing statements."""
        deck_lines = [ln.rstrip("\n") for ln in netlist.splitlines()]
        elements: list[str] = []
        for ln in deck_lines:
            s = ln.strip()
            if not s or s.startswith(("*", "$", ".")):
                continue
            elements.append(ln)
        if not elements:
            return []

        suspects: list[str] = []
        for idx, element in enumerate(elements):
            probe = [
                "* GSPICE crash isolate probe",
                element,
                ".OP",
                ".END",
                "",
            ]
            probe_path = os.path.join(self.work_dir, f"{safe_sim_name}_probe_{idx}.sp")
            try:
                with open(probe_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write("\n".join(probe))
                probe_cmd = self._build_command(probe_path, "", 1)
                proc = subprocess.run(
                    probe_cmd,
                    capture_output=True,
                    text=True,
                    timeout=max(10, min(timeout, 30)),
                    check=False,
                    cwd=self.work_dir,
                )
                if self._is_windows_crash_code(int(proc.returncode or 0)):
                    suspects.append(element.strip())
            except (OSError, subprocess.TimeoutExpired):
                continue
        return suspects

    @staticmethod
    def _is_windows_crash_code(return_code: int) -> bool:
        crash_codes = {
            0xC0000005,  # access violation
            0xC0000017,  # no memory
            0xC0000409,  # stack buffer overrun
            -1073741819,  # signed 0xC0000005
            -1073741801,  # signed 0xC0000017
            -1073740791,  # signed 0xC0000409
        }
        return int(return_code) in crash_codes

    def _preflight_checks(self) -> list[str]:
        """Return actionable preflight errors before launching a simulator."""
        errors: list[str] = []
        exe_resolved = self.exe_path
        if not (os.path.isfile(exe_resolved) or shutil.which(exe_resolved)):
            errors.append(f"{self.simulator} executable not found: {self.exe_path}")
            errors.append("Set the simulator path in configuration or add it to PATH.")
        if not os.path.isdir(self.work_dir):
            errors.append(f"Simulator work directory does not exist: {self.work_dir}")
        else:
            try:
                probe = os.path.join(self.work_dir, ".sim_probe")
                with open(probe, "w", encoding="utf-8") as f:
                    f.write("ok")
                os.remove(probe)
            except OSError as exc:
                errors.append(f"Simulator work directory is not writable: {self.work_dir} ({exc})")
        return errors

    def _collect_output_diagnostics(self, stdout: str, stderr: str) -> tuple[list[str], list[str]]:
        """Classify simulator output lines into fatal errors and warnings."""
        fatal_patterns = [
            re.compile(r"\berror\b", re.IGNORECASE),
            re.compile(r"\bfatal\b", re.IGNORECASE),
            re.compile(r"requires at least", re.IGNORECASE),
            re.compile(r"could not open file", re.IGNORECASE),
            re.compile(r"simulation failed", re.IGNORECASE),
        ]
        warning_patterns = [
            re.compile(r"\bwarning\b", re.IGNORECASE),
        ]

        fatal: list[str] = []
        warnings: list[str] = []
        for raw_line in (stdout + "\n" + stderr).splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if any(p.search(line) for p in warning_patterns):
                warnings.append(line)
            if any(p.search(line) for p in fatal_patterns):
                fatal.append(line)

        # De-duplicate while preserving order.
        seen = set()
        fatal_unique = []
        for line in fatal:
            if line not in seen:
                seen.add(line)
                fatal_unique.append(line)

        seen = set()
        warning_unique = []
        for line in warnings:
            if line not in seen:
                seen.add(line)
                warning_unique.append(line)

        return fatal_unique, warning_unique

    def _safe_sim_name(self, sim_name: str) -> str:
        """Return a filesystem-safe simulation deck basename."""
        name = re.sub(r"[^A-Za-z0-9_.-]+", "_", sim_name or "sim").strip("._")
        return name or "sim"

    def _write_ascii_raw_fallback(self, path: str, waveforms: dict) -> bool:
        """Write a minimal ASCII .raw file from parsed waveform arrays."""
        if not path or not isinstance(waveforms, dict):
            return False

        keys = [k for k in waveforms.keys() if not str(k).startswith("_")]
        if not keys:
            return False

        x_name = ""
        for candidate in ("time", "frequency", "v-sweep", "sweep"):
            if candidate in waveforms:
                x_name = candidate
                break
        if not x_name:
            return False
        if x_name not in waveforms:
            return False

        y_names = [k for k in keys if k != x_name]
        var_names = [x_name] + y_names
        series = []
        for name in var_names:
            vals = waveforms.get(name, [])
            if not isinstance(vals, list):
                return False
            series.append(vals)
        if not series:
            return False

        n_points = min(len(vals) for vals in series) if series else 0
        if n_points <= 1:
            return False

        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write("Title: Lumen ASCII RAW fallback\n")
                f.write("Plotname: Transient Analysis\n")
                f.write("Flags: real\n")
                f.write(f"No. Variables: {len(var_names)}\n")
                f.write(f"No. Points: {n_points}\n")
                f.write("Variables:\n")
                for idx, name in enumerate(var_names):
                    unit = "time" if idx == 0 else "voltage"
                    f.write(f"{idx}\t{name}\t{unit}\n")
                f.write("Values:\n")
                for row in range(n_points):
                    parts = []
                    for col in range(len(var_names)):
                        parts.append(f"{float(series[col][row]):.16g}")
                    f.write(" ".join(parts) + "\n")
            return True
        except Exception:
            return False

    def _write_waveform_csv(self, path: str, waveforms: dict) -> bool:
        """Write parsed waveform vectors to a SigView-loadable CSV artifact."""
        if not path or not isinstance(waveforms, dict):
            return False

        names = [str(k) for k in waveforms.keys() if not str(k).startswith("_")]
        if not names:
            return False

        x_name = ""
        for candidate in ("time", "frequency", "v-sweep", "sweep"):
            if candidate in waveforms:
                x_name = candidate
                break
        if x_name and x_name in names:
            names.remove(x_name)
            names.insert(0, x_name)

        series: list[list] = []
        for name in names:
            vals = waveforms.get(name, [])
            if isinstance(vals, list):
                series.append(vals)
            else:
                series.append([])

        n_points = max((len(vals) for vals in series), default=0)
        if n_points <= 0:
            return False

        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(",".join(names) + "\n")
                for row in range(n_points):
                    values = []
                    for vals in series:
                        if row < len(vals):
                            try:
                                values.append(f"{float(vals[row]):.16g}")
                            except (TypeError, ValueError):
                                values.append("")
                        else:
                            values.append("")
                    f.write(",".join(values) + "\n")
            return True
        except Exception:
            return False

    def _resolve_output_file_path(self, requested_output: str, netlist_path: str,
                                  safe_sim_name: str, started_at: float) -> str:
        """Find the actual output file path produced by the simulator run."""
        candidates: list[str] = []
        requested_output = str(requested_output or "").strip()
        if requested_output:
            candidates.append(requested_output)

        netlist_base = os.path.splitext(netlist_path)[0]
        if netlist_base:
            candidates.extend([
                f"{netlist_base}.raw",
                f"{netlist_base}.out",
                f"{netlist_base}.prn",
            ])

        # Fast-path: explicit candidate exists.
        for path in candidates:
            if path and os.path.isfile(path):
                return path

        # Fallback: scan simulator work dir for recent run artifacts.
        try:
            recents: list[tuple[float, str]] = []
            for name in os.listdir(self.work_dir):
                low = name.lower()
                if not (low.endswith(".raw") or low.endswith(".out") or low.endswith(".prn")):
                    continue
                full = os.path.join(self.work_dir, name)
                try:
                    mtime = os.path.getmtime(full)
                except OSError:
                    continue
                # Keep files written around this simulation window.
                if mtime + 1.0 < started_at:
                    continue
                score = 0
                if safe_sim_name.lower() in low:
                    score += 100
                if os.path.basename(netlist_base).lower() in low:
                    score += 50
                # Secondary tie-breaker by modification time.
                recents.append((score * 1_000_000.0 + mtime, full))
            if recents:
                recents.sort(key=lambda x: x[0], reverse=True)
                return recents[0][1]
        except OSError:
            pass

        return ""

    def _prepare_netlist_for_simulator(self, netlist: str) -> tuple[str, list[str]]:
        """Apply small compatibility rewrites before launching a simulator.

        GSPICE currently parses primitive devices directly, but not full
        Cadence/ngspice PDK wrapper syntax. Keep the ADE-visible netlist
        standard, then write a GSPICE-friendly deck for execution.
        """
        if self.simulator != "GSPICE":
            return netlist, []

        lines: list[str] = []
        stripped_model_directives = 0
        stripped_saves = 0
        converted_sources = 0
        converted_pdk_mos = 0

        for raw_line in netlist.splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith(("*", "$")):
                lines.append(raw_line)
                continue

            tokens = stripped.split()
            head = tokens[0]
            upper_head = head.upper()

            if upper_head in (".LIB", ".INCLUDE", ".INC"):
                stripped_model_directives += 1
                lines.append(f"* GSPICE compatibility: skipped {stripped}")
                continue

            if upper_head == ".SAVE":
                stripped_saves += 1
                lines.append(f"* GSPICE compatibility: skipped {stripped}")
                continue

            if upper_head[0] == "X":
                converted = self._convert_gspice_pdk_mos(tokens)
                if converted:
                    lines.append(converted)
                    converted_pdk_mos += 1
                else:
                    lines.append(f"* GSPICE compatibility: unsupported subckt skipped: {stripped}")
                continue

            if upper_head[0] in ("V", "I") and len(tokens) >= 5 and tokens[3].upper() == "DC":
                lines.append(" ".join(tokens[:3] + [tokens[4]] + tokens[5:]))
                converted_sources += 1
                continue

            lines.append(raw_line)

        notes = []
        if stripped_model_directives or stripped_saves or converted_sources or converted_pdk_mos:
            notes.append("[GSPICE compatibility] Rewrote standard SPICE deck for current GSPICE parser.")
        if converted_pdk_mos:
            notes.append(f"[GSPICE compatibility] Converted {converted_pdk_mos} PDK MOS subckt instance(s) to primitive M devices.")
        if stripped_model_directives:
            notes.append(f"[GSPICE compatibility] Skipped {stripped_model_directives} .LIB/.INCLUDE directive(s); current GSPICE does not parse model libraries yet.")
        if stripped_saves:
            notes.append(f"[GSPICE compatibility] Skipped {stripped_saves} .SAVE directive(s); current GSPICE reports all node values it solves.")
        if converted_sources:
            notes.append(f"[GSPICE compatibility] Converted {converted_sources} DC source line(s) to GSPICE's simple source syntax.")
        return "\n".join(lines) + ("\n" if netlist.endswith("\n") else ""), notes

    def _convert_gspice_pdk_mos(self, tokens: list[str]) -> str:
        """Convert known PDK MOS subckt instances to GSPICE primitive MOS lines."""
        if len(tokens) < 6:
            return ""

        model_name = tokens[5].lower()
        if not any(marker in model_name for marker in ("nmos", "pmos", "nfet", "pfet")):
            return ""

        inst_name = tokens[0]
        if inst_name.upper().startswith("X"):
            suffix = inst_name[1:] or inst_name
            inst_name = suffix if suffix.upper().startswith("M") else "M" + suffix

        mos_type = "PMOS" if any(marker in model_name for marker in ("pmos", "pfet")) else "NMOS"
        params = self._normalize_gspice_mos_params(tokens[6:])
        return " ".join([inst_name, *tokens[1:5], mos_type, *params])

    def _normalize_gspice_mos_params(self, params: list[str]) -> list[str]:
        """Keep GSPICE-supported MOS params and normalize common PDK aliases."""
        normalized: list[str] = []
        aliases = {
            "w": "W",
            "l": "L",
        }
        for param in params:
            if "=" not in param:
                continue
            key, value = param.split("=", 1)
            mapped_key = aliases.get(key.strip().lower())
            if not mapped_key:
                continue
            normalized.append(f"{mapped_key}={value.strip()}")
        return normalized

    def _convert_dynamic_source_for_gspice(self, tokens: list[str]) -> str:
        """Convert dynamic source syntax (PULSE/SIN/...) to a safe DC fallback."""
        if len(tokens) < 4:
            return ""
        supported_wave = ("PULSE(", "SIN(", "PWL(", "EXP(", "SFFM(")

        wave_token = ""
        for tok in tokens[3:]:
            upper_tok = tok.upper()
            if any(upper_tok.startswith(prefix) for prefix in supported_wave):
                wave_token = tok
                break
        if not wave_token:
            return ""

        # Derive a conservative DC value from the first waveform argument.
        first_arg = "0"
        raw = wave_token
        if "(" in raw:
            after = raw.split("(", 1)[1]
            first_arg = after.split(",", 1)[0].strip()
            first_arg = first_arg.split(")", 1)[0].strip() or "0"
        if first_arg.upper().startswith(("PULSE", "SIN", "PWL", "EXP", "SFFM")):
            first_arg = "0"

        name = tokens[0]
        nplus = tokens[1] if len(tokens) > 1 else "0"
        nminus = tokens[2] if len(tokens) > 2 else "0"
        return f"{name} {nplus} {nminus} {first_arg}"

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
            return [self.exe_path, "--threads", str(max(1, int(threads or 1))), netlist_path]
        elif self.simulator == "Ngspice":
            return [self.exe_path, "-b", "-r", output_path, netlist_path]
        elif self.simulator == "Xyce":
            return [self.exe_path, netlist_path,
                    "-o", output_path]
        return [self.exe_path, netlist_path]

    def _extract_gspice_node_aliases(self, netlist: str) -> dict[int, str]:
        """Mirror GSPICE parser node creation order for stdout node labels."""
        aliases: dict[int, str] = {}
        name_to_id = {"0": -1}

        def add_node(name: str) -> None:
            clean = str(name or "").strip()
            if not clean or clean in name_to_id:
                return
            idx = len([v for v in name_to_id.values() if v >= 0])
            name_to_id[clean] = idx
            aliases[idx] = clean

        for raw_line in netlist.splitlines():
            line = raw_line.strip()
            if not line or line.startswith(("*", "$")):
                continue
            tokens = line.split()
            if not tokens:
                continue
            head = tokens[0]
            upper_head = head.upper()
            if upper_head.startswith("."):
                if upper_head in (".NOISE", ".PNOISE") and len(tokens) > 1:
                    match = re.match(r"(?i)V\(([^)]+)\)", tokens[1])
                    if match:
                        add_node(match.group(1))
                continue

            first = upper_head[0]
            if first in {"R", "C", "L", "V", "I", "P", "W", "D"}:
                if len(tokens) > 1:
                    add_node(tokens[1])
                if len(tokens) > 2:
                    add_node(tokens[2])
            elif first == "M":
                for tok in tokens[1:5]:
                    add_node(tok)
            elif first == "S":
                for tok in tokens[1:]:
                    if "=" in tok:
                        break
                    if self._looks_like_node_token(tok):
                        add_node(tok)
                    else:
                        break

        return aliases

    @staticmethod
    def _looks_like_node_token(token: str) -> bool:
        text = str(token or "").strip()
        if not text:
            return False
        if "=" in text:
            return False
        return bool(re.match(r"^[A-Za-z0-9_.$:/+-]+$", text))

    @staticmethod
    def _waveform_name_for_node(index: int, node_aliases: dict[int, str]) -> str:
        name = str(node_aliases.get(index, f"node{index}")).strip()
        if not name or name == "0":
            return f"V(node{index})"
        if name.upper().startswith("V("):
            return name
        return f"V({name})"

    def _parse_gspice_stdout(self, output: str, node_aliases: dict[int, str] | None = None) -> dict:
        """Parse GSPICE's stdout table output into simple waveform arrays."""
        node_aliases = node_aliases or {}
        waveforms: dict[str, list[float]] = {}
        for line in output.splitlines():
            if "Node " in line and "=" in line:
                for node, value in re.findall(r"Node\s+(\d+)=([-+0-9.eE]+)V", line):
                    idx = int(node)
                    waveforms.setdefault(self._waveform_name_for_node(idx, node_aliases), []).append(float(value))
                continue
            if "|" not in line:
                continue
            left, right = line.split("|", 1)
            try:
                t = float(left.strip())
            except ValueError:
                continue
            values = []
            for token in right.split():
                try:
                    values.append(float(token))
                except ValueError:
                    pass
            if not values:
                continue
            waveforms.setdefault("time", []).append(t)
            for idx, value in enumerate(values):
                waveforms.setdefault(self._waveform_name_for_node(idx, node_aliases), []).append(value)
        return waveforms

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
