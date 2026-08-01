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


if __name__ == "__main__":
    unittest.main()
