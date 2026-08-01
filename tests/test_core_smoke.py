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

    def test_multiple_pins_on_same_rail_junction_are_all_stamped(self):
        engine = ConnectivityEngine()
        engine.build_from_schematic({
            "wires": [{"x1": 0, "y1": 0, "x2": 100, "y2": 0}],
            "labels": [{"text": "VDD", "x": 0, "y": 0}],
            "pins": [],
            "instances": [],
        })
        engine.add_instance_pins(
            "X0", "pdk:ihp_sg13g2", "sg13_lv_pmos", 40, 0,
            [{"name": "S", "x": 0, "y": 0}, {"name": "B", "x": 0, "y": 0}],
        )

        self.assertEqual(engine.get_net_map(), {"VDD": ["X0.S", "X0.B"]})

    def test_pin_near_wire_stamps_to_visible_rail(self):
        engine = ConnectivityEngine()
        engine.build_from_schematic({
            "wires": [{"x1": 0, "y1": 0, "x2": 100, "y2": 0}],
            "labels": [{"text": "VDD", "x": 0, "y": 0}],
            "pins": [],
            "instances": [],
        })
        engine.add_instance_pins(
            "X1", "pdk:ihp_sg13g2", "sg13_lv_pmos", 40, 2,
            [{"name": "S", "x": 0, "y": 0}],
        )

        self.assertEqual(engine.get_net_map(), {"VDD": ["X1.S"]})

    def test_top_level_pin_names_net(self):
        engine = ConnectivityEngine()
        engine.build_from_schematic({
            "wires": [{"x1": 0, "y1": 0, "x2": 20, "y2": 0}],
            "labels": [],
            "pins": [{"name": "OUT", "x": 0, "y": 0, "direction": "output"}],
            "instances": [],
        })
        engine.add_instance_pins(
            "R0", "primitives", "res", 20, -35,
            [{"name": "PLUS", "x": 0, "y": 35}],
        )

        self.assertEqual(engine.get_net_map(), {"OUT": ["__top__.OUT", "R0.PLUS"]})

    def test_rotated_pin_coordinates_match_drawn_orientation(self):
        engine = ConnectivityEngine()
        engine.build_from_schematic({
            "wires": [{"x1": 0, "y1": 10, "x2": 10, "y2": 10}],
            "labels": [{"text": "VIN", "x": 0, "y": 10}],
            "pins": [],
            "instances": [],
        })
        engine.add_instance_pins(
            "R0", "primitives", "res", 10, 0,
            [{"name": "PLUS", "x": 10, "y": 0}],
            rotation=90,
        )

        self.assertEqual(engine.get_net_map(), {"VIN": ["R0.PLUS"]})

    def test_crossing_wires_do_not_connect_unless_wire_ends_there(self):
        engine = ConnectivityEngine()
        engine.build_from_schematic({
            "wires": [
                {"x1": 0, "y1": 0, "x2": 20, "y2": 0},
                {"x1": 10, "y1": -10, "x2": 10, "y2": 10},
            ],
            "labels": [
                {"text": "H", "x": 0, "y": 0},
                {"text": "V", "x": 10, "y": -10},
            ],
            "pins": [],
            "instances": [],
        })
        engine.normalize_wires()
        engine.add_instance_pins("RH", "primitives", "res", 20, 0, [{"name": "PLUS", "x": 0, "y": 0}])
        engine.add_instance_pins("RV", "primitives", "res", 10, 10, [{"name": "PLUS", "x": 0, "y": 0}])

        net_map = engine.get_net_map()
        self.assertEqual(net_map["H"], ["RH.PLUS"])
        self.assertEqual(net_map["V"], ["RV.PLUS"])


if __name__ == "__main__":
    unittest.main()
