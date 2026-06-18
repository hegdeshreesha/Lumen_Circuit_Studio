import os
import tempfile
import unittest
from pathlib import Path

from lumen.core.simulator_runtime import SimulatorRuntimeManager


class SimulatorRuntimeManagerTest(unittest.TestCase):
    def test_set_active_and_apply_environment_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir(parents=True, exist_ok=True)
            fake_exe = workspace / "gspice.exe"
            fake_exe.write_text("", encoding="utf-8")

            manager = SimulatorRuntimeManager(str(workspace))
            self.assertTrue(manager.set_active_executable("GSPICE", str(fake_exe)))
            manager.apply_environment_overrides()
            self.assertEqual(
                os.environ.get("LUMEN_GSPICE_EXE", ""),
                str(fake_exe),
            )

    def test_runtime_summary_contains_gspice(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SimulatorRuntimeManager(tmp)
            summary = manager.runtime_summary()
            self.assertIn("simulators", summary)
            sims = summary["simulators"]
            self.assertIn("GSPICE", sims)


if __name__ == "__main__":
    unittest.main()
