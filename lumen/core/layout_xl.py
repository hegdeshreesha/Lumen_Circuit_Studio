"""
Layout integration service built around KLayout.

The service provides Layout-XL style entry points while keeping the runtime
upgradeable and externalized.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .database import LibraryDatabase
from .klayout_adapter import KLayoutCLIAdapter, KLayoutProcessResult
from .klayout_runtime import KLayoutInstallResult, KLayoutRuntimeManager


@dataclass
class LayoutActionResult:
    success: bool
    message: str
    payload: Optional[dict] = None


class LayoutXLService:
    """Facade for schematic-to-layout actions and KLayout orchestration."""

    def __init__(self, db: LibraryDatabase):
        self.db = db
        self.workspace = Path(db.workspace)
        self.runtime_manager = KLayoutRuntimeManager(self.workspace)
        self.adapter = KLayoutCLIAdapter(self.workspace, runtime_manager=self.runtime_manager)
        self.layout_root = self.workspace / "layout"
        self.layout_root.mkdir(parents=True, exist_ok=True)

    def runtime_summary(self) -> dict:
        return self.runtime_manager.runtime_summary()

    def set_runtime_executable(self, executable: str) -> bool:
        return self.runtime_manager.set_active_executable(executable)

    def ensure_runtime(self, auto_install: bool = False) -> tuple[bool, str]:
        return self.runtime_manager.ensure_runtime(auto_install=auto_install)

    def install_runtime_if_missing(self) -> KLayoutInstallResult:
        return self.runtime_manager.install_if_missing()

    def ensure_layout_view(self, library: str, cell: str) -> dict:
        """Ensure layout view metadata exists and return it."""
        view = self.db.load_view(library, cell, "layout")
        if not view:
            view = {
                "type": "layout",
                "name": cell,
                "library": library,
                "created_by": "LayoutXLService",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

        layout_file = view.get("layout_file", "")
        if not layout_file:
            default_file = self.layout_root / library / f"{cell}.gds"
            default_file.parent.mkdir(parents=True, exist_ok=True)
            view["layout_file"] = str(default_file)
            view["layout_format"] = "gds"
            view["managed_by"] = "klayout"

        self.db.save_view(library, cell, "layout", view)
        return view

    def open_layout_editor(self, library: str, cell: str) -> LayoutActionResult:
        """Open layout view in KLayout edit mode."""
        view = self.ensure_layout_view(library, cell)
        layout_file = str(view.get("layout_file", "")).strip()
        # Launch without file when the default file does not yet exist.
        launch_target = layout_file if layout_file and Path(layout_file).exists() else ""
        result = self.adapter.launch_layout_editor(layout_file=launch_target)
        if result.success:
            msg = f"KLayout launched for {library}/{cell}"
            if launch_target:
                msg += f" ({launch_target})"
            else:
                msg += " (new layout session)"
            return LayoutActionResult(True, msg, payload={"process": self._as_payload(result), "view": view})
        return LayoutActionResult(
            False,
            f"Failed to launch KLayout: {result.error or 'unknown launch error'}",
            payload={"process": self._as_payload(result), "view": view},
        )

    def update_layout_from_schematic(self, library: str, cell: str) -> LayoutActionResult:
        """Scaffold for Layout XL update-from-source flow."""
        view = self.ensure_layout_view(library, cell)
        view["last_update_from_schematic"] = datetime.now(timezone.utc).isoformat()
        view["update_status"] = (
            "Scaffold only: KLayout launch and runtime management are live. "
            "Auto-place/router and connectivity-driven updates are pending."
        )
        self.db.save_view(library, cell, "layout", view)
        return LayoutActionResult(
            True,
            f"Prepared layout metadata for {library}/{cell}; update pipeline scaffolded.",
            payload={"view": view},
        )

    def run_drc(self, library: str, cell: str, drc_script: str, report_path: str = "") -> LayoutActionResult:
        view = self.ensure_layout_view(library, cell)
        layout_file = str(view.get("layout_file", "")).strip()
        if not layout_file or not Path(layout_file).exists():
            return LayoutActionResult(False, "Layout file not found. Save/export a layout file first.")
        script_path = Path(drc_script)
        if not script_path.exists():
            return LayoutActionResult(False, f"DRC script not found: {drc_script}")

        report = report_path or str(self.layout_root / library / f"{cell}.drc.lyrdb")
        Path(report).parent.mkdir(parents=True, exist_ok=True)
        result = self.adapter.run_batch_script(
            script_path=str(script_path),
            runtime_defines={"input": layout_file, "report": report},
            input_files=[layout_file],
            timeout=1200,
        )
        if result.success:
            return LayoutActionResult(
                True,
                f"DRC completed: {report}",
                payload={"process": self._as_payload(result), "report": report},
            )
        return LayoutActionResult(
            False,
            f"DRC failed: {result.error or 'batch execution returned non-zero'}",
            payload={"process": self._as_payload(result), "report": report},
        )

    def run_lvs(
        self,
        library: str,
        cell: str,
        lvs_script: str,
        schematic_netlist: str = "",
        report_path: str = "",
    ) -> LayoutActionResult:
        view = self.ensure_layout_view(library, cell)
        layout_file = str(view.get("layout_file", "")).strip()
        if not layout_file or not Path(layout_file).exists():
            return LayoutActionResult(False, "Layout file not found. Save/export a layout file first.")
        script_path = Path(lvs_script)
        if not script_path.exists():
            return LayoutActionResult(False, f"LVS script not found: {lvs_script}")

        report = report_path or str(self.layout_root / library / f"{cell}.lvs.txt")
        Path(report).parent.mkdir(parents=True, exist_ok=True)
        defines = {"input": layout_file, "report": report}
        if schematic_netlist:
            defines["schematic"] = schematic_netlist
        result = self.adapter.run_batch_script(
            script_path=str(script_path),
            runtime_defines=defines,
            input_files=[layout_file],
            timeout=1800,
        )
        if result.success:
            return LayoutActionResult(
                True,
                f"LVS completed: {report}",
                payload={"process": self._as_payload(result), "report": report},
            )
        return LayoutActionResult(
            False,
            f"LVS failed: {result.error or 'batch execution returned non-zero'}",
            payload={"process": self._as_payload(result), "report": report},
        )

    def _as_payload(self, result: KLayoutProcessResult) -> dict:
        return {
            "success": result.success,
            "command": result.command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "elapsed_time": result.elapsed_time,
            "pid": result.pid,
            "error": result.error,
        }
