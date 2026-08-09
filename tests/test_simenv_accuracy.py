import unittest

from lumen.core.simulator import SimulatorBridge
from lumen.gui.ade_window import (
    ADEWindow,
    GSPICE_ACCURACY_PRESETS,
    GSPICE_TRANSIENT_TARGET_POINTS,
    gspice_transient_defaults,
)


class _TransientWidget:
    def __init__(self, values):
        self._values = dict(values)

    def get_values(self):
        return dict(self._values)


class _AnalysisHarness:
    _current_simulator = "GSPICE"
    _sim_accuracy = "Very High"
    _sim_timeout = 0
    _sim_tolerance_override = ""
    _sim_method = "Auto"
    _sim_save_mode = "all"
    _sim_adaptive_maxstep = True
    _sim_save_adaptive_points = True
    _sim_prefer_klu = True
    _accuracy_transient_defaults = ADEWindow._accuracy_transient_defaults
    _accuracy_presets = ADEWindow._accuracy_presets
    _accuracy_options_line = ADEWindow._accuracy_options_line
    _sim_method_token = ADEWindow._sim_method_token
    _sim_save_mode_token = ADEWindow._sim_save_mode_token
    _has_transient_initial_conditions = ADEWindow._has_transient_initial_conditions
    _sim_timeout_seconds = ADEWindow._sim_timeout_seconds


class _ConvergenceHarness(_AnalysisHarness):
    class _Convergence:
        @staticmethod
        def get_ic_lines():
            return [".IC STG2=1"]

    convergence_widget = _Convergence()


class SimEnvAccuracyTest(unittest.TestCase):
    def test_presets_keep_trtol_sane_and_tighten_lte_reltol(self):
        expected_lte = {"Low": 2e-2, "Medium": 5e-3, "High": 1e-3, "Very High": 3e-4}
        self.assertEqual(
            {name: float(values["TRTOL"]) for name, values in GSPICE_ACCURACY_PRESETS.items()},
            {"Low": 1.0, "Medium": 1.0, "High": 1.0, "Very High": 1.0},
        )
        self.assertEqual(
            {name: float(values["LTE_RELTOL"]) for name, values in GSPICE_ACCURACY_PRESETS.items()},
            expected_lte,
        )

    def test_very_high_five_microsecond_run_targets_fifty_thousand_points(self):
        defaults = gspice_transient_defaults("Very High", "5u")
        step = SimulatorBridge._parse_spice_number(defaults["step"])
        self.assertAlmostEqual(step, 100e-12)
        self.assertEqual(defaults["maxstep"], "")
        self.assertEqual(GSPICE_TRANSIENT_TARGET_POINTS["Very High"], 50_000)

    def test_gspice_accuracy_options_enable_fast_exact_reuse(self):
        line = ADEWindow._accuracy_options_line(_AnalysisHarness())
        self.assertIn("ACCURACY=VERYHIGH", line)
        self.assertIn("TRTOL=1", line)
        self.assertIn("LTE_RELTOL=3e-4", line)
        self.assertIn("SOLVER=KLU", line)
        self.assertIn("TRAN_STAMP_CACHE=1", line)
        self.assertIn("MAXSTEP=AUTO", line)
        self.assertIn("SAVEADAPTIVE=1", line)

    def test_timeout_auto_is_zero_for_bridge_default(self):
        self.assertEqual(ADEWindow._sim_timeout_seconds(_AnalysisHarness()), 0)

    def test_gspice_accuracy_options_can_leave_solver_auto(self):
        harness = _AnalysisHarness()
        harness._sim_prefer_klu = False
        line = ADEWindow._accuracy_options_line(harness)
        self.assertIn("SOLVER=AUTO", line)

    def test_gspice_accuracy_options_can_disable_internal_point_save(self):
        harness = _AnalysisHarness()
        harness._sim_save_adaptive_points = False
        line = ADEWindow._accuracy_options_line(harness)
        self.assertNotIn("SAVEADAPTIVE", line)

    def test_tolerance_override_tightens_reltol_and_lte_reltol(self):
        harness = _AnalysisHarness()
        harness._sim_tolerance_override = "1e-5"
        line = ADEWindow._accuracy_options_line(harness)
        self.assertIn("RELTOL=1e-5", line)
        self.assertIn("LTE_RELTOL=1e-5", line)
        self.assertIn("TRTOL=1", line)

    def test_loose_tolerance_override_is_ignored(self):
        harness = _AnalysisHarness()
        harness._sim_tolerance_override = "1"
        line = ADEWindow._accuracy_options_line(harness)
        self.assertIn("RELTOL=1e-4", line)
        self.assertIn("LTE_RELTOL=3e-4", line)
        self.assertNotIn("RELTOL=1 ", line)
        self.assertNotIn("LTE_RELTOL=1 ", line)

    def test_automatic_transient_defaults_scale_with_stop_time(self):
        short = SimulatorBridge._parse_spice_number(
            gspice_transient_defaults("High", "5u")["step"]
        )
        long = SimulatorBridge._parse_spice_number(
            gspice_transient_defaults("High", "10u")["step"]
        )
        self.assertAlmostEqual(long, 2.0 * short)

    def test_analysis_line_uses_scaled_defaults_when_fields_are_auto(self):
        widget = _TransientWidget({
            "Step": "Auto",
            "Stop": "5u",
            "Start": "0",
            "MaxStep": "Auto",
            "UIC": False,
        })
        line = ADEWindow._analysis_spice_line(_AnalysisHarness(), "Transient", widget)
        tokens = line.split()
        self.assertEqual(tokens[0], ".TRAN")
        self.assertAlmostEqual(SimulatorBridge._parse_spice_number(tokens[1]), 100e-12)
        self.assertEqual(tokens[2], "5u")
        self.assertEqual(len(tokens), 3)

    def test_analysis_line_preserves_explicit_step_and_maxstep(self):
        widget = _TransientWidget({
            "Step": "25p",
            "Stop": "5u",
            "Start": "0",
            "MaxStep": "10p",
            "UIC": False,
        })
        line = ADEWindow._analysis_spice_line(_AnalysisHarness(), "Transient", widget)
        self.assertEqual(line, ".TRAN 25p 5u 0 10p")

    def test_transient_line_implies_uic_from_ic_helpers(self):
        widget = _TransientWidget({
            "Step": "40p",
            "Stop": "2u",
            "Start": "0",
            "MaxStep": "Auto",
            "UIC": False,
        })
        line = ADEWindow._analysis_spice_line(_ConvergenceHarness(), "Transient", widget)
        self.assertEqual(line, ".TRAN 40p 2u UIC")

    def test_transient_line_keeps_explicit_uic(self):
        widget = _TransientWidget({
            "Step": "40p",
            "Stop": "2u",
            "Start": "0",
            "MaxStep": "Auto",
            "UIC": True,
        })
        line = ADEWindow._analysis_spice_line(_ConvergenceHarness(), "Transient", widget)
        self.assertEqual(line, ".TRAN 40p 2u UIC")


if __name__ == "__main__":
    unittest.main()
