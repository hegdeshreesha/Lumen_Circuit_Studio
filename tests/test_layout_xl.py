import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lumen.core.database import LibraryDatabase
from lumen.core.klayout_adapter import KLayoutCLIAdapter
from lumen.core.layout_xl import LayoutXLService


class _FakeRuntime:
    def get_active_executable(self) -> str:
        return "klayout"


class KLayoutAdapterTest(unittest.TestCase):
    def test_command_builders(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = KLayoutCLIAdapter(tmp, runtime_manager=_FakeRuntime())
            cmd = adapter.build_open_layout_command(layout_file="chip.gds")
            self.assertEqual(cmd[:2], ["klayout", "-e"])
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

            saved = db.load_view("work", "inv", "layout")
            self.assertIsNotNone(saved)
            self.assertEqual(saved.get("managed_by"), "klayout")


if __name__ == "__main__":
    unittest.main()
