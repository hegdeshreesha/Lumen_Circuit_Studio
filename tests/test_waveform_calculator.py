import unittest
import math
import tempfile
from pathlib import Path
from lumen.core.ade_engine import ExpressionCalculator
from lumen.core.waveform_calculator import (
    WaveformCalculator,
    WaveformVector,
    constant_vswr_radius,
    gamma_to_impedance,
    noise_circle,
    noise_figure_from_params_db,
    parse_touchstone,
    polar_to_complex,
    real_l_match,
    real_l_match_components,
    stability_circle,
)


class TestWaveformCalculator(unittest.TestCase):
    def setUp(self):
        # Create dummy transient signal (0V to 1.2V step over 10ns)
        time = [i * 1e-9 for i in range(11)]
        v_in = [0.0 if i < 2 else 1.2 for i in range(11)]
        v_out = [0.0 if i < 4 else 1.2 for i in range(11)]
        self.calc = WaveformCalculator({
            "v(in)": (time, v_in),
            "v(out)": (time, v_out)
        })

    def test_vector_metrics(self):
        vec = self.calc.v("in")
        self.assertEqual(vec.max_value(), 1.2)
        self.assertEqual(vec.min_value(), 0.0)
        self.assertEqual(vec.peak_to_peak(), 1.2)

    def test_propagation_delay(self):
        delay = self.calc.propagation_delay("in", "out")
        self.assertAlmostEqual(delay, 2e-9, delta=1e-10)

    def test_scalar_metrics(self):
        self.assertEqual(self.calc.scalar("out", "final"), 1.2)
        self.assertEqual(self.calc.scalar("out", "pp"), 1.2)
        self.assertAlmostEqual(self.calc.scalar("out", "mean"), 0.7636363636)

    def test_crossing_time_interpolates_first_edge(self):
        calc = WaveformCalculator({"v(ramp)": ([0, 1, 2], [0, 0.5, 1.0])})

        self.assertEqual(calc.crossing_time("ramp", 0.25, "rising"), 0.5)

    def test_lna_gain_db_and_value_at_frequency(self):
        freq = [1e9, 2e9, 3e9]
        calc = WaveformCalculator({
            "V(in)": (freq, [1.0, 1.0, 1.0]),
            "V(out)": (freq, [5.0, 10.0, 5.0]),
        })

        gain = calc.gain_db("out", "in")

        self.assertAlmostEqual(gain.y[1], 20.0)
        self.assertAlmostEqual(calc.gain_db_at("out", "in", 2e9), 20.0)

    def test_lna_noise_figure_uses_output_noise_psd(self):
        freq = [1e9, 2e9]
        source_psd = 4.0 * 1.380649e-23 * 300.0 * 50.0
        gain = 10.0
        calc = WaveformCalculator({
            "V(in)": (freq, [1.0, 1.0]),
            "V(out)": (freq, [gain, gain]),
            "onoise_psd(V^2/Hz)": (freq, [source_psd * gain * gain * 2.0] * 2),
        })

        nf = calc.lna_noise_figure_db("out", "in")

        self.assertAlmostEqual(nf.y[0], 10.0 * math.log10(2.0))
        self.assertAlmostEqual(calc.lna_noise_figure_db_at("out", "in", 1.5e9), nf.y[0])

    def test_sparameter_db_and_return_loss_helpers(self):
        freq = [1e9, 2e9, 3e9]
        calc = WaveformCalculator({
            "S21": (freq, [1.0, 10.0, 1.0]),
            "S11": (freq, [0.5, 0.1, 0.5]),
            "S12": (freq, [0.02, 0.02, 0.02]),
            "S22": (freq, [0.2, 0.2, 0.2]),
        })

        s21_db = calc.sparam_db("s21")
        rl = calc.return_loss_db("S11")
        k = calc.stability_k_factor()
        mu = calc.mu_factor()

        self.assertAlmostEqual(s21_db.y[1], 20.0)
        self.assertAlmostEqual(calc.sparam_db_at("S21", 2e9), 20.0)
        self.assertAlmostEqual(rl.y[1], 20.0)
        self.assertGreater(k.y[1], 1.0)
        self.assertGreater(mu.y[1], 1.0)
        self.assertAlmostEqual(calc.return_loss_db_at("S11", 2.5e9), rl.value_at(2.5e9))
        zin_r, zin_x = calc.impedance_from_gamma("S11")
        self.assertAlmostEqual(zin_r.y[1], gamma_to_impedance(complex(0.1, 0.0)).real)
        self.assertAlmostEqual(zin_x.y[1], 0.0)
        self.assertAlmostEqual(calc.vswr().y[1], (1.0 + 0.1) / (1.0 - 0.1))

    def test_rf_matching_gain_and_noise_helpers(self):
        freq = [1e9, 2e9]
        calc = WaveformCalculator({
            "S11": (freq, [0.1, 0.1]),
            "phase(S11)": (freq, [0.0, 0.0]),
            "S12": (freq, [0.02, 0.02]),
            "S21": (freq, [10.0, 10.0]),
            "S22": (freq, [0.2, 0.2]),
            "phase(S22)": (freq, [0.0, 0.0]),
            "NFmin(dB)": (freq, [1.0, 1.0]),
            "Rn(ohm)": (freq, [5.0, 5.0]),
            "Gammaopt": (freq, [0.2, 0.2]),
            "phase(Gammaopt)": (freq, [0.0, 0.0]),
        })

        gs_mag, gs_phase = calc.input_match_gamma()
        gl_mag, gl_phase = calc.output_match_gamma()
        self.assertAlmostEqual(gs_mag.y[0], 0.1)
        self.assertAlmostEqual(gs_phase.y[0], -0.0)
        self.assertAlmostEqual(gl_mag.y[0], 0.2)
        self.assertAlmostEqual(gl_phase.y[0], -0.0)
        self.assertAlmostEqual(calc.transducer_gain_db().y[0], 20.0)
        nf = calc.noise_figure_from_params_db(gamma_source=polar_to_complex(0.2, 0.0))
        self.assertAlmostEqual(nf.y[0], 1.0)
        self.assertAlmostEqual(noise_figure_from_params_db(1.0, 5.0, polar_to_complex(0.2), polar_to_complex(0.2)), 1.0)
        center, radius = noise_circle(polar_to_complex(0.2), 1.0, 5.0, 2.0)
        self.assertTrue(math.isfinite(center.real))
        self.assertGreaterEqual(radius, 0.0)
        xs, bp = real_l_match(25.0, 1e9)
        self.assertGreater(xs, 0.0)
        self.assertGreater(bp, 0.0)
        parts = real_l_match_components(25.0, 1e9)
        self.assertGreater(parts["series_L_H"], 0.0)
        self.assertGreater(parts["shunt_C_F"], 0.0)
        sc, sr = stability_circle(0.1 + 0j, 0.02 + 0j, 10.0 + 0j, 0.2 + 0j)
        self.assertTrue(math.isfinite(sc.real))
        self.assertGreater(sr, 0.0)
        self.assertAlmostEqual(constant_vswr_radius((1.0 + 0.5) / (1.0 - 0.5)), 0.5)
        self.assertGreater(calc.stability_circle_radius().y[0], 0.0)

    def test_pa_compression_efficiency_and_ip3_helpers(self):
        sweep = [-20.0, -10.0, 0.0]
        calc = WaveformCalculator({
            "Pin(dBm)": (sweep, sweep),
            "Pout(dBm)": (sweep, [-5.0, 5.0, 14.0]),
            "Pout(W)": (sweep, [0.1, 0.5, 1.0]),
            "Pin(W)": (sweep, [0.001, 0.01, 0.1]),
            "Pdc(W)": (sweep, [1.0, 1.0, 1.0]),
            "Pfund(dBm)": (sweep, [0.0, 10.0, 20.0]),
            "Pim3(dBm)": (sweep, [-40.0, -10.0, 20.0]),
        })

        self.assertAlmostEqual(calc.p1db_input_dbm(), 0.0)
        self.assertAlmostEqual(calc.pae_percent().y[-1], 90.0)
        self.assertAlmostEqual(calc.output_ip3_dbm().y[0], 20.0)
        self.assertAlmostEqual(calc.input_ip3_dbm().y[1], 0.0)

        pull = WaveformCalculator({
            "Pout(dBm)": (sweep, [10.0, 12.0, 11.0]),
            "GammaL": (sweep, [0.1, 0.35, 0.2]),
            "phase(GammaL)": (sweep, [10.0, -45.0, 90.0]),
        }).optimum_gamma("Pout(dBm)")
        self.assertEqual(pull["metric"], 12.0)
        self.assertEqual(pull["gamma"], 0.35)
        self.assertEqual(pull["phase"], -45.0)

    def test_ade_expression_calculator_handles_rf_helpers(self):
        calc = ExpressionCalculator()
        waveforms = {
            "frequency": [1e9, 2e9],
            "S11": [0.5, 0.1],
            "S12": [0.02, 0.02],
            "S21": [2.0, 10.0],
            "S22": [0.2, 0.2],
            "phase(S11)": [0.0, 0.0],
            "phase(S12)": [0.0, 0.0],
            "phase(S21)": [0.0, 0.0],
            "phase(S22)": [0.0, 0.0],
            "Pout(W)": [0.5, 1.0],
            "Pin(W)": [0.01, 0.1],
            "Pdc(W)": [1.0, 1.0],
            "Pout(dBm)": [10.0, 12.0],
            "GammaL": [0.2, 0.4],
            "phase(GammaL)": [0.0, -30.0],
        }

        self.assertAlmostEqual(calc.evaluate('return_loss_db(sig("S11"))', waveforms)["y"][1], 20.0)
        self.assertAlmostEqual(calc.evaluate('real_z(sig("S11"), sig("phase(S11)"), 50)', waveforms)["y"][1], 50.0 * 1.1 / 0.9)
        self.assertAlmostEqual(calc.evaluate('pae_percent(sig("Pout(W)"), sig("Pin(W)"), sig("Pdc(W)"))', waveforms)["y"][1], 90.0)
        self.assertAlmostEqual(calc.evaluate('source_match_gamma(sig("S11"))', waveforms)["y"][1], 0.1)
        self.assertGreater(calc.evaluate('source_stability_radius(sig("S11"))', waveforms)["y"][1], 0.0)
        self.assertAlmostEqual(calc.evaluate('load_pull_gamma(sig("Pout(dBm)"))', waveforms)["y"][0], 0.4)

    def test_touchstone_parser_loads_two_port_ma_db_and_ri(self):
        with tempfile.TemporaryDirectory() as tmp:
            ma = Path(tmp) / "amp.s2p"
            ma.write_text(
                "# GHz S MA R 50\n"
                "1.0 0.5 0 2.0 45 0.02 180 0.1 -30\n",
                encoding="utf-8",
            )
            parsed = parse_touchstone(str(ma))
            self.assertEqual(parsed["frequency"], [1e9])
            self.assertEqual(parsed["S11"], [0.5])
            self.assertEqual(parsed["phase(S21)"], [45.0])

            db = Path(tmp) / "amp_db.s2p"
            db.write_text("# MHz S DB R 50\n1000 -6 0 20 0 -40 0 -20 0\n", encoding="utf-8")
            parsed_db = parse_touchstone(str(db))
            self.assertAlmostEqual(parsed_db["S21"][0], 10.0)

            ri = Path(tmp) / "amp_ri.s1p"
            ri.write_text("# Hz S RI R 50\n1e9 0 1\n", encoding="utf-8")
            parsed_ri = parse_touchstone(str(ri))
            self.assertAlmostEqual(parsed_ri["S11"][0], 1.0)
            self.assertAlmostEqual(parsed_ri["phase(S11)"][0], 90.0)

            three_port = Path(tmp) / "amp.s3p"
            three_port.write_text(
                "# Hz S MA R 50\n"
                "1e9 11 0 12 0 13 0 21 0 22 0 23 0 31 0 32 0 33 0\n",
                encoding="utf-8",
            )
            parsed_three_port = parse_touchstone(str(three_port))
            self.assertEqual(parsed_three_port["S12"], [12.0])
            self.assertEqual(parsed_three_port["S21"], [21.0])


if __name__ == "__main__":
    unittest.main()
