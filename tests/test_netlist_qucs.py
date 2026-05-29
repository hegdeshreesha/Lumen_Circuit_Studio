import tempfile
import unittest
from pathlib import Path

from lumen.core.database import LibraryDatabase
from lumen.core.netlist import NetlistGenerator


class NetlistQucsSupportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = LibraryDatabase(self.tmp.name)
        self.db.create_library("work")
        self.db.create_cell("work", "top")

    def tearDown(self):
        self.tmp.cleanup()

    def _save_symbol(self, name: str, spice_model: str, pins: list[dict], parameters: list[dict]):
        if not self.db.cell_exists("work", name):
            self.db.create_cell("work", name)
        self.db.save_view("work", name, "symbol", {
            "type": "symbol",
            "name": name,
            "library": "work",
            "prefix": name[:1].upper() or "X",
            "spice_model": spice_model,
            "pins": pins,
            "shapes": [],
            "parameters": parameters,
            "label": {"text": "@name", "x": 0, "y": 0},
        })

    def _save_top(self, instances: list[dict], labels: list[dict] | None = None):
        self.db.save_view("work", "top", "schematic", {
            "type": "schematic",
            "name": "top",
            "library": "work",
            "instances": instances,
            "wires": [],
            "labels": labels or [],
            "pins": [],
        })

    def test_numeric_validation_blocks_bad_instance_params(self):
        self._save_symbol(
            "rv",
            "R",
            [{"name": "PLUS", "x": 0, "y": -10}, {"name": "MINUS", "x": 0, "y": 10}],
            [{"name": "R", "default": "1k", "type": "number"}],
        )
        self._save_top([{
            "name": "R0",
            "library": "work",
            "cell": "rv",
            "x": 0,
            "y": 0,
            "params": {"R": "abc"},
        }])
        gen = NetlistGenerator(self.db)
        netlist = gen.generate("work", "top")
        self.assertIn(".END", netlist)
        self.assertTrue(any("expects numeric value" in e for e in gen.get_errors()))

    def test_system_file_validation_reports_missing_file(self):
        self._save_symbol(
            "sparam_file",
            "SPFILE",
            [{"name": "P1", "x": -10, "y": 0}, {"name": "P2", "x": 10, "y": 0}],
            [{"name": "File", "default": "network.s2p"}],
        )
        self._save_top([{
            "name": "X1",
            "library": "work",
            "cell": "sparam_file",
            "x": 0,
            "y": 0,
            "params": {"File": "missing.s2p"},
        }])
        gen = NetlistGenerator(self.db)
        _ = gen.generate("work", "top")
        self.assertTrue(gen.get_errors())

    def test_digital_gate_emits_behavioral_source(self):
        self._save_symbol(
            "gate_and",
            "AND",
            [{"name": "A", "x": -10, "y": -10}, {"name": "B", "x": -10, "y": 10}, {"name": "Y", "x": 10, "y": 0}],
            [],
        )
        self._save_top([{
            "name": "U1",
            "library": "work",
            "cell": "gate_and",
            "x": 0,
            "y": 0,
            "params": {"VHI": "1.2", "TH": "0.6"},
        }])
        gen = NetlistGenerator(self.db)
        netlist = gen.generate("work", "top")
        self.assertIn("BU1", netlist)
        self.assertIn("V=(1.2)", netlist)

    def test_ac_power_source_emits_pac_norton_equivalent(self):
        self._save_symbol(
            "ac_power",
            "PAC",
            [{"name": "PLUS", "x": -10, "y": 0}, {"name": "MINUS", "x": 10, "y": 0}],
            [{"name": "P", "default": "0dBm"}, {"name": "Z", "default": "50"}],
        )
        self._save_top([{
            "name": "P1",
            "library": "work",
            "cell": "ac_power",
            "x": 0,
            "y": 0,
            "params": {"P": "10dBm", "Z": "50"},
        }])
        gen = NetlistGenerator(self.db)
        netlist = gen.generate("work", "top")
        self.assertIn("PAC Norton equivalent", netlist)
        self.assertIn("GP1_PAC", netlist)
        self.assertIn("IP1_PAC", netlist)
        self.assertFalse(any("expects numeric value" in e for e in gen.get_errors()))

    def test_spfile_emits_ngspice_wrapper(self):
        touchstone = Path(self.tmp.name) / "tiny.s2p"
        touchstone.write_text(
            "! tiny 2-port\n"
            "# Hz S RI R 50\n"
            "1.0e9 0 0 0.9 0 0.01 0 0 0\n",
            encoding="utf-8",
        )
        self._save_symbol(
            "sparam_file",
            "SPFILE",
            [{"name": "P1", "x": -10, "y": 0}, {"name": "P2", "x": 10, "y": 0}],
            [{"name": "File", "default": "tiny.s2p"}],
        )
        self._save_top([{
            "name": "XSP",
            "library": "work",
            "cell": "sparam_file",
            "x": 0,
            "y": 0,
            "params": {"File": "tiny.s2p"},
        }])
        gen = NetlistGenerator(self.db)
        gen.set_target_simulator("Ngspice")
        netlist = gen.generate("work", "top")
        self.assertIn(".SUBCKT LUMEN_S2P_GENERIC", netlist)
        self.assertIn("xfer file=touchstone span=9", netlist)
        self.assertIn("XXSP_SP", netlist)

    def test_malformed_pin_records_do_not_crash_netlisting(self):
        self._save_symbol(
            "badpins",
            "R",
            [{"name": "PLUS", "x": 0, "y": -10}, {"x": 0, "y": 10}, "MINUS"],
            [{"name": "R", "default": "1k"}],
        )
        self._save_top([{
            "name": "RBAD",
            "library": "work",
            "cell": "badpins",
            "x": 0,
            "y": 0,
            "params": {"R": "2k"},
        }])
        gen = NetlistGenerator(self.db)
        netlist = gen.generate("work", "top")
        self.assertIn(".END", netlist)
        self.assertIn("RBAD", netlist)


if __name__ == "__main__":
    unittest.main()
