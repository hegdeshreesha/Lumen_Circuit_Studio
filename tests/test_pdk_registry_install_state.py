import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from lumen.core.pdk_unified import PDKRegistry


class PDKRegistryInstallStateTest(unittest.TestCase):
    def test_builtin_pdks_are_not_active_until_installed(self):
        with tempfile.TemporaryDirectory() as workspace:
            registry = PDKRegistry(workspace)

            registry._pdks["sky130"].installed = False
            registry._pdks["gf180mcu"].installed = False
            registry._active_pdk = "sky130"

            self.assertIsNone(registry.get_active_pdk())
            self.assertEqual(registry.get_active_name(), "")
            self.assertFalse(registry.set_active_pdk("gf180mcu"))

    def test_ihp_install_uses_bundled_symbol_cache(self):
        with tempfile.TemporaryDirectory() as workspace:
            registry = PDKRegistry(workspace)
            pdk = registry.get_pdk("ihp_sg13g2")
            pdk.installed = False
            pdk.root_path = ""
            pdk.symbols_path = ""
            pdk.devices = []

            self.assertTrue(registry.install_pdk("ihp_sg13g2"))
            self.assertGreaterEqual(len(pdk.devices), 100)
            self.assertTrue(pdk.symbols_path.endswith("ihp_symbols"))
            self.assertIsNotNone(registry.find_device("sg13_lv_rf_nmos", "ihp_sg13g2"))
            self.assertFalse(registry.install_pdk("gf180mcu"))

    def test_register_local_pdk_writes_manifest_and_reloads(self):
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as pdk_root:
            model_dir = Path(pdk_root) / "libs.tech" / "ngspice" / "models"
            model_dir.mkdir(parents=True)
            (model_dir / "demo.lib").write_text(
                ".LIB tt\n.ENDL tt\n.LIB ff\n.ENDL ff\n",
                encoding="utf-8",
            )
            registry = PDKRegistry(workspace)

            pdk = registry.register_local_pdk(pdk_root, name="demo_pdk", display_name="Demo PDK")

            self.assertIsNotNone(pdk)
            self.assertTrue((Path(pdk_root) / "lumen_pdk.json").exists())
            self.assertEqual(registry.get_active_name(), "demo_pdk")
            self.assertEqual(len(pdk.model_files), 1)
            self.assertEqual([corner.name for corner in pdk.corners], ["ff", "tt"])

            reloaded = PDKRegistry(workspace)
            self.assertEqual(reloaded.get_active_name(), "demo_pdk")
            self.assertIsNotNone(reloaded.get_pdk("demo_pdk"))

    def test_register_local_pdk_uses_canonical_open_pdk_names(self):
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as parent:
            pdk_root = Path(parent) / "IHP-Open-PDK"
            model_dir = pdk_root / "models"
            model_dir.mkdir(parents=True)
            (model_dir / "demo.lib").write_text(".LIB tt\n.ENDL tt\n", encoding="utf-8")
            registry = PDKRegistry(workspace)

            pdk = registry.register_local_pdk(str(pdk_root))

            self.assertIsNotNone(pdk)
            self.assertEqual(pdk.name, "ihp_sg13g2")
            self.assertEqual(registry.get_active_name(), "ihp_sg13g2")

    def test_install_open_pdk_clones_then_registers(self):
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as installs:
            registry = PDKRegistry(workspace)

            def fake_run(cmd, **_kwargs):
                target = Path(cmd[-1])
                target.mkdir(parents=True)
                (target / "models").mkdir()
                (target / "models" / "demo.lib").write_text(".LIB tt\n.ENDL tt\n", encoding="utf-8")
                return SimpleNamespace(returncode=0, stderr="")

            with patch("lumen.core.pdk_unified.subprocess.run", side_effect=fake_run) as run:
                pdk = registry.install_open_pdk("sky130", installs)

            self.assertIsNotNone(pdk)
            self.assertEqual(pdk.name, "sky130")
            self.assertEqual(registry.get_active_name(), "sky130")
            self.assertTrue((Path(installs) / "sky130" / "lumen_pdk.json").exists())
            run.assert_called_once()

    def test_refresh_pdk_installation_updates_health(self):
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as pdk_root:
            root = Path(pdk_root)
            (root / "models").mkdir()
            registry = PDKRegistry(workspace)
            pdk = registry.register_local_pdk(pdk_root, name="demo_pdk", display_name="Demo PDK")

            before = registry.get_pdk_health_report("demo_pdk")
            self.assertIn("No model files discovered", before["issues"])

            (root / "models" / "corners.lib").write_text(
                ".LIB tt\n.ENDL tt\n.LIB ss\n.ENDL ss\n",
                encoding="utf-8",
            )
            refreshed = registry.refresh_pdk_installation("demo_pdk")
            after = registry.get_pdk_health_report("demo_pdk")

            self.assertIsNotNone(pdk)
            self.assertIsNotNone(refreshed)
            self.assertEqual(after["model_files_count"], 1)
            self.assertEqual(after["model_sections_count"], 2)
            self.assertNotIn("No model files discovered", after["issues"])

    def test_choose_models_folder_repairs_model_discovery(self):
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as pdk_root:
            root = Path(pdk_root)
            (root / "empty").mkdir()
            model_dir = root / "vendor" / "models"
            model_dir.mkdir(parents=True)
            (model_dir / "corners.lib").write_text(".LIB tt\n.ENDL tt\n", encoding="utf-8")
            registry = PDKRegistry(workspace)
            pdk = registry.register_local_pdk(str(root), name="demo_pdk", display_name="Demo PDK")
            pdk.model_files = []

            repaired = registry.set_pdk_models_path("demo_pdk", str(model_dir))

            self.assertIsNotNone(repaired)
            self.assertEqual(len(repaired.model_files), 1)
            self.assertEqual([corner.name for corner in repaired.corners], ["tt"])
            self.assertTrue((root / "lumen_pdk.json").exists())

    def test_create_lock_for_selected_pdk(self):
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as pdk_root:
            model_dir = Path(pdk_root) / "models"
            model_dir.mkdir()
            (model_dir / "demo.lib").write_text(".LIB tt\n.ENDL tt\n", encoding="utf-8")
            registry = PDKRegistry(workspace)
            registry.register_local_pdk(pdk_root, name="demo_pdk", display_name="Demo PDK")

            lock = registry.create_lock("demo_pdk", used_devices=["m1"], used_corners=["tt"])

            self.assertIsNotNone(lock)
            self.assertEqual(lock.pdk_name, "demo_pdk")
            self.assertEqual(lock.used_devices, ["m1"])
            self.assertEqual(lock.used_corners, ["tt"])


if __name__ == "__main__":
    unittest.main()
