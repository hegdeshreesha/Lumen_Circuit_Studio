import unittest
from lumen.core.gspice_diagnostics import GspiceDiagnosticParser
from lumen.core.connectivity import ConnectivityEngine, Junction, WireSegment


class TestGspiceDiagnostics(unittest.TestCase):
    def setUp(self):
        self.parser = GspiceDiagnosticParser()

    def test_singular_matrix_detection(self):
        log = "Error: Matrix is singular at node v_out.3\nSimulation aborted."
        report = self.parser.parse_log("GSPICE", log)
        self.assertFalse(report.success)
        self.assertEqual(len(report.issues), 1)
        self.assertEqual(report.issues[0].category, "SINGULAR_MATRIX")
        self.assertIn("v_out.3", report.issues[0].affected_nodes)

    def test_missing_model_detection(self):
        log = "Error: Model nmos_18v not found in PDK libraries."
        report = self.parser.parse_log("Ngspice", log)
        self.assertFalse(report.success)
        self.assertEqual(len(report.issues), 1)
        self.assertEqual(report.issues[0].category, "MISSING_MODEL")

    def test_clean_simulation_log(self):
        log = "Transient analysis completed successfully. 1000 points saved."
        report = self.parser.parse_log("GSPICE", log)
        self.assertTrue(report.success)
        self.assertTrue(report.is_clean())


class TestConnectivityCheckAndSave(unittest.TestCase):
    def test_check_and_save_pipeline(self):
        engine = ConnectivityEngine()
        # Add a pin with no wire (floating pin)
        engine.junctions["j1"] = Junction(id="j1", x=10.0, y=10.0, is_pin=True, pin_name="B", pin_instance="M1")
        report = engine.run_check_and_save()
        self.assertTrue(report["valid"])  # Warnings don't break valid netlisting
        self.assertEqual(len(report["floating_pins"]), 1)
        self.assertEqual(len(report["unconnected_bulks"]), 1)


if __name__ == "__main__":
    unittest.main()
