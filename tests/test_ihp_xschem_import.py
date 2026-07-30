import tempfile
import unittest
from pathlib import Path

from lumen.core.pdk_unified import PDKRegistry
from lumen.core.xschem_symbol_import import XschemSymbolParser


_IHP_XSCHEM_CANDIDATES = [
    Path(r"C:\EDA\LumenCircuitStudio\external\ihp_pdk\ihp-sg13g2\libs.tech\xschem"),
    Path(r"C:\EDA\LumenCircuitStudio\ihp_pdk\ihp-sg13g2\libs.tech\xschem"),
    Path(r"C:\EDA\ihp_pdk\ihp-sg13g2\libs.tech\xschem"),
]
IHP_XSCHEM_ROOT = next((p for p in _IHP_XSCHEM_CANDIDATES if p.exists()), _IHP_XSCHEM_CANDIDATES[0])


@unittest.skipUnless(IHP_XSCHEM_ROOT.exists(), "Local IHP Open PDK xschem library not installed")
class IHPXschemImportTest(unittest.TestCase):
    def test_parser_preserves_ihp_symbol_pins_and_parameters(self):
        parser = XschemSymbolParser()
        symbol = parser.parse_file(str(IHP_XSCHEM_ROOT / "sg13g2_pr" / "sg13_lv_nmos.sym"))
        data = symbol.to_lumen_json()

        self.assertEqual(data["prefix"], "X")
        self.assertEqual(data["spice_model"], "sg13_lv_nmos")
        self.assertEqual([pin["name"] for pin in data["pins"]], ["D", "G", "S", "B"])
        self.assertTrue(data["render_options"]["draw_pin_markers"])
        self.assertEqual(data["render_options"]["pin_marker_style"], "xschem_box")
        self.assertEqual(data["pins"][0]["bbox"], [17.5, -32.5, 22.5, -27.5])
        self.assertIn("polygon", {shape["type"] for shape in data["shapes"]})
        self.assertEqual([param["name"] for param in data["parameters"]], ["l", "w", "ng", "m"])

    def test_registry_exposes_every_local_ihp_xschem_symbol(self):
        with tempfile.TemporaryDirectory() as workspace:
            registry = PDKRegistry(workspace)
            pdk = registry.get_pdk("ihp_sg13g2")

        expected = {
            path.stem
            for group in ("sg13g2_pr", "sg13g2_stdcells")
            for path in (IHP_XSCHEM_ROOT / group).glob("*.sym")
        }
        actual = {device.name for device in pdk.devices}

        self.assertGreaterEqual(len(expected), 100)
        self.assertFalse(expected - actual)

        nmos = registry.find_device("sg13_lv_nmos", "ihp_sg13g2")
        self.assertIsNotNone(nmos)
        self.assertIsInstance(nmos.symbol_data, dict)
        self.assertEqual(nmos.term_order, ["D", "G", "S", "B"])

        inv = registry.find_device("sg13g2_inv_1", "ihp_sg13g2")
        self.assertIsNotNone(inv)
        self.assertEqual(inv.prefix, "X")
        self.assertEqual(inv.component_name, "sg13g2_inv_1")

    def test_registry_uses_ihp_klayout_layer_table(self):
        with tempfile.TemporaryDirectory() as workspace:
            registry = PDKRegistry(workspace)
            pdk = registry.get_pdk("ihp_sg13g2")

        self.assertGreater(len(pdk.layers), 50)
        metal1 = [
            layer for layer in pdk.layers
            if layer.get("name") == "Metal1" and layer.get("purpose") == "drawing"
        ]
        self.assertTrue(metal1)
        self.assertEqual(metal1[0]["gds_number"], 8)
        self.assertEqual(metal1[0]["gds_datatype"], 0)
        self.assertTrue(metal1[0]["color"].startswith("#"))


if __name__ == "__main__":
    unittest.main()
