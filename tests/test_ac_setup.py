import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lumen.qt.QtWidgets import QApplication

from lumen.core.ade_engine import AnalysisSetup, AnalysisType
from lumen.core.database import LibraryDatabase
from lumen.core.simulator import SimulationResult, SimulatorBridge
from lumen.gui.ade_window import ADEWindow, AnalysisSetupWidget, ConvergenceHelpersWidget, StimulusEditorWidget


class _AcHarness:
    _current_simulator = "GSPICE"
    _sim_accuracy = "High"
    _sim_tolerance_override = ""
    _sim_method = "Auto"
    _sim_save_mode = "all"
    _sim_adaptive_maxstep = True
    _accuracy_transient_defaults = ADEWindow._accuracy_transient_defaults
    _accuracy_presets = ADEWindow._accuracy_presets
    _accuracy_options_line = ADEWindow._accuracy_options_line
    _sim_method_token = ADEWindow._sim_method_token
    _sim_save_mode_token = ADEWindow._sim_save_mode_token
    _has_transient_initial_conditions = ADEWindow._has_transient_initial_conditions


class _TransientIcHarness(_AcHarness):
    class _ConvergenceWidget:
        @staticmethod
        def get_ic_lines():
            return [".IC STG3=0"]

    convergence_widget = _ConvergenceWidget()


class AcSetupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_gui_ac_analysis_runs_from_op_by_default(self):
        widget = AnalysisSetupWidget("AC Small-Signal")
        line = ADEWindow._analysis_spice_line(_AcHarness(), "AC Small-Signal", widget)
        self.assertEqual(
            line,
            "* AC bias point\n.OP\n.AC DEC 100 1 10G",
        )

    def test_gui_ac_bias_op_can_be_disabled(self):
        widget = AnalysisSetupWidget("AC Small-Signal")
        widget.set_values({"BiasOP": False, "Sweep": "LIN", "Points": "11", "Fstart": "1k", "Fstop": "1M"})
        line = ADEWindow._analysis_spice_line(_AcHarness(), "AC Small-Signal", widget)
        self.assertEqual(line, ".AC LIN 11 1k 1M")

    def test_transient_ic_rows_emit_uic_even_when_checkbox_is_off(self):
        widget = AnalysisSetupWidget("Transient")
        widget.set_values({"Step": "2e-10", "Stop": "10u", "MaxStep": "", "UIC": False})
        line = ADEWindow._analysis_spice_line(_TransientIcHarness(), "Transient", widget)
        self.assertEqual(line, ".TRAN 2e-10 10u UIC")

    def test_ade_engine_ac_analysis_emits_op_anchor(self):
        setup = AnalysisSetup(
            AnalysisType.AC,
            params={"sweep": "DEC", "points": "20", "fstart": "10", "fstop": "1G"},
        )
        self.assertEqual(setup.to_spice(), ".OP\n.AC DEC 20 10 1G")

    def test_stimulus_editor_emits_ac_source(self):
        widget = StimulusEditorWidget()
        widget._add_row()
        type_widget = widget.table.cellWidget(0, 3)
        type_widget.setCurrentText("AC")
        widget.table.item(0, 4).setText("0 1 45")
        self.assertIn("V1 net1 0 DC 0 AC 1 45", widget.get_stimulus_lines())

    def test_convergence_helper_placeholder_rows_are_ignored(self):
        widget = ConvergenceHelpersWidget()
        widget._add_row(widget.nodeset_table, "node", "0")
        widget._add_row(widget.ic_table, "node", "0")
        self.assertEqual(widget.get_nodeset_lines(), [])
        self.assertEqual(widget.get_ic_lines(), [])

        widget.nodeset_table.item(0, 0).setText("STG3")
        widget.ic_table.item(0, 0).setText("STG1")
        self.assertEqual(widget.get_nodeset_lines(), [".NODESET STG3=0"])
        self.assertEqual(widget.get_ic_lines(), [".IC STG1=0"])

    def test_gspice_bridge_inserts_op_before_direct_ac_deck(self):
        bridge = SimulatorBridge("GSPICE")
        deck = "V1 in 0 DC 0 AC 1\nR1 in 0 1k\n.AC DEC 10 1 1k\n.END\n"
        prepared, notes = bridge._prepare_netlist_for_simulator(deck)
        self.assertIn(".OP\n.AC DEC 10 1 1k", prepared)
        self.assertTrue(any("Added .OP before .AC" in note for note in notes))

    def test_results_matrix_handles_dc_op_scalar_waveforms(self):
        with tempfile.TemporaryDirectory() as tmp:
            win = ADEWindow(LibraryDatabase(tmp), "test_lib", "op_cell")
            win._add_analysis("DC Operating Point")
            result = SimulationResult(
                success=True,
                simulator="GSPICE",
                waveforms={
                    "V(out)": [1.234],
                    "I(VDD)": -2.5e-6,
                },
                netlist_path=os.path.join(tmp, "input.sp"),
                output_path=os.path.join(tmp, "waveforms.raw"),
            )
            win._handle_simulation_result(result, "single", result.waveforms)
            self.assertEqual(win.results_table.rowCount(), 1)
            summary = win.results_table.item(0, 5).text()
            self.assertIn("V(out)", summary)
            self.assertIn("I(VDD)", summary)
            win.close()


if __name__ == "__main__":
    unittest.main()
