import unittest
from pathlib import Path

from lumen.core.ihp_klayout_devices import build_device_catalog, resolve_device
from lumen.core.ihp_symbols import generate_all_ihp_primitives


TEMPLATES = (
    Path(__file__).resolve().parents[1]
    / "external"
    / "ihp_pdk"
    / "ihp-sg13g2"
    / "libs.tech"
    / "klayout"
    / "python"
    / "import_netlist"
    / "ihp130_pcell_templates.py"
)


class IHPKLayoutDeviceTest(unittest.TestCase):
    def test_catalog_is_derived_from_pdk_templates(self):
        catalog = build_device_catalog(TEMPLATES)
        by_symbol = {item.symbol: item for item in catalog}
        self.assertGreaterEqual(len(catalog), 20)
        self.assertEqual(by_symbol["sg13_lv_nmos"].pcell_name, "nmos")
        self.assertEqual(by_symbol["cap_cmim"].default_parameters["w"], "7.0e-6")
        self.assertEqual(by_symbol["npn13G2l"].pcell_name, "npn13G2L")

    def test_rf_mos_uses_base_model_and_rf_pcell(self):
        result = resolve_device(
            "sg13_lv_rf_nmos",
            {"w": "2u", "l": "0.72u", "ng": 4, "m": 2},
            TEMPLATES,
        )
        self.assertTrue(result.supported)
        self.assertEqual(result.model, "sg13_lv_nmos")
        self.assertEqual(result.pcell_name, "rfnmos")
        self.assertEqual(result.pcell_parameters["rfmode"], 1)
        self.assertEqual(result.pcell_parameters["ng"], 4)
        self.assertEqual(result.multiplicity, 2)

    def test_case_insensitive_parameter_mapping(self):
        result = resolve_device("rppd", {"W": "1u", "L": "10u", "B": 2}, TEMPLATES)
        self.assertTrue(result.supported)
        self.assertEqual(result.pcell_parameters["w"], "1u")
        self.assertEqual(result.pcell_parameters["l"], "10u")
        self.assertEqual(result.pcell_parameters["b"], 2)

    def test_builtin_symbols_match_physical_topology(self):
        symbols = generate_all_ihp_primitives()
        rf_mos = symbols["sg13_lv_rf_nmos"]
        self.assertEqual(rf_mos["spice_model"], "sg13_lv_nmos")
        self.assertEqual(rf_mos["layout"]["pcell"], "rfnmos")
        self.assertIn("rfmode", {item["name"] for item in rf_mos["parameters"]})

        self.assertEqual(
            [pin["name"] for pin in symbols["cap_rfcmim"]["pins"]],
            ["c0", "c1", "bn"],
        )
        self.assertEqual(
            [pin["name"] for pin in symbols["npn13G2"]["pins"]],
            ["C", "B", "E", "S"],
        )


if __name__ == "__main__":
    unittest.main()
