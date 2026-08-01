import subprocess
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from lumen.core.database import LibraryDatabase
from lumen.core.klayout_adapter import KLayoutCLIAdapter, KLayoutProcessResult
from lumen.core.layout_xl import LayoutXLService


class _FakeRuntime:
    def get_active_executable(self) -> str:
        return "klayout"


class KLayoutAdapterTest(unittest.TestCase):
    def test_command_builders(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = KLayoutCLIAdapter(tmp, runtime_manager=_FakeRuntime())
            cmd = adapter.build_open_layout_command(layout_file="chip.gds", technology_name="sg13g2")
            self.assertEqual(cmd[:2], ["klayout", "-e"])
            self.assertIn("-n", cmd)
            self.assertIn("sg13g2", cmd)
            self.assertIn("chip.gds", cmd)

            batch = adapter.build_batch_command(
                script_path="rules.drc",
                runtime_defines={"input": "chip.gds", "report": "out.lyrdb"},
                input_files=["chip.gds"],
            )
            self.assertEqual(batch[:2], ["klayout", "-b"])
            self.assertIn("-rd", batch)
            self.assertIn("input=chip.gds", batch)
            self.assertIn("rules.drc", batch)

    def test_batch_runner_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = KLayoutCLIAdapter(tmp, runtime_manager=_FakeRuntime())
            with patch("lumen.core.klayout_adapter.subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(
                    args=["klayout"], returncode=0, stdout="ok", stderr=""
                )
                result = adapter.run_batch_script("rules.drc", runtime_defines={"input": "a.gds"})
                self.assertTrue(result.success)
                self.assertEqual(result.returncode, 0)

    def test_ihp_profile_and_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = KLayoutCLIAdapter(tmp, runtime_manager=_FakeRuntime())
            profile = adapter.resolve_ihp_sg13g2_profile()
            self.assertTrue(profile.available)
            self.assertEqual(profile.technology_name, "sg13g2")
            self.assertTrue(profile.technology_file.endswith("sg13g2.lyt"))
            self.assertTrue(profile.layer_properties_file.endswith("sg13g2.lyp"))
            self.assertTrue(profile.pcells_available)
            self.assertEqual(profile.pcell_library, "SG13_dev")
            self.assertGreaterEqual(profile.pcell_count, 20)
            self.assertTrue(profile.netlist_import_macro.endswith("ihp130_import_netlist.lym"))

            env = adapter.build_environment(profile)
            self.assertEqual(env["PDK"], "ihp-sg13g2")
            self.assertTrue(env["PDKPATH"].endswith("ihp-sg13g2"))
            self.assertEqual(env["STD_CELL_LIBRARY"], "sg13g2_stdcell")
            self.assertIn("libs.tech", env["KLAYOUT_PATH"])
            self.assertIn("klayout", env["KLAYOUT_PATH"].lower())
            self.assertIn(str(Path(tmp) / ".klayout"), env["KLAYOUT_PATH"])

    def test_ihp_profile_ignores_conflicting_global_environment(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as fake_pdk_root:
            fake_tech = Path(fake_pdk_root) / "ihp-sg13g2" / "libs.tech" / "klayout" / "tech"
            fake_tech.mkdir(parents=True)
            (fake_tech / "sg13g2.lyt").write_text("wrong", encoding="utf-8")

            with patch.dict(
                "lumen.core.klayout_adapter.os.environ",
                {
                    "PDK_ROOT": fake_pdk_root,
                    "KLAYOUT_PATH": str(fake_tech),
                    "PYTHONPATH": str(fake_tech),
                },
            ):
                adapter = KLayoutCLIAdapter(tmp, runtime_manager=_FakeRuntime())
                profile = adapter.resolve_ihp_sg13g2_profile()
                env = adapter.build_environment(profile)

            self.assertNotEqual(Path(profile.pdk_root), Path(fake_pdk_root))
            self.assertNotIn(str(fake_tech), env["KLAYOUT_PATH"])
            self.assertNotIn(str(fake_tech), env.get("PYTHONPATH", ""))

    def test_python_helper_uses_klayout_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = KLayoutCLIAdapter(tmp, runtime_manager=_FakeRuntime())
            profile = adapter.resolve_ihp_sg13g2_profile()
            with patch("lumen.core.klayout_adapter.subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(
                    args=["python"], returncode=0, stdout="ok", stderr=""
                )
                result = adapter.run_python_script(
                    profile.drc_script or "run_drc.py",
                    args=["--path=a.gds"],
                    pdk_profile=profile,
                    cwd=tmp,
                )
                self.assertTrue(result.success)
                kwargs = mock_run.call_args.kwargs
                self.assertIn("KLAYOUT_PATH", kwargs["env"])
                self.assertEqual(kwargs["env"]["PDK"], "ihp-sg13g2")

    def test_interactive_bridge_command_and_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = KLayoutCLIAdapter(tmp, runtime_manager=_FakeRuntime())
            script = adapter.bridge_script
            self.assertTrue(script.is_file())
            compile(script.read_text(encoding="utf-8"), str(script), "exec")

            with patch("lumen.core.klayout_adapter.subprocess.Popen") as mock_popen:
                mock_popen.return_value.pid = 42
                result = adapter.launch_layout_editor(
                    extra_args=["-rr", str(script)],
                    env_overrides={"LUMEN_PCELL_PLAN": "device-plan.json"},
                )
                self.assertTrue(result.success)
                self.assertIn("-rr", result.command)
                self.assertIn(str(script), result.command)
                env = mock_popen.call_args.kwargs["env"]
                self.assertEqual(env["LUMEN_PCELL_PLAN"], "device-plan.json")
                self.assertEqual(env["LUMEN_KLAYOUT_BRIDGE_FILE"], str(adapter.bridge_file))
                self.assertEqual(env["LUMEN_KLAYOUT_EVENT_FILE"], str(adapter.event_file))


class LayoutXLServiceTest(unittest.TestCase):
    def test_ensure_layout_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = LibraryDatabase(tmp)
            db.create_library("work")
            db.create_cell("work", "inv")
            db.save_view(
                "work",
                "inv",
                "schematic",
                {"type": "schematic", "name": "inv", "library": "work", "instances": [], "wires": [], "labels": [], "pins": []},
            )

            service = LayoutXLService(db)
            view = service.ensure_layout_view("work", "inv")
            self.assertEqual(view.get("type"), "layout")
            self.assertIn("layout_file", view)
            self.assertTrue(str(view["layout_file"]).endswith("inv.gds"))
            self.assertEqual(view.get("technology"), "sg13g2")
            self.assertGreater(view.get("layer_count", 0), 50)
            self.assertEqual(view.get("interoperability", {}).get("owner"), "external_klayout")
            self.assertEqual(
                view.get("interoperability", {}).get("view_mapping", {}).get("cadence_like_role"),
                "maskLayout",
            )

            saved = db.load_view("work", "inv", "layout")
            self.assertIsNotNone(saved)
            self.assertEqual(saved.get("managed_by"), "klayout")
            self.assertGreater(len(saved.get("layers", [])), 50)

    def test_import_and_export_layout_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = LibraryDatabase(tmp)
            db.create_library("work")
            db.create_cell("work", "inv")
            service = LayoutXLService(db)

            source = Path(tmp) / "source.gds"
            source.write_bytes(b"dummy-gds")

            result = service.import_layout_file("work", "inv", str(source))
            self.assertTrue(result.success)

            view = db.load_view("work", "inv", "layout")
            self.assertEqual(view.get("layout_format"), "GDS")
            self.assertEqual(view.get("managed_by"), "klayout")
            self.assertEqual(view.get("imported_from"), str(source.resolve()))
            self.assertGreater(view.get("layer_count", 0), 50)
            self.assertTrue(Path(view["layout_file"]).exists())

            target = Path(tmp) / "exported.gds"
            export_result = service.export_layout_file("work", "inv", str(target))
            self.assertTrue(export_result.success)
            self.assertEqual(target.read_bytes(), b"dummy-gds")

    def test_device_correspondence_and_pcell_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = LibraryDatabase(tmp)
            db.create_library("work")
            db.create_cell("work", "inv")
            db.save_view("work", "inv", "schematic", {
                "type": "schematic", "name": "inv", "library": "work",
                "instances": [{
                    "name": "M1", "library": "ihp_primitives", "cell": "sg13_lv_nmos",
                    "x": 0, "y": 0, "params": {"w": "2u", "l": "0.13u", "ng": 2, "m": 1},
                }],
                "wires": [], "labels": [], "pins": [],
            })
            service = LayoutXLService(db)

            resolved = service.resolve_layout_device("sg13_lv_rf_nmos", {"m": 3})
            self.assertTrue(resolved["supported"])
            self.assertEqual(resolved["pcell_name"], "rfnmos")
            self.assertEqual(resolved["multiplicity"], 3)

            result = service.update_layout_from_schematic("work", "inv")
            self.assertTrue(result.success, result.message)
            self.assertTrue(Path(result.payload["plan_path"]).exists())
            self.assertTrue(Path(result.payload["netlist"]).exists())
            self.assertEqual(result.payload["plan"]["placements"][0]["pcell_name"], "nmos")
            self.assertEqual(result.payload["plan"]["placements"][0]["instance"], "M1")
            self.assertEqual(result.payload["plan"]["placements"][0]["source"]["x"], 0)
            cdl = Path(result.payload["netlist"]).read_text(encoding="utf-8")
            self.assertIn("sg13_lv_nmos", cdl)
            self.assertIn("w=2u", cdl)
            self.assertIn("l=0.13u", cdl)
            self.assertIn("ng=2", cdl)

    def test_import_from_source_launches_bridge_and_highlight_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = LibraryDatabase(tmp)
            db.create_library("Dummy1")
            db.create_cell("Dummy1", "Dummy2")
            db.save_view("Dummy1", "Dummy2", "schematic", {
                "type": "schematic", "name": "Dummy2", "library": "Dummy1",
                "instances": [
                    {
                        "name": "X0", "library": "pdk:ihp_sg13g2", "cell": "sg13_lv_nmos",
                        "x": 140, "y": 50,
                        "params": {"w": "0.15u", "l": "0.13u", "ng": "1", "m": "1"},
                    },
                    {
                        "name": "X1", "library": "pdk:ihp_sg13g2", "cell": "sg13_lv_pmos",
                        "x": 140, "y": -50,
                        "params": {"w": "0.15u", "l": "0.13u", "ng": "1", "m": "1"},
                    },
                ],
                "wires": [], "labels": [], "pins": [],
            })
            service = LayoutXLService(db)
            with patch.object(service.adapter, "launch_layout_editor") as mock_launch:
                mock_launch.return_value = KLayoutProcessResult(
                    success=True, command=["klayout", "-e"], returncode=0, pid=77
                )
                result = service.import_from_source("Dummy1", "Dummy2")
                self.assertTrue(result.success, result.message)
                kwargs = mock_launch.call_args.kwargs
                self.assertEqual(kwargs["env_overrides"]["LUMEN_IMPORT_SOURCE"], "1")
                self.assertTrue(Path(kwargs["env_overrides"]["LUMEN_PCELL_PLAN"]).is_file())
                self.assertEqual(kwargs["extra_args"], ["-rr", str(service.adapter.bridge_script)])

            highlight = service.highlight_layout_device("Dummy1", "Dummy2", "X1")
            self.assertTrue(highlight.success, highlight.message)
            command = json.loads(service.adapter.bridge_file.read_text(encoding="utf-8"))
            self.assertEqual(command["command"], "highlight")
            self.assertEqual(command["instance"], "X1")

            unsupported = service.highlight_layout_device("Dummy1", "Dummy2", "V0")
            self.assertFalse(unsupported.success)

    def test_ihp_drc_invokes_pdk_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = LibraryDatabase(tmp)
            db.create_library("work")
            db.create_cell("work", "inv")
            service = LayoutXLService(db)
            view = service.ensure_layout_view("work", "inv")
            Path(view["layout_file"]).parent.mkdir(parents=True, exist_ok=True)
            Path(view["layout_file"]).write_text("dummy", encoding="utf-8")

            with patch.object(service.adapter, "run_python_script") as mock_run:
                mock_run.return_value.success = True
                mock_run.return_value.command = ["python", "run_drc.py"]
                mock_run.return_value.returncode = 0
                result = service.run_ihp_sg13g2_drc("work", "inv", topcell="inv")
                self.assertTrue(result.success)
                args = mock_run.call_args.args
                self.assertTrue(str(args[0]).endswith("run_drc.py"))
                kwargs = mock_run.call_args.kwargs
                self.assertIn("--topcell=inv", kwargs["args"])
                self.assertIn("--no_density", kwargs["args"])

    def test_ihp_lvs_invokes_pdk_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = LibraryDatabase(tmp)
            db.create_library("work")
            db.create_cell("work", "inv")
            service = LayoutXLService(db)
            view = service.ensure_layout_view("work", "inv")
            Path(view["layout_file"]).parent.mkdir(parents=True, exist_ok=True)
            Path(view["layout_file"]).write_text("dummy", encoding="utf-8")

            with patch.object(service.adapter, "run_python_script") as mock_run:
                mock_run.return_value.success = True
                mock_run.return_value.command = ["python", "run_lvs.py"]
                mock_run.return_value.returncode = 0
                result = service.run_ihp_sg13g2_lvs("work", "inv", schematic_netlist="inv.cdl")
                self.assertTrue(result.success)
                args = mock_run.call_args.args
                self.assertTrue(str(args[0]).endswith("run_lvs.py"))
                kwargs = mock_run.call_args.kwargs
                self.assertIn("--netlist=inv.cdl", kwargs["args"])
                self.assertNotIn("--net_only", kwargs["args"])


if __name__ == "__main__":
    unittest.main()
