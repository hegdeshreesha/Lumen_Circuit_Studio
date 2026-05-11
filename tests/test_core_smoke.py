import tempfile
import unittest

from lumen.core.connectivity import ConnectivityEngine
from lumen.core.database import LibraryDatabase
from lumen.pdk.registry import DeviceCategory, PDKDevice, PDKParameter, PDKPin
from lumen.pdk.symbols import generate_device_symbol


class LibraryDatabaseSmokeTest(unittest.TestCase):
    def test_view_and_cell_existence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = LibraryDatabase(tmp)
            db.create_library("work")
            db.create_cell("work", "amp")

            self.assertTrue(db.cell_exists("work", "amp"))
            self.assertFalse(db.view_exists("work", "amp", "schematic"))

            db.save_view("work", "amp", "schematic", {"type": "schematic"})

            self.assertTrue(db.view_exists("work", "amp", "schematic"))


class SymbolGenerationSmokeTest(unittest.TestCase):
    def test_generate_resistor_symbol(self):
        device = PDKDevice(
            name="res_test",
            category=DeviceCategory.RESISTOR,
            prefix="R",
            model="res_test",
            pins=[PDKPin("PLUS"), PDKPin("MINUS")],
            parameters=[PDKParameter("R", "1k")],
        )

        symbol = generate_device_symbol(device, "test_pdk")

        self.assertEqual(symbol["type"], "symbol")
        self.assertEqual(symbol["prefix"], "R")
        self.assertEqual([pin["name"] for pin in symbol["pins"]], ["PLUS", "MINUS"])
        self.assertGreater(len(symbol["shapes"]), 0)


class ConnectivitySmokeTest(unittest.TestCase):
    def test_label_propagates_through_wire_to_pin(self):
        engine = ConnectivityEngine()
        engine.build_from_schematic({
            "wires": [{"x1": 0, "y1": 0, "x2": 20, "y2": 0}],
            "labels": [{"text": "VIN", "x": 0, "y": 0}],
            "instances": [],
        })
        engine.add_instance_pins(
            "R0", "primitives", "res", 20, -35,
            [{"name": "PLUS", "x": 0, "y": 35}],
        )

        self.assertEqual(engine.get_net_map(), {"VIN": ["R0.PLUS"]})


if __name__ == "__main__":
    unittest.main()
