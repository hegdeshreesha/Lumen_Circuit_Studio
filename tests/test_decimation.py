import unittest
from lumen.core.decimation import lttb_decimate


class TestLTTBDecimation(unittest.TestCase):
    def test_small_data_returns_unchanged(self):
        x = [0.0, 1.0, 2.0]
        y = [1.0, 3.0, 2.0]
        dx, dy = lttb_decimate(x, y, target_points=100)
        self.assertEqual(dx, x)
        self.assertEqual(dy, y)

    def test_decimation_reduces_point_count(self):
        # 10,000 point sine wave
        import math
        x = [i * 0.001 for i in range(10000)]
        y = [math.sin(2 * math.pi * t) for t in x]

        dx, dy = lttb_decimate(x, y, target_points=500)
        self.assertEqual(len(dx), 500)
        self.assertEqual(len(dy), 500)
        self.assertEqual(dx[0], x[0])
        self.assertEqual(dx[-1], x[-1])


if __name__ == "__main__":
    unittest.main()
