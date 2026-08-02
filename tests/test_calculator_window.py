import unittest
import sys
from lumen.qt.QtWidgets import QApplication
from lumen.gui.calculator_window import CalculatorWindow

app = QApplication.instance() or QApplication(sys.argv)


class TestCalculatorWindow(unittest.TestCase):
    def test_calculator_window_init(self):
        waveforms = {
            "v(out)": ([0.0, 1e-9, 2e-9], [0.0, 0.6, 1.2])
        }
        win = CalculatorWindow(waveforms)
        self.assertEqual(win.sig_combo.count(), 1)
        self.assertEqual(win.sig_combo.currentText(), "v(out)")

        win._insert_function("rise_time")
        self.assertIn("rise_time", win.expr_edit.text())


if __name__ == "__main__":
    unittest.main()
