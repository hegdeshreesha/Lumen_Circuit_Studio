import tempfile
import unittest
from pathlib import Path

from lumen.core.project_system import ProjectSystem


class ProjectSystemTest(unittest.TestCase):
    def test_create_and_open_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            root = Path(tmp) / "projects"
            mgr = ProjectSystem(str(state_path))
            info = mgr.create_project("alpha", str(root))
            self.assertEqual(info.name, "alpha")
            self.assertTrue((Path(info.path) / ".lumen_project.json").exists())
            self.assertTrue((Path(info.path) / "runs").exists())
            reopened = mgr.open_project(info.path)
            self.assertEqual(reopened.path, info.path)
            self.assertTrue(mgr.list_recent_projects())

    def test_autosave_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            root = Path(tmp) / "projects"
            mgr = ProjectSystem(str(state_path))
            info = mgr.create_project("beta", str(root))
            payload = {"dirty": True, "open_editors": [{"library": "mylib", "cell": "amp"}]}
            mgr.save_autosave(payload, info.path)
            loaded = mgr.load_autosave(info.path)
            self.assertIsNotNone(loaded)
            self.assertTrue(loaded.get("dirty"))
            self.assertEqual(loaded.get("open_editors", [])[0]["library"], "mylib")


if __name__ == "__main__":
    unittest.main()

