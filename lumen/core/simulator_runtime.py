"""
Simulator runtime discovery, configuration, and install helpers.

This mirrors the KLayout runtime pattern so simulator setup is portable
across machines and persisted per workspace.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from lumen.core.simulator import SIMULATOR_INFO, normalize_simulator_name

# Public simulator choices exposed by Lumen.  Ngspice/Xyce bridge code is kept
# in place for a future re-enable, but the product surface is GSPICE-only while
# the native simulator is being brought up to signoff-class RF coverage.
ACTIVE_SIMULATORS = ("GSPICE",)


@dataclass
class SimulatorInstallation:
    simulator: str
    executable: str
    version: str = ""
    source: str = "auto"
    available: bool = True


@dataclass
class SimulatorInstallResult:
    success: bool
    message: str
    simulator: str
    executable: str = ""
    method: str = ""
    logs: list[str] | None = None


class SimulatorRuntimeManager:
    """Discovers simulator runtimes and persists selected executables."""

    CONFIG_FILENAME = ".lumen_simulators.json"
    ENV_MAP = {
        "GSPICE": "LUMEN_GSPICE_EXE",
        "Ngspice": "LUMEN_NGSPICE_EXE",
        "Xyce": "LUMEN_XYCE_EXE",
    }

    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace or "").expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.config_path = self.workspace / self.CONFIG_FILENAME
        self._config = self._load_config()

    def discover_installations(self, simulator: str) -> list[SimulatorInstallation]:
        sim = self._normalize_simulator(simulator)
        if not sim or sim not in ACTIVE_SIMULATORS:
            return []

        candidates: list[tuple[str, str]] = []
        env_var = self.ENV_MAP.get(sim, "")
        if env_var:
            env_path = os.environ.get(env_var, "").strip()
            if env_path:
                candidates.append((env_path, f"env:{env_var}"))
        env_any = os.environ.get("LUMEN_SIM_EXE", "").strip()
        if env_any:
            candidates.append((env_any, "env:LUMEN_SIM_EXE"))

        configured = self._normalize_executable(
            self._config.get("simulators", {}).get(sim, {}).get("active_executable", "")
        )
        if configured:
            candidates.append((configured, "config"))

        for path in self._preferred_candidate_paths(sim):
            candidates.append((path, "preferred"))

        for path in SIMULATOR_INFO.get(sim, {}).get("candidates", []):
            candidates.append((str(path), "default"))

        for name in self._command_candidates(sim):
            candidates.append((name, "path"))

        unique: set[str] = set()
        found: list[SimulatorInstallation] = []
        for path, source in candidates:
            norm = self._normalize_executable(path)
            if not norm or norm in unique:
                continue
            unique.add(norm)
            resolved = self._resolve_executable(norm)
            if not resolved:
                continue
            version = self.probe_version(sim, resolved)
            found.append(
                SimulatorInstallation(
                    simulator=sim,
                    executable=resolved,
                    version=version,
                    source=source,
                    available=True,
                )
            )
        return found

    def get_active_executable(self, simulator: str) -> str:
        sim = self._normalize_simulator(simulator)
        if not sim or sim not in ACTIVE_SIMULATORS:
            return ""
        prefer_klu = sim == "GSPICE" and self.gspice_prefer_klu()
        configured = self._normalize_executable(
            self._config.get("simulators", {}).get(sim, {}).get("active_executable", "")
        )
        if configured:
            resolved = self._resolve_executable(configured)
            if resolved:
                configured_source = str(
                    self._config.get("simulators", {}).get(sim, {}).get("active_source", "")
                ).lower()
                if (
                    prefer_klu
                    and configured_source in {"", "auto", "default", "path", "config", "preferred"}
                    and not self._gspice_executable_has_klu(resolved)
                ):
                    preferred = self._find_preferred_gspice_klu()
                    if preferred:
                        self.set_active_executable(sim, preferred, source="preferred-klu")
                        return preferred
                return resolved
        discovered = self.discover_installations(sim)
        if discovered:
            self.set_active_executable(sim, discovered[0].executable, source=discovered[0].source)
            return discovered[0].executable
        return ""

    def gspice_prefer_klu(self) -> bool:
        entry = self._config.get("simulators", {}).get("GSPICE", {})
        return bool(entry.get("prefer_klu", True))

    def set_gspice_prefer_klu(self, enabled: bool) -> bool:
        self._config.setdefault("simulators", {}).setdefault("GSPICE", {})["prefer_klu"] = bool(enabled)
        if enabled:
            active = self.get_active_executable("GSPICE")
            if not active or not self._gspice_executable_has_klu(active):
                preferred = self._find_preferred_gspice_klu()
                if not preferred:
                    self._save_config()
                    return False
                self.set_active_executable("GSPICE", preferred, source="preferred-klu")
        self._save_config()
        return True

    def active_gspice_has_klu(self) -> bool:
        return self._gspice_executable_has_klu(self.get_active_executable("GSPICE"))

    def set_active_executable(self, simulator: str, executable: str, source: str = "manual") -> bool:
        sim = self._normalize_simulator(simulator)
        if not sim or sim not in ACTIVE_SIMULATORS:
            return False
        norm = self._normalize_executable(executable)
        if not norm:
            return False
        resolved = self._resolve_executable(norm)
        if not resolved:
            return False

        self._config.setdefault("simulators", {})
        self._config["simulators"].setdefault(sim, {})
        self._config["simulators"][sim]["active_executable"] = resolved
        self._config["simulators"][sim]["active_source"] = source
        version = self.probe_version(sim, resolved)
        if version:
            self._config["simulators"][sim]["active_version"] = version
        self._save_config()

        env_var = self.ENV_MAP.get(sim)
        if env_var:
            os.environ[env_var] = resolved
        return True

    def clear_active_executable(self, simulator: str) -> None:
        sim = self._normalize_simulator(simulator)
        if not sim:
            return
        entry = self._config.get("simulators", {}).get(sim, {})
        entry.pop("active_executable", None)
        entry.pop("active_source", None)
        entry.pop("active_version", None)
        self._save_config()
        env_var = self.ENV_MAP.get(sim)
        if env_var and env_var in os.environ:
            del os.environ[env_var]

    def apply_environment_overrides(self) -> None:
        for sim in ACTIVE_SIMULATORS:
            env_var = self.ENV_MAP.get(sim, "")
            exe = self.get_active_executable(sim)
            if env_var and exe:
                os.environ[env_var] = exe

    def runtime_summary(self) -> dict:
        sims = {}
        for sim in ACTIVE_SIMULATORS:
            active = self.get_active_executable(sim)
            sims[sim] = {
                "active_executable": active,
                "active_version": self.probe_version(sim, active) if active else "",
                "discovered": [asdict(x) for x in self.discover_installations(sim)],
                "runtime_available": bool(active),
            }
        return {
            "config_path": str(self.config_path),
            "active_simulator": self.get_active_simulator(),
            "simulators": sims,
        }

    def get_active_simulator(self) -> str:
        sim = self._normalize_simulator(self._config.get("active_simulator", "GSPICE"))
        return sim if sim in ACTIVE_SIMULATORS else "GSPICE"

    def set_active_simulator(self, simulator: str) -> bool:
        sim = self._normalize_simulator(simulator)
        if sim not in ACTIVE_SIMULATORS:
            return False
        self._config["active_simulator"] = sim
        self._save_config()
        return True

    def ensure_runtime(self, simulator: str, auto_install: bool = False) -> tuple[bool, str]:
        sim = self._normalize_simulator(simulator)
        active = self.get_active_executable(sim)
        if active:
            return True, f"{sim} runtime ready: {active}"
        if not auto_install:
            return False, f"{sim} is not installed or not configured."
        result = self.install_if_missing(sim)
        return result.success, result.message

    def install_if_missing(self, simulator: str) -> SimulatorInstallResult:
        sim = self._normalize_simulator(simulator)
        if sim not in ACTIVE_SIMULATORS:
            return SimulatorInstallResult(
                success=False,
                message=f"{sim} install is not enabled in this Lumen build.",
                simulator=sim,
                method="disabled",
                logs=[],
            )
        active = self.get_active_executable(sim)
        if active:
            return SimulatorInstallResult(
                success=True,
                message=f"{sim} already available: {active}",
                simulator=sim,
                executable=active,
                method="existing",
                logs=[],
            )

        logs: list[str] = []
        if os.name != "nt":
            return SimulatorInstallResult(
                success=False,
                message=(
                    f"Automatic install for {sim} is currently implemented for Windows only. "
                    "Install it using your package manager and set executable manually."
                ),
                simulator=sim,
                method=platform.system().lower(),
                logs=logs,
            )

        local = self._install_windows_local(sim)
        logs.extend(local.logs or [])
        if local.success:
            local.logs = logs
            return local

        choco = self._install_windows_choco(sim)
        logs.extend(choco.logs or [])
        if choco.success:
            choco.logs = logs
            return choco

        winget = self._install_windows_winget(sim)
        logs.extend(winget.logs or [])
        if winget.success:
            winget.logs = logs
            return winget

        return SimulatorInstallResult(
            success=False,
            message=(
                f"Could not install {sim} automatically. "
                "Use 'Locate Executable' in Simulator Manager after manual installation."
            ),
            simulator=sim,
            method="windows",
            logs=logs,
        )

    def probe_version(self, simulator: str, executable: str) -> str:
        sim = self._normalize_simulator(simulator)
        exe = self._normalize_executable(executable)
        if not sim or not exe:
            return ""
        resolved = self._resolve_executable(exe)
        if not resolved:
            return ""
        probes = {
            "GSPICE": [[resolved, "--version"], [resolved, "-v"]],
            "Ngspice": [[resolved, "--version"], [resolved, "-v"]],
            "Xyce": [[resolved, "-v"], [resolved, "--version"]],
        }.get(sim, [[resolved, "--version"]])
        for cmd in probes:
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
            except (OSError, subprocess.TimeoutExpired):
                continue
            text = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
            if not text:
                continue
            line = text.splitlines()[0].strip()
            if line:
                return line[:120]
        return ""

    def _install_windows_local(self, simulator: str) -> SimulatorInstallResult:
        logs: list[str] = []
        installer = self._find_local_windows_installer(simulator)
        if not installer:
            return SimulatorInstallResult(
                success=False,
                message=f"No local installer found for {simulator}.",
                simulator=simulator,
                method="local_installer",
                logs=["No matching installer found in local tool folders."],
            )

        suffix = Path(installer).suffix.lower()
        if suffix == ".msi":
            cmd = ["msiexec", "/i", installer, "/qn", "/norestart"]
        else:
            cmd = [installer, "/S"]

        logs.append(f"Running local installer: {' '.join(cmd)}")
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logs.append(f"Installer launch failed: {exc}")
            return SimulatorInstallResult(
                success=False,
                message=f"Local installer failed: {exc}",
                simulator=simulator,
                method="local_installer",
                logs=logs,
            )

        if (proc.stdout or "").strip():
            logs.append((proc.stdout or "").strip())
        if (proc.stderr or "").strip():
            logs.append((proc.stderr or "").strip())

        exe = self.get_active_executable(simulator)
        if exe:
            return SimulatorInstallResult(
                success=True,
                message=f"{simulator} installed from local installer: {exe}",
                simulator=simulator,
                executable=exe,
                method="local_installer",
                logs=logs,
            )
        return SimulatorInstallResult(
            success=False,
            message=f"Local installer ran but {simulator} executable was not discovered.",
            simulator=simulator,
            method="local_installer",
            logs=logs,
        )

    def _install_windows_choco(self, simulator: str) -> SimulatorInstallResult:
        logs: list[str] = []
        package_map = {"GSPICE": "gspice", "Ngspice": "ngspice", "Xyce": "xyce"}
        package = package_map.get(simulator, simulator.lower())
        choco = shutil.which("choco")
        if not choco:
            return SimulatorInstallResult(
                success=False,
                message="Chocolatey not found.",
                simulator=simulator,
                method="choco",
                logs=["Chocolatey executable not found in PATH."],
            )
        cmd = [choco, "install", package, "-y", "--no-progress"]
        logs.append(f"Running: {' '.join(cmd)}")
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logs.append(f"Chocolatey launch failed: {exc}")
            return SimulatorInstallResult(
                success=False,
                message=f"Chocolatey install failed: {exc}",
                simulator=simulator,
                method="choco",
                logs=logs,
            )

        if (proc.stdout or "").strip():
            logs.append((proc.stdout or "").strip())
        if (proc.stderr or "").strip():
            logs.append((proc.stderr or "").strip())
        if proc.returncode != 0:
            return SimulatorInstallResult(
                success=False,
                message=f"Chocolatey installation failed for package '{package}'.",
                simulator=simulator,
                method="choco",
                logs=logs,
            )

        exe = self.get_active_executable(simulator)
        if exe:
            return SimulatorInstallResult(
                success=True,
                message=f"{simulator} installed via Chocolatey: {exe}",
                simulator=simulator,
                executable=exe,
                method="choco",
                logs=logs,
            )
        return SimulatorInstallResult(
            success=False,
            message=f"Chocolatey completed but {simulator} executable was not discovered.",
            simulator=simulator,
            method="choco",
            logs=logs,
        )

    def _install_windows_winget(self, simulator: str) -> SimulatorInstallResult:
        logs: list[str] = []
        winget = shutil.which("winget")
        if not winget:
            return SimulatorInstallResult(
                success=False,
                message="winget not found.",
                simulator=simulator,
                method="winget",
                logs=["winget executable not found in PATH."],
            )

        name_map = {"GSPICE": "gspice", "Ngspice": "ngspice", "Xyce": "xyce"}
        query = name_map.get(simulator, simulator.lower())
        cmd = [winget, "install", "--silent", "--accept-source-agreements", "--accept-package-agreements", query]
        logs.append(f"Running: {' '.join(cmd)}")
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logs.append(f"winget launch failed: {exc}")
            return SimulatorInstallResult(
                success=False,
                message=f"winget install failed: {exc}",
                simulator=simulator,
                method="winget",
                logs=logs,
            )
        if (proc.stdout or "").strip():
            logs.append((proc.stdout or "").strip())
        if (proc.stderr or "").strip():
            logs.append((proc.stderr or "").strip())

        exe = self.get_active_executable(simulator)
        if exe:
            return SimulatorInstallResult(
                success=True,
                message=f"{simulator} installed via winget: {exe}",
                simulator=simulator,
                executable=exe,
                method="winget",
                logs=logs,
            )
        return SimulatorInstallResult(
            success=False,
            message=f"winget completed but {simulator} executable was not discovered.",
            simulator=simulator,
            method="winget",
            logs=logs,
        )

    def _find_local_windows_installer(self, simulator: str) -> str:
        roots = [
            self.workspace / "external" / "tools",
            self.workspace / "tools",
            Path.cwd() / "tools",
            Path("C:/EDA/LumenCircuitStudio/external/tools"),
            Path("C:/EDA/LumenCircuitStudio/tools"),
            Path("C:/EDA/tools"),
            self.workspace,
        ]
        tokens = {
            "GSPICE": ["gspice"],
            "Ngspice": ["ngspice"],
            "Xyce": ["xyce"],
        }.get(simulator, [simulator.lower()])
        best = ""
        patterns = [
            "*install*.exe",
            "*.msi",
            "*.exe",
        ]
        for root in roots:
            if not root.exists():
                continue
            for pattern in patterns:
                for candidate in sorted(root.glob(pattern)):
                    name = candidate.name.lower()
                    if any(tok in name for tok in tokens):
                        best = str(candidate)
        return best

    def _default_candidate_paths(self, simulator: str) -> list[str]:
        defaults = [str(x) for x in SIMULATOR_INFO.get(simulator, {}).get("candidates", [])]
        return [p for p in defaults if p]

    def _preferred_candidate_paths(self, simulator: str) -> list[str]:
        if simulator != "GSPICE":
            return []
        return [
            r"C:\EDA\GSPICE\build-klu\Release\gspice.exe",
            r"C:\EDA\GSPICE\build-vcpkg\Release\gspice.exe",
            r"C:\EDA\GSPICE\build-vcpkg\gspice.exe",
            r"C:\EDA\GSPICE\build\Release\gspice.exe",
        ]

    def _find_preferred_gspice_klu(self) -> str:
        for installation in self.discover_installations("GSPICE"):
            if self._gspice_executable_has_klu(installation.executable):
                return installation.executable
        return ""

    def _gspice_executable_has_klu(self, executable: str) -> bool:
        exe = self._resolve_executable(executable)
        if not exe:
            return False
        try:
            proc = subprocess.run(
                [exe, "--capabilities"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        text = f"{proc.stdout}\n{proc.stderr}"
        return "SuiteSparse-KLU" in text

    def _command_candidates(self, simulator: str) -> list[str]:
        names = {
            "GSPICE": ["gspice.exe", "gspice"],
            "Ngspice": ["ngspice.exe", "ngspice"],
            "Xyce": ["Xyce.exe", "Xyce"],
        }.get(simulator, [])
        return [name for name in names if shutil.which(name)]

    @staticmethod
    def _normalize_simulator(simulator: str) -> str:
        return normalize_simulator_name(simulator)

    @staticmethod
    def _normalize_executable(path: str) -> str:
        return str(path or "").strip().strip('"')

    @staticmethod
    def _resolve_executable(candidate: str) -> str:
        normalized = SimulatorRuntimeManager._normalize_executable(candidate)
        if not normalized:
            return ""
        if Path(normalized).is_file():
            return str(Path(normalized))
        found = shutil.which(normalized)
        return found or ""

    def _load_config(self) -> dict:
        if not self.config_path.exists():
            return {"version": 1, "simulators": {}}
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("simulators", {})
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return {"version": 1, "simulators": {}}

    def _save_config(self) -> None:
        payload = dict(self._config)
        payload.setdefault("version", 1)
        payload.setdefault("simulators", {})
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
