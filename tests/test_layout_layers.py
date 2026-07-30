import unittest
from pathlib import Path

from lumen.core.layout_layers import parse_klayout_layer_properties


class LayoutLayerRegistryTest(unittest.TestCase):
    def test_parse_ihp_klayout_layer_properties(self):
        lyp = (
            Path(__file__).resolve().parents[1]
            / "external"
            / "ihp_pdk"
            / "ihp-sg13g2"
            / "libs.tech"
            / "klayout"
            / "tech"
            / "sg13g2.lyp"
        )
        self.assertTrue(lyp.exists())
        layers = parse_klayout_layer_properties(lyp)
        self.assertGreater(len(layers), 50)

        metal1 = [
            layer for layer in layers
            if layer.name == "Metal1" and layer.purpose == "drawing"
        ]
        self.assertTrue(metal1)
        self.assertEqual(metal1[0].gds_layer, 8)
        self.assertEqual(metal1[0].gds_datatype, 0)
        self.assertTrue(metal1[0].color.startswith("#"))


if __name__ == "__main__":
    unittest.main()
