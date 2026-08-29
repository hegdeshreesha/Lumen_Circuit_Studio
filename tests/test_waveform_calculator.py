import unittest
from lumen.core.waveform_calculator import WaveformCalculator, WaveformVector


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


if __name__ == "__main__":
    unittest.main()
