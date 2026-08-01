import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
