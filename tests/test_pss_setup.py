import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lumen.qt.QtWidgets import QApplication

from lumen.core.ade_engine import AnalysisSetup, AnalysisType
from lumen.core.pss import (
    PSS_MODE_DRIVEN,
    PSS_MODE_OSCILLATOR,
    build_pss_statement,
    pss_validation_errors,
)
from lumen.gui.ade_window import AnalysisSetupWidget


class PssSetupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_driven_statement_uses_explicit_mode_and_tstab(self):
        line = build_pss_statement(
            {
                "Mode": PSS_MODE_DRIVEN,
                "Fund": "2.4G",
                "Harmonics": "9",
                "Tstab": "10n",
            }
        )
        self.assertEqual(line, ".PSS 2.4G 9 DRIVEN TSTAB=10n")

    def test_oscillator_statement_uses_autonomous_solver_option(self):
        self.assertEqual(
            build_pss_statement(
                {
                    "Mode": PSS_MODE_OSCILLATOR,
                    "Fund": "800M",
                    "Harmonics": "11",
                }
            ),
            ".PSS 800MEG 11 OSCILLATOR=YES TSTAB_PERIODS=30 PSS_ADAPTIVE=YES PSS_CONTINUATION=YES "
            "USE_INITIAL_CONDITIONS=YES MAX_PSS_ITER=50",
        )

    def test_validation_rejects_bad_frequency_and_harmonics(self):
        errors = pss_validation_errors(
            {"Mode": PSS_MODE_OSCILLATOR, "Fund": "-1G", "Harmonics": "0"}
        )
        self.assertEqual(len(errors), 2)
        self.assertIn("Frequency estimate", errors[0])

    def test_advanced_pss_options_are_emitted(self):
        self.assertEqual(
            build_pss_statement(
                {
                    "Mode": PSS_MODE_OSCILLATOR,
                    "Fund": "800M",
                    "Harmonics": "11",
                    "Tstab": "250n",
                    "TstabPeriods": "5",
                    "Adaptive": True,
                    "Continuation": True,
                    "UseIC": True,
                    "ContinuationSteps": "4",
                    "MaxPssIter": "25",
                    "ResidualGoal": "0.25",
                }
            ),
            ".PSS 800MEG 11 OSCILLATOR=YES TSTAB=250n TSTAB_PERIODS=5 "
            "PSS_ADAPTIVE=YES PSS_CONTINUATION=YES USE_INITIAL_CONDITIONS=YES PSS_CONTINUATION_STEPS=4 "
            "MAX_PSS_ITER=25 PSS_RESIDUAL_GOAL=0.25",
        )

    def test_validation_rejects_bad_advanced_options(self):
        errors = pss_validation_errors(
            {
                "Mode": PSS_MODE_DRIVEN,
                "Fund": "1G",
                "Harmonics": "7",
                "Tstab": "-10n",
                "TstabPeriods": "0",
                "ContinuationSteps": "1.5",
                "MaxPssIter": "0",
                "ResidualGoal": "0",
            }
        )
        self.assertEqual(len(errors), 5)

    def test_engine_and_form_emit_the_same_oscillator_syntax(self):
        engine_setup = AnalysisSetup(
            AnalysisType.PSS,
            params={"mode": "oscillator", "fund": "1k", "harmonics": "3"},
        )
        self.assertEqual(
            engine_setup.to_spice(),
            ".PSS 1k 3 OSCILLATOR=YES TSTAB_PERIODS=30 PSS_ADAPTIVE=YES PSS_CONTINUATION=YES "
            "USE_INITIAL_CONDITIONS=YES MAX_PSS_ITER=50",
        )

        widget = AnalysisSetupWidget("PSS (Periodic Steady-State)")
        widget.set_values(
            {
                "Mode": "Oscillator (autonomous)",
                "Fund": "1k",
                "Harmonics": "3",
            }
        )
        self.assertEqual(widget.get_spice_line(), engine_setup.to_spice())
        self.assertEqual(widget.validation_errors(), [])
        self.assertEqual(
            widget._pss_frequency_label.text(),
            "Frequency estimate:",
        )

    def test_legacy_oscillator_boolean_migrates_when_loading_form(self):
        widget = AnalysisSetupWidget("PSS (Periodic Steady-State)")
        widget.set_values(
            {"Oscillator": True, "Fund": "10M", "Harmonics": "5", "Tstab": "1u"}
        )
        self.assertEqual(widget.get_values()["Mode"], PSS_MODE_OSCILLATOR)
        self.assertEqual(
            widget.get_spice_line(),
            ".PSS 10MEG 5 OSCILLATOR=YES TSTAB=1u PSS_ADAPTIVE=YES PSS_CONTINUATION=YES "
            "USE_INITIAL_CONDITIONS=YES MAX_PSS_ITER=50",
        )

    def test_form_exposes_advanced_pss_options(self):
        widget = AnalysisSetupWidget("PSS (Periodic Steady-State)")
        widget.set_values(
            {
                "Mode": PSS_MODE_OSCILLATOR,
                "Fund": "2G",
                "Harmonics": "15",
                "Tstab": "100n",
                "TstabPeriods": "3",
                "Adaptive": True,
                "Continuation": True,
                "UseIC": True,
                "ContinuationSteps": "2",
                "MaxPssIter": "40",
                "ResidualGoal": "0.5",
            }
        )
        self.assertEqual(
            widget.get_spice_line(),
            ".PSS 2G 15 OSCILLATOR=YES TSTAB=100n TSTAB_PERIODS=3 "
            "PSS_ADAPTIVE=YES PSS_CONTINUATION=YES USE_INITIAL_CONDITIONS=YES PSS_CONTINUATION_STEPS=2 "
            "MAX_PSS_ITER=40 PSS_RESIDUAL_GOAL=0.5",
        )
        self.assertEqual(widget.validation_errors(), [])

    def test_pnoise_form_emits_gspice_syntax(self):
        widget = AnalysisSetupWidget("PNOISE (Periodic Noise)")
        widget.set_values(
            {
                "Output": "V(OUTNET)",
                "Points": "25",
                "Fstart": "1k",
                "Fstop": "10MEG",
            }
        )
        self.assertEqual(widget.get_spice_line(), ".PNOISE V(OUTNET) none DEC 25 1k 10MEG")


if __name__ == "__main__":
    unittest.main()
