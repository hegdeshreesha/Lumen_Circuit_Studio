"""
KLayout command adapter.

Encapsulates command construction and process execution so higher layers can
use layout actions without hard-coding command line details.
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

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
        layer_props_file: str = "",
        extra_args: Optional[list[str]] = None,
    ) -> list[str]:
        cmd = [self.get_executable(), "-e"]
        if technology_file:
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
        layer_props_file: str = "",
        extra_args: Optional[list[str]] = None,
    ) -> KLayoutProcessResult:
        """Launch KLayout GUI (non-blocking)."""
        command = self.build_open_layout_command(
            layout_file=layout_file,
            technology_file=technology_file,
            layer_props_file=layer_props_file,
            extra_args=extra_args,
        )
        result = KLayoutProcessResult(command=command)
        start = time.time()
        try:
            proc = subprocess.Popen(
                command,
                cwd=self.workspace,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
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
