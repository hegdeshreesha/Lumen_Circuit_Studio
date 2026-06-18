import tempfile
import unittest

from lumen.core.database import LibraryDatabase
from lumen.core.netlist import NetlistGenerator
from lumen.core.simulator import SimulatorBridge, ensure_direct_run_analysis


class NetNamingSigViewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = LibraryDatabase(self.tmp.name)
        self.db.create_library("work")
        self.db.create_cell("work", "top")

    def tearDown(self):
        self.tmp.cleanup()

    def _save_symbol(self, name: str, spice_model: str, pins: list[dict], params: dict | None = None):
        if not self.db.cell_exists("work", name):
            self.db.create_cell("work", name)
        self.db.save_view("work", name, "symbol", {
            "type": "symbol",
            "name": name,
            "library": "work",
            "prefix": name[:1].upper(),
            "spice_model": spice_model,
            "pins": pins,
            "shapes": [],
            "parameters": [],
            "label": {"text": "@name", "x": 0, "y": 0},
        })

    def test_mid_wire_label_names_entire_connected_net(self):
        self._save_symbol("res", "R", [
            {"name": "PLUS", "x": -10, "y": 0},
            {"name": "MINUS", "x": 10, "y": 0},
        ])
        self.db.save_view("work", "top", "schematic", {
            "type": "schematic",
            "name": "top",
            "library": "work",
            "instances": [{
                "name": "R1",
                "library": "work",
                "cell": "res",
                "x": 10,
                "y": 0,
                "params": {"R": "1k"},
            }],
            "wires": [{"x1": 0, "y1": 0, "x2": 20, "y2": 0}],
            "labels": [{"text": "OUT", "x": 10, "y": 0}],
            "pins": [],
        })

        gen = NetlistGenerator(self.db)
        net_map = gen._build_net_map_connectivity(self.db.load_view("work", "top", "schematic"))

        self.assertEqual(net_map["R1.PLUS"], "OUT")
        self.assertEqual(net_map["R1.MINUS"], "OUT")

    def test_unlabeled_wire_uses_one_canonical_net_for_all_connected_pins(self):
        self._save_symbol("res", "R", [
            {"name": "PLUS", "x": -10, "y": 0},
            {"name": "MINUS", "x": 10, "y": 0},
        ])
        self.db.save_view("work", "top", "schematic", {
            "type": "schematic",
            "name": "top",
            "library": "work",
            "instances": [{
                "name": "R1",
                "library": "work",
                "cell": "res",
                "x": 10,
                "y": 0,
                "params": {"R": "1k"},
            }],
            "wires": [{"x1": 0, "y1": 0, "x2": 20, "y2": 0}],
            "labels": [],
            "pins": [],
        })

        gen = NetlistGenerator(self.db)
        net_map = gen._build_net_map_connectivity(self.db.load_view("work", "top", "schematic"))

        self.assertEqual(net_map["R1.PLUS"], net_map["R1.MINUS"])
        self.assertRegex(net_map["R1.PLUS"], r"^net\d+$")

    def test_wire_net_property_seeds_connected_component_name(self):
        self._save_symbol("res", "R", [
            {"name": "PLUS", "x": -10, "y": 0},
            {"name": "MINUS", "x": 10, "y": 0},
        ])
        self.db.save_view("work", "top", "schematic", {
            "type": "schematic",
            "name": "top",
            "library": "work",
            "instances": [{
                "name": "R1",
                "library": "work",
                "cell": "res",
                "x": 10,
                "y": 0,
                "params": {"R": "1k"},
            }],
            "wires": [{"x1": 0, "y1": 0, "x2": 20, "y2": 0, "net": "WIRE_NET"}],
            "labels": [],
            "pins": [],
        })

        gen = NetlistGenerator(self.db)
        net_map = gen._build_net_map_connectivity(self.db.load_view("work", "top", "schematic"))

        self.assertEqual(net_map["R1.PLUS"], "WIRE_NET")
        self.assertEqual(net_map["R1.MINUS"], "WIRE_NET")

    def test_gspice_stdout_nodes_are_renamed_to_voltage_trace_names(self):
        bridge = SimulatorBridge("GSPICE")
        netlist = "\n".join([
            "V1 IN 0 1",
            "R1 IN OUT 1k",
            "C1 OUT 0 1p",
            ".TRAN 1n 2n",
            ".END",
        ])
        aliases = bridge._extract_gspice_node_aliases(netlist)
        waveforms = bridge._parse_gspice_stdout(
            "0.000000 | 1.0 0.0\n0.000001 | 1.0 0.5\n",
            aliases,
        )

        self.assertIn("time", waveforms)
        self.assertEqual(waveforms["V(IN)"], [1.0, 1.0])
        self.assertEqual(waveforms["V(OUT)"], [0.0, 0.5])

    def test_direct_run_adds_transient_for_dynamic_source(self):
        netlist = "\n".join([
            "* no explicit analysis",
            "V1 IN 0 DC 0 PULSE(0 1 0 1n 1n 5u 10u)",
            "R1 IN 0 1k",
            ".END",
        ])

        rewritten, note = ensure_direct_run_analysis(netlist)

        self.assertIn(".TRAN 1n 10u", rewritten)
        self.assertIn("quick-run", note)
        self.assertTrue(rewritten.rstrip().endswith(".END"))

    def test_direct_run_adds_op_without_dynamic_source(self):
        netlist = "\n".join([
            "* no explicit analysis",
            "V1 IN 0 1",
            "R1 IN 0 1k",
            ".END",
        ])

        rewritten, _note = ensure_direct_run_analysis(netlist)

        self.assertIn(".OP", rewritten)
        self.assertNotIn(".TRAN", rewritten)


if __name__ == "__main__":
    unittest.main()
