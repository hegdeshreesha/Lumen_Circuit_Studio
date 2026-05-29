"""
KLayout runtime discovery and configuration.

This module keeps KLayout integration upgrade-friendly by separating runtime
selection from the rest of the layout flow. Users can switch to newer KLayout
versions without code changes.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


@dataclass
class KLayoutInstallation:
    """Resolved KLayout runtime candidate."""

    executable: str
    version: str = ""
    source: str = "auto"
    available: bool = True


@dataclass
class KLayoutInstallResult:
    """Outcome for install-on-missing flow."""

    success: bool
    message: str
    executable: str = ""
    method: str = ""
    logs: list[str] | None = None


class KLayoutRuntimeManager:
    """Discovers KLayout runtimes and persists the selected executable."""

    CONFIG_FILENAME = ".lumen_klayout.json"
    CHOCO_INSTALL_SCRIPT_URL = (
        "https://raw.githubusercontent.com/chtof/chocolatey-packages/"
        "master/automatic/klayout/tools/chocolateyinstall.ps1"
    )
    VERSION_PATTERN = re.compile(r"(\d+\.\d+(?:\.\d+)?)")

    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.config_path = self.workspace / self.CONFIG_FILENAME
        self._config = self._load_config()

    def discover_installations(self) -> list[KLayoutInstallation]:
        """Return available KLayout runtime candidates with version metadata."""
        candidates: list[tuple[str, str]] = []

        env_paths = [
            ("env:LUMEN_KLAYOUT_EXE", os.environ.get("LUMEN_KLAYOUT_EXE", "").strip()),
            ("env:KLAYOUT_EXE", os.environ.get("KLAYOUT_EXE", "").strip()),
        ]
        for source, path in env_paths:
            if path:
                candidates.append((path, source))

        for path in self._default_candidate_paths():
            candidates.append((path, "default"))

        for path in self._command_candidates():
            candidates.append((path, "path"))

        unique_paths: set[str] = set()
        installations: list[KLayoutInstallation] = []

        for path, source in candidates:
            norm = self._normalize_executable(path)
            if not norm or norm in unique_paths:
                continue
            unique_paths.add(norm)

            resolved = self._resolve_executable(norm)
            if not resolved:
                continue
            version = self._probe_version(resolved)
            available = bool(version or Path(resolved).is_file() or shutil.which(resolved))
            installations.append(
                KLayoutInstallation(
                    executable=resolved,
                    version=version,
                    source=source,
                    available=available,
                )
            )

        return installations

    def get_active_installation(self) -> Optional[KLayoutInstallation]:
        """Get the currently selected runtime, auto-falling back if needed."""
        active = self.get_active_executable()
        if not active:
            return None
        return KLayoutInstallation(
            executable=active,
            version=self._probe_version(active),
            source=self._config.get("active_source", "auto"),
            available=True,
        )

    def get_active_executable(self) -> str:
        """Return the configured runtime path or discover a default one."""
        configured = self._normalize_executable(self._config.get("active_executable", ""))
        if configured:
            resolved = self._resolve_executable(configured)
            if resolved:
                return resolved

        discovered = self.discover_installations()
        if discovered:
            first = discovered[0]
            self.set_active_executable(first.executable, source=first.source)
            return first.executable
        return ""

    def set_active_executable(self, executable: str, source: str = "manual") -> bool:
        """Persist a runtime executable path."""
        normalized = self._normalize_executable(executable)
        if not normalized:
            return False
        resolved = self._resolve_executable(normalized)
        if not resolved:
            return False

        self._config["active_executable"] = resolved
        self._config["active_source"] = source
        version = self._probe_version(resolved)
        if version:
            self._config["active_version"] = version
        self._save_config()
        return True

    def clear_active_executable(self):
        """Forget pinned runtime and allow rediscovery."""
        self._config.pop("active_executable", None)
        self._config.pop("active_source", None)
        self._config.pop("active_version", None)
        self._save_config()

    def runtime_summary(self) -> dict:
        """Small status dictionary for UI/log display."""
        active = self.get_active_installation()
        discovered = self.discover_installations()
        return {
            "runtime_available": bool(active),
            "active_executable": active.executable if active else "",
            "active_version": active.version if active else "",
            "discovered": [asdict(entry) for entry in discovered],
            "config_path": str(self.config_path),
        }

    def ensure_runtime(self, auto_install: bool = False) -> tuple[bool, str]:
        """Ensure a runtime exists, optionally attempting installation."""
        active = self.get_active_executable()
        if active:
            return True, f"KLayout runtime ready: {active}"
        if not auto_install:
            return False, "KLayout is not installed or not configured."
        install = self.install_if_missing()
        return install.success, install.message

    def install_if_missing(self) -> KLayoutInstallResult:
        """Install KLayout if no runtime is currently available."""
        active = self.get_active_executable()
        if active:
            return KLayoutInstallResult(
                success=True,
                message=f"KLayout already available: {active}",
                executable=active,
                method="existing",
                logs=[],
            )

        logs: list[str] = []
        if os.name == "nt":
            local_installer_result = self._install_windows_local_installer()
            logs.extend(local_installer_result.logs or [])
            if local_installer_result.success:
                local_installer_result.logs = logs
                return local_installer_result

            choco_result = self._install_windows_choco()
            logs.extend(choco_result.logs or [])
            if choco_result.success:
                return choco_result

            portable_result = self._install_windows_portable()
            logs.extend(portable_result.logs or [])
            if portable_result.success:
                portable_result.logs = logs
                return portable_result

            return KLayoutInstallResult(
                success=False,
                message=(
                    "KLayout install failed via Chocolatey and portable ZIP fallback. "
                    "Use KLayout Runtime... and set an existing executable manually."
                ),
                method="windows",
                logs=logs,
            )

        return KLayoutInstallResult(
            success=False,
            message=(
                "Automatic install is currently implemented for Windows only. "
                "Install KLayout from your package manager and set the executable path."
            ),
            method=platform.system().lower(),
            logs=logs,
        )

    def _load_config(self) -> dict:
        if not self.config_path.exists():
            return {"version": 1}
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return {"version": 1}

    def _save_config(self):
        data = dict(self._config)
        data.setdefault("version", 1)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _resolve_executable(self, candidate: str) -> str:
        candidate = self._normalize_executable(candidate)
        if not candidate:
            return ""
        path = Path(candidate)
        if path.is_file():
            return str(path)
        found = shutil.which(candidate)
        return found or ""

    def _probe_version(self, executable: str) -> str:
        commands = [
            [executable, "-v"],
            [executable, "-zz", "-v"],
        ]
        for cmd in commands:
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            text = (proc.stdout or "") + "\n" + (proc.stderr or "")
            match = self.VERSION_PATTERN.search(text)
            if match:
                return match.group(1)
            if proc.returncode == 0 and text.strip():
                return text.strip().splitlines()[0].strip()
        return ""

    def _command_candidates(self) -> list[str]:
        names = ["klayout_app.exe", "klayout.exe", "klayout_app", "klayout"]
        resolved = [shutil.which(name) or "" for name in names]
        return [p for p in resolved if p]

    def _install_windows_local_installer(self) -> KLayoutInstallResult:
        """Try local installer EXE first (non-admin friendly destination)."""
        logs: list[str] = []
        installer = self._find_local_windows_installer()
        if not installer:
            return KLayoutInstallResult(
                success=False,
                message="No local KLayout installer found.",
                method="local_installer",
                logs=["No klayout-*-install.exe found in known local tool folders."],
            )

        install_root = str(self._portable_install_root())
        Path(install_root).mkdir(parents=True, exist_ok=True)
        cmd = [installer, "/S", f"/D={install_root}"]
        logs.append(f"Running local installer: {' '.join(cmd)}")
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=1800,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logs.append(f"Local installer launch failed: {exc}")
            return KLayoutInstallResult(
                success=False,
                message=f"Local installer failed: {exc}",
                method="local_installer",
                logs=logs,
            )

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        if stdout.strip():
            logs.append(stdout.strip())
        if stderr.strip():
            logs.append(stderr.strip())

        exe = self._find_klayout_executable_under(Path(install_root))
        if exe:
            self.set_active_executable(exe, source="local_installer")
            return KLayoutInstallResult(
                success=True,
                message=f"KLayout installed from local installer: {exe}",
                executable=exe,
                method="local_installer",
                logs=logs,
            )

        return KLayoutInstallResult(
            success=False,
            message=(
                "Local KLayout installer ran but no executable was found "
                f"under {install_root}."
            ),
            method="local_installer",
            logs=logs,
        )

    def _install_windows_choco(self) -> KLayoutInstallResult:
        logs: list[str] = []
        choco = shutil.which("choco")
        if not choco:
            return KLayoutInstallResult(
                success=False,
                message="Chocolatey not found.",
                method="choco",
                logs=["Chocolatey executable not found in PATH."],
            )

        cmd = [choco, "install", "klayout", "-y", "--no-progress"]
        logs.append(f"Running: {' '.join(cmd)}")
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logs.append(f"Chocolatey launch failed: {exc}")
            return KLayoutInstallResult(
                success=False,
                message=f"Chocolatey install failed: {exc}",
                method="choco",
                logs=logs,
            )

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        if stdout.strip():
            logs.append(stdout.strip())
        if stderr.strip():
            logs.append(stderr.strip())
        if proc.returncode != 0:
            return KLayoutInstallResult(
                success=False,
                message="Chocolatey installation did not complete successfully.",
                method="choco",
                logs=logs,
            )

        discovered = self.discover_installations()
        if discovered:
            chosen = discovered[0]
            self.set_active_executable(chosen.executable, source="choco")
            return KLayoutInstallResult(
                success=True,
                message=f"KLayout installed via Chocolatey: {chosen.executable}",
                executable=chosen.executable,
                method="choco",
                logs=logs,
            )

        return KLayoutInstallResult(
            success=False,
            message="Chocolatey finished but no KLayout executable was discovered.",
            method="choco",
            logs=logs,
        )

    def _install_windows_portable(self) -> KLayoutInstallResult:
        logs: list[str] = []
        install_root = self._portable_install_root()
        install_root.mkdir(parents=True, exist_ok=True)
        urls = self._resolve_windows_portable_urls()
        if not urls:
            return KLayoutInstallResult(
                success=False,
                message="No portable KLayout URLs resolved.",
                method="portable",
                logs=["Unable to resolve KLayout portable download URL."],
            )

        for url in urls:
            try:
                logs.append(f"Downloading: {url}")
                archive = self._download_to_temp(url)
                with zipfile.ZipFile(archive, "r") as zf:
                    zf.extractall(install_root)
                exe = self._find_klayout_executable_under(install_root)
                if exe:
                    self.set_active_executable(exe, source="portable")
                    return KLayoutInstallResult(
                        success=True,
                        message=f"KLayout installed (portable): {exe}",
                        executable=exe,
                        method="portable",
                        logs=logs,
                    )
                logs.append("Archive extracted but executable not found.")
            except (urllib.error.URLError, OSError, zipfile.BadZipFile) as exc:
                logs.append(f"Portable install failed for {url}: {exc}")
                continue

        return KLayoutInstallResult(
            success=False,
            message="Portable KLayout install failed.",
            method="portable",
            logs=logs,
        )

    def _resolve_windows_portable_urls(self) -> list[str]:
        """Resolve portable ZIP URLs, preferring URLs inferred from upstream package script."""
        urls: list[str] = []
        script = self._fetch_choco_install_script()
        if script:
            match64 = re.search(r"url64\s*=\s*'([^']+)'", script)
            match32 = re.search(r"url\s*=\s*'([^']+)'", script)
            for match in (match64, match32):
                if not match:
                    continue
                installer_url = match.group(1).strip()
                zip_url = installer_url.replace("-install.exe", ".zip")
                urls.append(zip_url)

        urls.extend(
            [
                "https://www.klayout.org/downloads/Windows/klayout-0.30.8-win64.zip",
                "https://www.klayout.org/downloads/Windows/klayout-0.30.8-win32.zip",
            ]
        )
        deduped: list[str] = []
        seen: set[str] = set()
        for url in urls:
            norm = url.strip()
            if not norm or norm in seen:
                continue
            seen.add(norm)
            deduped.append(norm)
        return deduped

    def _fetch_choco_install_script(self) -> str:
        try:
            with urllib.request.urlopen(self.CHOCO_INSTALL_SCRIPT_URL, timeout=20) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except (urllib.error.URLError, OSError, TimeoutError):
            return ""

    def _portable_install_root(self) -> Path:
        home = Path.home()
        return home / "LumenTools" / "KLayoutPortable"

    def _find_local_windows_installer(self) -> str:
        patterns = [
            self.workspace / "external" / "tools",
            self.workspace / "tools",
            Path.cwd() / "tools",
            Path("C:/EDA/LumenCircuitStudio/external/tools"),
            Path("C:/EDA/LumenCircuitStudio/tools"),
            Path("C:/EDA/tools"),
            self.workspace,
        ]
        best = ""
        for base in patterns:
            if not base.exists():
                continue
            for candidate in sorted(base.glob("klayout-*-install.exe")):
                best = str(candidate)
            for candidate in sorted(base.glob("*klayout*-install*.exe")):
                best = str(candidate)
        return best

    def _download_to_temp(self, url: str) -> Path:
        fd, temp_path = tempfile.mkstemp(prefix="lumen_klayout_", suffix=".zip")
        os.close(fd)
        target = Path(temp_path)
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "LumenCircuitStudio/0.3"},
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            with open(target, "wb") as out:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
        return target

    def _find_klayout_executable_under(self, root: Path) -> str:
        candidates = ["klayout_app.exe", "klayout.exe"]
        for name in candidates:
            for path in root.rglob(name):
                if path.is_file():
                    return str(path)
        return ""

    def _default_candidate_paths(self) -> list[str]:
        home = Path.home()
        portable_root = self._portable_install_root()
        return [
            r"C:\Program Files\KLayout\klayout_app.exe",
            r"C:\Program Files\KLayout\klayout.exe",
            r"C:\Program Files (x86)\KLayout\klayout_app.exe",
            r"C:\Program Files (x86)\KLayout\klayout.exe",
            r"C:\EDA\LumenCircuitStudio\external\tools\KLayout\klayout_app.exe",
            r"C:\EDA\LumenCircuitStudio\external\tools\KLayout\klayout.exe",
            r"C:\EDA\LumenCircuitStudio\external\tools\KLayoutPortable\klayout_app.exe",
            r"C:\EDA\LumenCircuitStudio\external\tools\KLayoutPortable\klayout.exe",
            r"C:\EDA\LumenCircuitStudio\tools\KLayout\klayout_app.exe",
            r"C:\EDA\LumenCircuitStudio\tools\KLayout\klayout.exe",
            r"C:\EDA\LumenCircuitStudio\tools\KLayoutPortable\klayout_app.exe",
            r"C:\EDA\LumenCircuitStudio\tools\KLayoutPortable\klayout.exe",
            r"C:\EDA\tools\KLayout\klayout_app.exe",
            r"C:\EDA\tools\KLayout\klayout.exe",
            r"C:\EDA\tools\KLayoutPortable\klayout_app.exe",
            r"C:\EDA\tools\KLayoutPortable\klayout.exe",
            str(portable_root / "klayout_app.exe"),
            str(portable_root / "klayout.exe"),
            str(home / "AppData" / "Local" / "Programs" / "KLayout" / "klayout_app.exe"),
            str(home / "AppData" / "Local" / "Programs" / "KLayout" / "klayout.exe"),
            "/usr/bin/klayout",
            "/usr/local/bin/klayout",
            "/opt/homebrew/bin/klayout",
        ]

    def _normalize_executable(self, executable: str) -> str:
        return str(executable or "").strip().strip('"').strip("'")
