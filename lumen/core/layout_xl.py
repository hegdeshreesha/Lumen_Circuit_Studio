"""
Layout integration service built around KLayout.

The service provides Layout-XL style entry points while keeping the runtime
upgradeable and externalized.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import shutil
import time
from pathlib import Path
from typing import Optional

from .database import LibraryDatabase
from .ihp_klayout_devices import resolve_device
from .klayout_adapter import KLayoutCLIAdapter, KLayoutProcessResult
from .klayout_runtime import KLayoutInstallResult, KLayoutRuntimeManager
from .netlist import NetlistGenerator


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
        summary = self.runtime_manager.runtime_summary()
        summary["ihp_sg13g2"] = self.adapter.resolve_ihp_sg13g2_profile().as_dict()
        return summary

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
                "interop": {
                    "owner": "external_klayout",
                    "mode": "linked_stream",
                    "editable_in": ["KLayout"],
                    "stream_formats": ["gds", "oas"],
                    "layout_xl_status": "metadata_linked",
                },
            }

        profile = self.adapter.resolve_ihp_sg13g2_profile()
        layout_file = view.get("layout_file", "")
        if not layout_file:
            default_file = self.layout_root / library / f"{cell}.gds"
            default_file.parent.mkdir(parents=True, exist_ok=True)
            view["layout_file"] = str(default_file)
            view["layout_format"] = "GDS"
            view["managed_by"] = "klayout"
        if profile.available:
            view["pdk"] = profile.name
            view["technology"] = profile.technology_name
            view["technology_file"] = profile.technology_file
            view["layer_properties_file"] = profile.layer_properties_file
            view["layer_count"] = len(profile.layers)
            view["layers"] = profile.layers
            view["layer_source"] = profile.layer_properties_file
            view["interoperability"] = self._interop_metadata(profile)

        self.db.save_view(library, cell, "layout", view)
        return view

    def import_layout_file(
        self,
        library: str,
        cell: str,
        source_path: str,
        copy_into_workspace: bool = True,
    ) -> LayoutActionResult:
        """Attach or import an existing GDS/OAS layout into a Lumen layout view."""
        source = Path(source_path)
        if not source.exists():
            return LayoutActionResult(False, f"Layout file not found: {source_path}")
        suffix = source.suffix.lower().lstrip(".")
        if suffix not in {"gds", "oas", "oasis"}:
            return LayoutActionResult(False, "Layout import supports GDS/OAS files for now.")

        view = self.ensure_layout_view(library, cell)
        target = source
        if copy_into_workspace:
            target_suffix = ".oas" if suffix == "oasis" else source.suffix
            target = self.layout_root / library / f"{cell}{target_suffix}"
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.resolve() != target.resolve():
                shutil.copy2(source, target)

        profile = self.adapter.resolve_ihp_sg13g2_profile()
        view["layout_file"] = str(target)
        view["layout_format"] = "OAS" if suffix == "oasis" else suffix.upper()
        view["managed_by"] = "klayout"
        view["imported_from"] = str(source)
        view["imported_at"] = datetime.now(timezone.utc).isoformat()
        if profile.available:
            view["pdk"] = profile.name
            view["technology"] = profile.technology_name
            view["technology_file"] = profile.technology_file
            view["layer_properties_file"] = profile.layer_properties_file
            view["layer_count"] = len(profile.layers)
            view["layers"] = profile.layers
            view["layer_source"] = profile.layer_properties_file
            view["interoperability"] = self._interop_metadata(profile)
        self.db.save_view(library, cell, "layout", view)
        return LayoutActionResult(True, f"Imported layout into {library}/{cell}: {target}", payload={"view": view})

    def export_layout_file(self, library: str, cell: str, target_path: str) -> LayoutActionResult:
        """Export/copy the linked layout stream file to another location."""
        view = self.ensure_layout_view(library, cell)
        layout_file = Path(str(view.get("layout_file", "")).strip())
        if not layout_file.exists():
            return LayoutActionResult(False, "Layout file not found. Save/export a layout file first.")
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(layout_file, target)
        view["last_exported_to"] = str(target)
        view["last_exported_at"] = datetime.now(timezone.utc).isoformat()
        self.db.save_view(library, cell, "layout", view)
        return LayoutActionResult(True, f"Exported layout: {target}", payload={"source": str(layout_file), "target": str(target)})

    def layer_palette(self) -> list[dict]:
        """Return the active IHP layer palette as Lumen layer records."""
        profile = self.adapter.resolve_ihp_sg13g2_profile()
        return profile.layers if profile.available else []

    def device_correspondence(self) -> list[dict]:
        """Return the PDK-versioned schematic -> SG13_dev correspondence table."""
        profile = self.adapter.resolve_ihp_sg13g2_profile()
        return profile.device_correspondence if profile.pcells_available else []

    def resolve_layout_device(self, symbol_or_model: str, parameters: Optional[dict] = None) -> dict:
        """Resolve one schematic primitive into its exact IHP PCell variant."""
        profile = self.adapter.resolve_ihp_sg13g2_profile()
        if not profile.pcells_available or not profile.pcell_templates:
            return {
                "supported": False,
                "symbol": symbol_or_model,
                "message": profile.message,
            }
        return resolve_device(symbol_or_model, parameters, profile.pcell_templates).as_dict()

    def open_layout_editor(self, library: str, cell: str) -> LayoutActionResult:
        """Open layout view in KLayout edit mode."""
        view = self.ensure_layout_view(library, cell)
        layout_file = str(view.get("layout_file", "")).strip()
        profile = self.adapter.resolve_ihp_sg13g2_profile()
        if profile.available and not profile.pcells_available:
            return LayoutActionResult(
                False,
                profile.message,
                payload={"view": view, "pdk": profile.as_dict()},
            )
        # Launch without file when the default file does not yet exist.
        launch_target = layout_file if layout_file and Path(layout_file).exists() else ""
        plan_path = str(view.get("pcell_plan", "")).strip()
        env_overrides = {
            "LUMEN_LIBRARY": library,
            "LUMEN_CELL": cell,
        }
        if plan_path and Path(plan_path).is_file():
            env_overrides["LUMEN_PCELL_PLAN"] = plan_path
        result = self.adapter.launch_layout_editor(
            layout_file=launch_target,
            technology_name=profile.technology_name if profile.available else str(view.get("technology", "")),
            layer_props_file=profile.layer_properties_file if profile.available else str(view.get("layer_properties_file", "")),
            pdk_profile=profile if profile.available else None,
            extra_args=["-rr", str(self.adapter.bridge_script)],
            env_overrides=env_overrides,
        )
        if result.success:
            msg = f"KLayout launched for {library}/{cell}"
            if launch_target:
                msg += f" ({launch_target})"
            else:
                msg += " (new layout session)"
            return LayoutActionResult(True, msg, payload={"process": self._as_payload(result), "view": view, "pdk": profile.as_dict()})
        return LayoutActionResult(
            False,
            f"Failed to launch KLayout: {result.error or 'unknown launch error'}",
            payload={"process": self._as_payload(result), "view": view, "pdk": profile.as_dict()},
        )

    def update_layout_from_schematic(self, library: str, cell: str) -> LayoutActionResult:
        """Create an IHP PCell handoff plan and CDL netlist from the schematic."""
        view = self.ensure_layout_view(library, cell)
        profile = self.adapter.resolve_ihp_sg13g2_profile()
        if not profile.pcells_available or not profile.pcell_templates:
            return LayoutActionResult(False, profile.message, payload={"pdk": profile.as_dict()})

        schematic = self.db.load_view(library, cell, "schematic")
        if not schematic:
            return LayoutActionResult(False, f"Schematic view not found: {library}/{cell}")

        placements: list[dict] = []
        unsupported: list[dict] = []
        for instance in schematic.get("instances", []):
            symbol = str(instance.get("cell", ""))
            resolution = resolve_device(symbol, instance.get("params", {}), profile.pcell_templates)
            record = resolution.as_dict()
            record["instance"] = str(instance.get("name", ""))
            record["source"] = {
                "library": str(instance.get("library", "")),
                "cell": symbol,
                "x": instance.get("x", 0),
                "y": instance.get("y", 0),
                "rotation": instance.get("rotation", instance.get("rot", 0)),
            }
            if resolution.supported:
                placements.append(record)
            else:
                unsupported.append(record)

        if not placements:
            return LayoutActionResult(
                False,
                "No schematic instances have an IHP SG13G2 PCell correspondence.",
                payload={"unsupported": unsupported, "pdk": profile.as_dict()},
            )

        handoff_dir = self.layout_root / library
        handoff_dir.mkdir(parents=True, exist_ok=True)
        netlist_path = handoff_dir / f"{cell}.layout.cdl"
        netlist = self._build_ihp_layout_cdl(cell, schematic, placements)
        netlist_path.write_text(netlist, encoding="utf-8")

        plan_path = handoff_dir / f"{cell}.pcell-plan.json"
        plan = {
            "schema": "lumen.ihp-sg13g2-pcell-plan/v1",
            "library": library,
            "cell": cell,
            "technology": profile.technology_name,
            "pcell_library": profile.pcell_library,
            "netlist": str(netlist_path),
            "placements": placements,
            "unsupported": unsupported,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")

        view["last_update_from_schematic"] = datetime.now(timezone.utc).isoformat()
        view["update_status"] = "PCell correspondence and netlist handoff prepared"
        view["schematic_netlist"] = str(netlist_path)
        view["pcell_plan"] = str(plan_path)
        view["pcell_instance_count"] = sum(item["multiplicity"] for item in placements)
        view["unsupported_layout_instances"] = unsupported
        self.db.save_view(library, cell, "layout", view)
        message = (
            f"Prepared {len(placements)} IHP device correspondence(s) for {library}/{cell}: "
            f"{plan_path}"
        )
        if unsupported:
            message += f" ({len(unsupported)} non-layout instance(s) skipped)"
        return LayoutActionResult(
            True,
            message,
            payload={"view": view, "plan": plan, "plan_path": str(plan_path), "netlist": str(netlist_path)},
        )

    def import_from_source(self, library: str, cell: str) -> LayoutActionResult:
        """Prepare the schematic handoff and instantiate its PCells in KLayout."""
        prepared = self.update_layout_from_schematic(library, cell)
        if not prepared.success:
            return prepared

        payload = prepared.payload or {}
        view = payload.get("view") or self.ensure_layout_view(library, cell)
        profile = self.adapter.resolve_ihp_sg13g2_profile()
        layout_file = str(view.get("layout_file", "")).strip()
        launch_target = layout_file if layout_file and Path(layout_file).is_file() else ""
        plan_path = str(payload.get("plan_path", ""))
        result = self.adapter.launch_layout_editor(
            layout_file=launch_target,
            technology_name=profile.technology_name,
            layer_props_file=profile.layer_properties_file,
            pdk_profile=profile,
            extra_args=["-rr", str(self.adapter.bridge_script)],
            env_overrides={
                "LUMEN_LIBRARY": library,
                "LUMEN_CELL": cell,
                "LUMEN_PCELL_PLAN": plan_path,
                "LUMEN_IMPORT_SOURCE": "1",
                "LUMEN_LAYOUT_FILE": layout_file,
            },
        )
        combined = dict(payload)
        combined["process"] = self._as_payload(result)
        combined["pdk"] = profile.as_dict()
        if result.success:
            return LayoutActionResult(
                True,
                f"KLayout launched and is importing {len(payload.get('plan', {}).get('placements', []))} "
                f"source device(s) for {library}/{cell}.",
                payload=combined,
            )
        return LayoutActionResult(
            False,
            f"Source handoff was prepared, but KLayout could not be launched: "
            f"{result.error or 'unknown launch error'}",
            payload=combined,
        )

    def highlight_layout_device(self, library: str, cell: str, instance: str) -> LayoutActionResult:
        """Ask an open Lumen-managed KLayout session to select a source device."""
        instance = str(instance or "").strip()
        if not instance:
            return LayoutActionResult(False, "Select a schematic device first.")

        view = self.db.load_view(library, cell, "layout") or {}
        plan_path = Path(str(view.get("pcell_plan", "")))
        if not plan_path.is_file():
            return LayoutActionResult(
                False,
                "No source-import plan exists yet. Use Layout > Import From Source Into KLayout first.",
            )
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return LayoutActionResult(False, f"Cannot read the source-import plan: {exc}")
        known = {str(item.get("instance", "")) for item in plan.get("placements", [])}
        if instance not in known:
            return LayoutActionResult(
                False,
                f"{instance} has no IHP physical PCell correspondence in this source-import plan.",
            )

        command = {
            "schema": "lumen.klayout-bridge-command/v1",
            "sequence": time.time_ns(),
            "command": "highlight",
            "library": library,
            "cell": cell,
            "instance": instance,
            "plan": str(plan_path),
        }
        bridge_file = self.adapter.bridge_file
        temporary = bridge_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(command, indent=2), encoding="utf-8")
        temporary.replace(bridge_file)
        return LayoutActionResult(
            True,
            f"Sent layout highlight for {instance}. KLayout selects and zooms to its imported PCell.",
            payload={"command": command, "bridge_file": str(bridge_file)},
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

    def run_ihp_sg13g2_drc(
        self,
        library: str,
        cell: str,
        run_mode: str = "deep",
        topcell: str = "",
        no_density: bool = True,
        extra_args: Optional[list[str]] = None,
    ) -> LayoutActionResult:
        """Run the IHP SG13G2 DRC Python flow with Lumen's KLayout environment."""
        view = self.ensure_layout_view(library, cell)
        layout_file = str(view.get("layout_file", "")).strip()
        if not layout_file or not Path(layout_file).exists():
            return LayoutActionResult(False, "Layout file not found. Save/export a layout file first.")

        profile = self.adapter.resolve_ihp_sg13g2_profile()
        if not profile.available or not profile.drc_script:
            return LayoutActionResult(False, profile.message or "IHP SG13G2 DRC script is not available.")

        run_dir = self.layout_root / library / f"{cell}_drc"
        run_dir.mkdir(parents=True, exist_ok=True)
        args = [
            f"--path={layout_file}",
            f"--run_dir={run_dir}",
            f"--run_mode={run_mode}",
        ]
        if topcell:
            args.append(f"--topcell={topcell}")
        if no_density:
            args.append("--no_density")
        args.extend(extra_args or [])

        result = self.adapter.run_python_script(
            profile.drc_script,
            args=args,
            timeout=1800,
            pdk_profile=profile,
            cwd=Path(profile.drc_script).parent,
        )
        payload = {"process": self._as_payload(result), "run_dir": str(run_dir), "pdk": profile.as_dict()}
        if result.success:
            return LayoutActionResult(True, f"IHP SG13G2 DRC completed: {run_dir}", payload=payload)
        return LayoutActionResult(False, f"IHP SG13G2 DRC failed: {result.error or 'non-zero return'}", payload=payload)

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

    def run_ihp_sg13g2_lvs(
        self,
        library: str,
        cell: str,
        schematic_netlist: str = "",
        topcell: str = "",
        run_mode: str = "flat",
        extra_args: Optional[list[str]] = None,
    ) -> LayoutActionResult:
        """Run the IHP SG13G2 LVS Python flow with Lumen's KLayout environment."""
        view = self.ensure_layout_view(library, cell)
        layout_file = str(view.get("layout_file", "")).strip()
        if not layout_file or not Path(layout_file).exists():
            return LayoutActionResult(False, "Layout file not found. Save/export a layout file first.")

        profile = self.adapter.resolve_ihp_sg13g2_profile()
        if not profile.available or not profile.lvs_script:
            return LayoutActionResult(False, profile.message or "IHP SG13G2 LVS script is not available.")

        run_dir = self.layout_root / library / f"{cell}_lvs"
        run_dir.mkdir(parents=True, exist_ok=True)
        args = [
            f"--layout={layout_file}",
            f"--run_dir={run_dir}",
            f"--run_mode={run_mode}",
        ]
        if schematic_netlist:
            args.append(f"--netlist={schematic_netlist}")
        else:
            args.append("--net_only")
        if topcell:
            args.append(f"--topcell={topcell}")
        args.extend(extra_args or [])

        result = self.adapter.run_python_script(
            profile.lvs_script,
            args=args,
            timeout=2400,
            pdk_profile=profile,
            cwd=Path(profile.lvs_script).parent,
        )
        payload = {"process": self._as_payload(result), "run_dir": str(run_dir), "pdk": profile.as_dict()}
        if result.success:
            return LayoutActionResult(True, f"IHP SG13G2 LVS completed: {run_dir}", payload=payload)
        return LayoutActionResult(False, f"IHP SG13G2 LVS failed: {result.error or 'non-zero return'}", payload=payload)

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

    def _build_ihp_layout_cdl(self, cell: str, schematic: dict, placements: list[dict]) -> str:
        """Emit a PCell-import/LVS CDL using the same physical parameters as the plan."""
        generator = NetlistGenerator(self.db)
        try:
            net_map = generator._build_net_map_connectivity(schematic)
        except (KeyError, TypeError, ValueError):
            net_map = {}

        pins = [str(pin.get("name", "")).strip() for pin in schematic.get("pins", [])]
        pins = [pin for pin in pins if pin]
        lines = [
            "* Lumen IHP SG13G2 physical handoff netlist",
            f".SUBCKT {cell}" + (" " + " ".join(pins) if pins else ""),
        ]
        for item in placements:
            instance = str(item.get("instance", "X?"))
            spice_name = instance if instance.upper().startswith("X") else f"X{instance}"
            terminals = list(item.get("terminals") or [])
            nets = [
                net_map.get(f"{instance}.{terminal}", f"__UNCONNECTED_{instance}_{terminal}")
                for terminal in terminals
            ]
            params = dict(item.get("pcell_parameters") or {})
            params["m"] = item.get("multiplicity", 1)
            param_text = " ".join(f"{name}={value}" for name, value in params.items())
            fields = [spice_name] + nets + [str(item.get("model", "")), param_text]
            lines.append(" ".join(field for field in fields if field))
        lines.extend([f".ENDS {cell}", ""])
        return "\n".join(lines)

    def _interop_metadata(self, profile) -> dict:
        return {
            "owner": "external_klayout",
            "mode": "linked_stream",
            "technology": profile.technology_name,
            "technology_file": profile.technology_file,
            "layer_properties_file": profile.layer_properties_file,
            "drc_script": profile.drc_script,
            "lvs_script": profile.lvs_script,
            "pcell_library": profile.pcell_library,
            "pcell_bootstrap": profile.pcell_bootstrap,
            "pcell_templates": profile.pcell_templates,
            "netlist_import_macro": profile.netlist_import_macro,
            "pcells_available": profile.pcells_available,
            "device_correspondence_count": profile.pcell_count,
            "stream_formats": ["gds", "oas"],
            "view_mapping": {
                "lumen": "layout",
                "klayout": profile.technology_name,
                "cadence_like_role": "maskLayout",
            },
        }
