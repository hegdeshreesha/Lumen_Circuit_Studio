import os
import tempfile
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from lumen.core.database import LibraryDatabase
from lumen.gui.ade_window import ADEWindow


class SimEnvGuiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = LibraryDatabase(tmp.name)
        win = ADEWindow(db, "lib", "cell")
        self.addCleanup(win.close)
        return win

    def test_analyses_tab_is_primary_setup_workspace(self):
        win = self._window()
        self.assertNotIn("All Analysis", [win.main_tabs.tabText(i) for i in range(win.main_tabs.count())])

        win._add_analysis("Transient")
        self.assertIn("Transient", win._analysis_tabs)
        self.assertEqual(win.main_tabs.tabText(win.main_tabs.currentIndex()), "Analyses")

    def test_analysis_form_edits_generated_directive(self):
        win = self._window()
        win._add_analysis("Transient")

        editor = win._analysis_tabs["Transient"]
        stop = editor._fields["Stop"]
        stop.setText("25u")
        stop.editingFinished.emit()

        self.assertIn("25u", win._analysis_spice_line("Transient", editor))

    def test_simenv_run_cleanup_clears_stale_dc_annotations(self):
        win = self._window()
        editor = SimpleNamespace(cleared=False)
        editor.clear_dc_annotations = lambda: setattr(editor, "cleared", True)
        win._find_schematic_editor = lambda: (editor, None)

        win._clear_schematic_dc_annotations_for_run()

        self.assertTrue(editor.cleared)

    def test_cadence_style_menus_are_present(self):
        win = self._window()
        menus = [action.text().replace("&", "") for action in win.menuBar().actions()]
        for name in ["Session", "Setup", "Analyses", "Simulation", "Results", "Tools", "Window"]:
            self.assertIn(name, menus)

    def test_corner_results_matrix_groups_runs_as_columns(self):
        win = self._window()
        result = SimpleNamespace(
            success=True,
            waveforms={"time": [0, 1], "V(out)": [0, 1.2]},
            netlist_path="",
            output_path="",
            artifacts={},
            log="",
            errors=[],
        )

        win._handle_simulation_result(result, "TT_25C")

        self.assertIn("TT_25C", win._corner_result_rows)
        self.assertEqual(win.corner_matrix_table.horizontalHeaderItem(0).text(), "TT_25C")
        self.assertIn("1/1 PASS", win.corner_matrix_table.item(0, 0).text())
        self.assertEqual(win.corner_matrix_table.verticalHeaderItem(1).text(), "Plots")
        self.assertIn("plot", win.corner_matrix_table.item(1, 0).text())

    def test_corner_matrix_exports_column_shaped_csv(self):
        win = self._window()
        result = SimpleNamespace(
            success=True,
            waveforms={"time": [0, 1], "V(out)": [0, 1.2]},
            netlist_path="",
            output_path="",
            artifacts={},
            log="",
            errors=[],
        )
        win._handle_simulation_result(result, "TT_25C")

        csv_path = os.path.join(tempfile.gettempdir(), "lumen_corner_matrix_test.csv")
        self.addCleanup(lambda: os.path.exists(csv_path) and os.remove(csv_path))
        win._export_corner_matrix_to_csv(csv_path)

        with open(csv_path, encoding="utf-8") as fh:
            data = fh.read()
        self.assertIn("Metric,TT_25C", data)
        self.assertIn("Status,1/1 PASS", data)
        self.assertIn("Plots,1 plot", data)


if __name__ == "__main__":
    unittest.main()
