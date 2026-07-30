"""
KLayout command adapter.

Encapsulates command construction and process execution so higher layers can
use layout actions without hard-coding command line details.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from .ihp_klayout_devices import build_device_catalog
from .layout_layers import parse_klayout_layer_properties
from .klayout_runtime import KLayoutRuntimeManager


@dataclass
class KLayoutProcessResult:
    success: bool = False
    command: list[str] = field(default_factory=list)
    returncode: int = -1
    stdout: str = ""
    stderr: str = ""
    elapsed_time: float = 0.0
    pid: int = 0
    error: str = ""


class KLayoutAdapterError(RuntimeError):
    """Raised when KLayout is unavailable or cannot be launched."""


@dataclass
class KLayoutPDKProfile:
    """KLayout technology profile resolved from a local PDK tree."""

    name: str
    display_name: str
    pdk_root: str
    pdk: str
    klayout_root: str
    technology_name: str
    technology_file: str
    layer_properties_file: str
    drc_script: str = ""
    lvs_script: str = ""
    python_root: str = ""
    pcell_library: str = "SG13_dev"
    pcell_bootstrap: str = ""
    pcell_templates: str = ""
    netlist_import_macro: str = ""
    pycell_api_root: str = ""
    pypreprocessor_root: str = ""
    pcells_available: bool = False
    pcell_count: int = 0
    device_correspondence: list[dict] = field(default_factory=list)
    missing_pcell_dependencies: list[str] = field(default_factory=list)
    layers: list[dict] = field(default_factory=list)
    available: bool = False
    message: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


class KLayoutCLIAdapter:
    """CLI adapter for launching KLayout GUI and batch jobs."""

    def __init__(
        self,
        workspace: str | Path,
        runtime_manager: Optional[KLayoutRuntimeManager] = None,
    ):
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.runtime_manager = runtime_manager or KLayoutRuntimeManager(self.workspace)
        self.klayout_home = self.workspace / ".klayout"
        self.klayout_home.mkdir(parents=True, exist_ok=True)
        self.bridge_file = self.workspace / ".lumen_klayout_bridge.json"
        self.event_file = self.workspace / ".lumen_klayout_event.json"

    @property
    def bridge_script(self) -> Path:
        """Return the Lumen macro executed inside interactive KLayout sessions."""
        return Path(__file__).resolve().parents[1] / "klayout" / "lumen_ihp_bridge.py"

    def resolve_ihp_sg13g2_profile(self) -> KLayoutPDKProfile:
        """Resolve the bundled/user IHP SG13G2 KLayout technology profile."""
        pdk_dir = self._find_ihp_sg13g2_dir()
        if not pdk_dir:
            return KLayoutPDKProfile(
                name="ihp_sg13g2",
                display_name="IHP SG13G2",
                pdk_root="",
                pdk="ihp-sg13g2",
                klayout_root="",
                technology_name="sg13g2",
                technology_file="",
                layer_properties_file="",
                available=False,
                message="IHP SG13G2 PDK was not found.",
            )

        klayout_root = pdk_dir / "libs.tech" / "klayout"
        tech_file = klayout_root / "tech" / "sg13g2.lyt"
        layer_file = klayout_root / "tech" / "sg13g2.lyp"
        drc_script = klayout_root / "tech" / "drc" / "run_drc.py"
        lvs_script = klayout_root / "tech" / "lvs" / "run_lvs.py"
        python_root = klayout_root / "python"
        pcell_bootstrap = klayout_root / "tech" / "pymacros" / "autorun.lym"
        pcell_templates = python_root / "import_netlist" / "ihp130_pcell_templates.py"
        netlist_import_macro = klayout_root / "tech" / "macros" / "ihp130_import_netlist.lym"
        pycell_api_root = python_root / "pycell4klayout-api" / "source" / "python"
        pypreprocessor_root = python_root / "pypreprocessor" / "pypreprocessor"
        required = [klayout_root, tech_file, layer_file]
        available = all(path.exists() for path in required)
        missing = [str(path) for path in required if not path.exists()]
        pcell_required = [
            pcell_bootstrap,
            pcell_templates,
            pycell_api_root / "cni" / "dlo.py",
            pypreprocessor_root / "__init__.py",
        ]
        missing_pcell_dependencies = [str(path) for path in pcell_required if not path.exists()]
        pcells_available = not missing_pcell_dependencies
        correspondence = build_device_catalog(pcell_templates) if pcell_templates.exists() else []
        layers = parse_klayout_layer_properties(layer_file) if layer_file.exists() else []
        if available and not pcells_available:
            message = (
                "IHP technology found, but SG13_dev PCells are incomplete. "
                "Initialize the PDK's pycell4klayout-api and pypreprocessor submodules."
            )
        elif available:
            message = "IHP SG13G2 technology and SG13_dev PCells ready."
        else:
            message = "Missing: " + ", ".join(missing)
        return KLayoutPDKProfile(
            name="ihp_sg13g2",
            display_name="IHP SG13G2",
            pdk_root=str(pdk_dir.parent),
            pdk=pdk_dir.name,
            klayout_root=str(klayout_root),
            technology_name="sg13g2",
            technology_file=str(tech_file),
            layer_properties_file=str(layer_file),
            drc_script=str(drc_script) if drc_script.exists() else "",
            lvs_script=str(lvs_script) if lvs_script.exists() else "",
            python_root=str(python_root) if python_root.exists() else "",
            pcell_bootstrap=str(pcell_bootstrap) if pcell_bootstrap.exists() else "",
            pcell_templates=str(pcell_templates) if pcell_templates.exists() else "",
            netlist_import_macro=str(netlist_import_macro) if netlist_import_macro.exists() else "",
            pycell_api_root=str(pycell_api_root) if pycell_api_root.exists() else "",
            pypreprocessor_root=str(pypreprocessor_root) if pypreprocessor_root.exists() else "",
            pcells_available=pcells_available,
            pcell_count=len(correspondence),
            device_correspondence=[item.as_dict() for item in correspondence],
            missing_pcell_dependencies=missing_pcell_dependencies,
            layers=[layer.as_dict() for layer in layers],
            available=available,
            message=message,
        )

    def build_environment(self, pdk_profile: Optional[KLayoutPDKProfile] = None) -> dict[str, str]:
        """Build a process environment matching IHP/IIC-OSIC KLayout expectations."""
        env = dict(os.environ)
        exe = ""
        try:
            exe = self.get_executable()
        except KLayoutAdapterError:
            pass
        if exe:
            exe_dir = str(Path(exe).parent)
            env["PATH"] = self._prepend_path(env.get("PATH", ""), exe_dir)
            env["Path"] = env["PATH"]

        env.setdefault("KLAYOUT_HOME", str(self.klayout_home))
        env["LUMEN_KLAYOUT_BRIDGE_FILE"] = str(self.bridge_file)
        env["LUMEN_KLAYOUT_EVENT_FILE"] = str(self.event_file)
        pycache = self.workspace / ".cache" / "klayout_pycache"
        pycache.mkdir(parents=True, exist_ok=True)
        env.setdefault("PYTHONPYCACHEPREFIX", str(pycache))

        profile = pdk_profile
        if profile and profile.available:
            env["PDK_ROOT"] = profile.pdk_root
            env["PDK"] = profile.pdk
            env["PDKPATH"] = str(Path(profile.pdk_root) / profile.pdk)
            env.setdefault("STD_CELL_LIBRARY", "sg13g2_stdcell")
            env["KLAYOUT_HOME"] = str(self.klayout_home)
            klayout_paths = [
                env["KLAYOUT_HOME"],
                profile.klayout_root,
                str(Path(profile.klayout_root) / "tech"),
            ]
            env["KLAYOUT_PATH"] = self._join_unique_paths(klayout_paths + [env.get("KLAYOUT_PATH", "")])
            if profile.python_root:
                python_paths = [profile.python_root]
                if profile.pycell_api_root:
                    python_paths.append(profile.pycell_api_root)
                env["PYTHONPATH"] = self._join_unique_paths(python_paths + [env.get("PYTHONPATH", "")])
        return env

    def get_executable(self) -> str:
        exe = self.runtime_manager.get_active_executable()
        if not exe:
            raise KLayoutAdapterError(
                "KLayout executable not found. Configure one in Layout Integration settings."
            )
        return exe

    def build_open_layout_command(
        self,
        layout_file: str = "",
        technology_file: str = "",
        technology_name: str = "",
        layer_props_file: str = "",
        extra_args: Optional[list[str]] = None,
    ) -> list[str]:
        cmd = [self.get_executable(), "-e"]
        if technology_name:
            cmd.extend(["-n", technology_name])
        elif technology_file:
            cmd.extend(["-n", technology_file])
        if layer_props_file:
            cmd.extend(["-l", layer_props_file])
        if layout_file:
            cmd.append(layout_file)
        if extra_args:
            cmd.extend(extra_args)
        return cmd

    def launch_layout_editor(
        self,
        layout_file: str = "",
        technology_file: str = "",
        technology_name: str = "",
        layer_props_file: str = "",
        pdk_profile: Optional[KLayoutPDKProfile] = None,
        extra_args: Optional[list[str]] = None,
        env_overrides: Optional[dict[str, str]] = None,
    ) -> KLayoutProcessResult:
        """Launch KLayout GUI (non-blocking)."""
        command = self.build_open_layout_command(
            layout_file=layout_file,
            technology_file=technology_file,
            technology_name=technology_name,
            layer_props_file=layer_props_file,
            extra_args=extra_args,
        )
        result = KLayoutProcessResult(command=command)
        start = time.time()
        try:
            env = self.build_environment(pdk_profile)
            for key, value in (env_overrides or {}).items():
                env[str(key)] = str(value)
            proc = subprocess.Popen(
                command,
                cwd=self.workspace,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
            result.success = True
            result.returncode = 0
            result.pid = proc.pid or 0
        except OSError as exc:
            result.error = str(exc)
        result.elapsed_time = time.time() - start
        return result

    def build_batch_command(
        self,
        script_path: str,
        runtime_defines: Optional[dict[str, str]] = None,
        input_files: Optional[list[str]] = None,
        extra_args: Optional[list[str]] = None,
    ) -> list[str]:
        cmd = [self.get_executable(), "-b"]
        for key, value in (runtime_defines or {}).items():
            cmd.extend(["-rd", f"{key}={value}"])
        cmd.extend(["-r", script_path])
        for path in input_files or []:
            if path:
                cmd.append(path)
        if extra_args:
            cmd.extend(extra_args)
        return cmd

    def run_batch_script(
        self,
        script_path: str,
        runtime_defines: Optional[dict[str, str]] = None,
        input_files: Optional[list[str]] = None,
        timeout: int = 900,
        pdk_profile: Optional[KLayoutPDKProfile] = None,
        extra_args: Optional[list[str]] = None,
    ) -> KLayoutProcessResult:
        """Run KLayout in batch mode and wait for completion."""
        command = self.build_batch_command(
            script_path=script_path,
            runtime_defines=runtime_defines,
            input_files=input_files,
            extra_args=extra_args,
        )
        result = KLayoutProcessResult(command=command)
        start = time.time()
        try:
            proc = subprocess.run(
                command,
                cwd=self.workspace,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env=self.build_environment(pdk_profile),
            )
            result.returncode = proc.returncode
            result.stdout = proc.stdout or ""
            result.stderr = proc.stderr or ""
            result.success = proc.returncode == 0
            if not result.success and result.stderr:
                result.error = result.stderr.strip().splitlines()[-1]
        except subprocess.TimeoutExpired as exc:
            result.returncode = -1
            result.stdout = exc.stdout or ""
            result.stderr = exc.stderr or ""
            result.error = f"KLayout batch run timed out after {timeout}s"
        except OSError as exc:
            result.returncode = -1
            result.error = str(exc)
        result.elapsed_time = time.time() - start
        return result

    def build_python_script_command(self, script_path: str, args: Optional[list[str]] = None) -> list[str]:
        return [os.environ.get("PYTHON", sys.executable or "python"), script_path] + list(args or [])

    def run_python_script(
        self,
        script_path: str,
        args: Optional[list[str]] = None,
        timeout: int = 1800,
        pdk_profile: Optional[KLayoutPDKProfile] = None,
        cwd: str | Path | None = None,
    ) -> KLayoutProcessResult:
        """Run a PDK Python helper with the same KLayout/PDK environment."""
        command = self.build_python_script_command(script_path, args=args)
        result = KLayoutProcessResult(command=command)
        start = time.time()
        try:
            proc = subprocess.run(
                command,
                cwd=str(cwd or self.workspace),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env=self.build_environment(pdk_profile),
            )
            result.returncode = proc.returncode
            result.stdout = proc.stdout or ""
            result.stderr = proc.stderr or ""
            result.success = proc.returncode == 0
            if not result.success:
                text = result.stderr or result.stdout
                result.error = text.strip().splitlines()[-1] if text.strip() else "Python helper returned non-zero"
        except subprocess.TimeoutExpired as exc:
            result.returncode = -1
            result.stdout = exc.stdout or ""
            result.stderr = exc.stderr or ""
            result.error = f"Python helper timed out after {timeout}s"
        except OSError as exc:
            result.returncode = -1
            result.error = str(exc)
        result.elapsed_time = time.time() - start
        return result

    def _find_ihp_sg13g2_dir(self) -> Path | None:
        env_root = os.environ.get("PDK_ROOT", "").strip()
        candidates: list[Path] = []
        if env_root:
            candidates.append(Path(env_root) / os.environ.get("PDK", "ihp-sg13g2"))
            candidates.append(Path(env_root) / "ihp-sg13g2")
        repo_root = Path(__file__).resolve().parents[2]
        candidates.extend(
            [
                repo_root / "external" / "ihp_pdk" / "ihp-sg13g2",
                repo_root / "ihp_pdk" / "ihp-sg13g2",
                Path(r"C:\EDA\LumenCircuitStudio\external\ihp_pdk\ihp-sg13g2"),
                Path(r"C:\EDA\ihp_pdk\ihp-sg13g2"),
                Path.home() / "IHP-Open-PDK" / "ihp-sg13g2",
            ]
        )
        for candidate in candidates:
            if (candidate / "libs.tech" / "klayout" / "tech" / "sg13g2.lyt").exists():
                return candidate
        return None

    def _join_unique_paths(self, paths: list[str]) -> str:
        result: list[str] = []
        seen: set[str] = set()
        for raw in paths:
            for part in str(raw or "").split(os.pathsep):
                part = part.strip()
                if not part:
                    continue
                norm = os.path.normcase(os.path.abspath(part))
                if norm in seen:
                    continue
                seen.add(norm)
                result.append(part)
        return os.pathsep.join(result)

    def _prepend_path(self, current: str, new_entry: str) -> str:
        return self._join_unique_paths([new_entry, current])
