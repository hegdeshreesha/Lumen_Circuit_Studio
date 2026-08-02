import unittest

from lumen.core.ade_engine import AnalysisSetup, AnalysisType


class NoiseSetupTest(unittest.TestCase):
    def test_noise_requires_output_node(self):
        with self.assertRaisesRegex(ValueError, "requires an output node"):
            AnalysisSetup(AnalysisType.NOISE, params={}).to_spice()

    def test_pnoise_requires_output_node(self):
        with self.assertRaisesRegex(ValueError, "requires an output node"):
            AnalysisSetup(AnalysisType.PNOISE, params={}).to_spice()

    def test_noise_outputs_are_not_double_wrapped(self):
        setup = AnalysisSetup(
            AnalysisType.NOISE,
            params={"output": "V(OUTNET)", "source": "V1", "points": "25", "fstart": "1k", "fstop": "10MEG"},
        )
        self.assertEqual(setup.to_spice(), ".NOISE V(OUTNET) V1 25 1k 10MEG")

    def test_pnoise_accepts_plain_node_name(self):
        setup = AnalysisSetup(
            AnalysisType.PNOISE,
            params={"output": "OUTNET", "points": "25", "fstart": "1k", "fstop": "10MEG"},
        )
        self.assertEqual(setup.to_spice(), ".PNOISE V(OUTNET) none DEC 25 1k 10MEG")


if __name__ == "__main__":
    unittest.main()
