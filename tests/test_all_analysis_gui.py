import os
import tempfile
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lumen.qt.QtCore import Qt
from lumen.qt.QtWidgets import QApplication

from lumen.core.database import LibraryDatabase
from lumen.core.simulation_setup import ModelDirective
from lumen.gui.ade_window import ADEWindow
from lumen.gui.schematic_editor_window import SchematicEditorWindow


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

    def test_gspice_tree_marks_prototype_rf_and_hides_unavailable_rf(self):
        win = self._window()
        labels = []
        enabled = {}
        for i in range(win.analysis_tree.topLevelItemCount()):
            parent = win.analysis_tree.topLevelItem(i)
            labels.append(parent.text(0))
            for j in range(parent.childCount()):
                child = parent.child(j)
                labels.append(child.text(0))
                enabled[child.text(0)] = bool(child.flags() & Qt.ItemFlag.ItemIsEnabled)

        self.assertIn("Prototype / Experimental", labels)
        self.assertIn("PSS (Periodic Steady-State) (prototype)", labels)
        self.assertFalse(enabled["PSS (Periodic Steady-State) (prototype)"])
        self.assertIn("S-Parameters", labels)

    def test_sparameter_preset_adds_sp_and_stability_outputs(self):
        win = self._window()

        win._apply_two_port_sparam_preset()

        self.assertIn("S-Parameters", win._analysis_tabs)
        output_exprs = [
            win.outputs_widget.table.item(row, 1).text()
            for row in range(win.outputs_widget.table.rowCount())
        ]
        self.assertIn('s_db(sig("S21"))', output_exprs)
        self.assertIn('return_loss_db(sig("S11"))', output_exprs)
        self.assertIn('stability_k(sig("S11"), sig("S12"), sig("S21"), sig("S22"))', output_exprs)

    def test_analysis_form_edits_generated_directive(self):
        win = self._window()
        win._add_analysis("Transient")

        editor = win._analysis_tabs["Transient"]
        stop = editor._fields["Stop"]
        stop.setText("25u")
        stop.editingFinished.emit()

        self.assertIn("25u", win._analysis_spice_line("Transient", editor))

    def test_lna_preset_adds_ac_noise_and_rf_outputs(self):
        win = self._window()

        win._apply_lna_ac_noise_preset()

        self.assertIn("AC Small-Signal", win._analysis_tabs)
        self.assertIn("Noise", win._analysis_tabs)
        output_exprs = [
            win.outputs_widget.table.item(row, 1).text()
            for row in range(win.outputs_widget.table.rowCount())
        ]
        self.assertIn("dB20(V(out)/V(in))", output_exprs)
        self.assertIn('lna_nf_db(V(out), V(in), sig("onoise_psd(V^2/Hz)"))', output_exprs)

    def test_pss_form_can_enable_oscillator_mode(self):
        win = self._window()
        win._add_analysis("PSS (Periodic Steady-State)")

        editor = win._analysis_tabs["PSS (Periodic Steady-State)"]
        editor.set_values({"Mode": "Oscillator (autonomous)", "Fund": "60M", "Harmonics": "7"})

        self.assertEqual(
            win._analysis_spice_line("PSS (Periodic Steady-State)", editor),
            ".PSS 60MEG 7 OSCILLATOR=YES TSTAB_PERIODS=30 PSS_ADAPTIVE=YES "
            "PSS_CONTINUATION=YES USE_INITIAL_CONDITIONS=YES MAX_PSS_ITER=50",
        )

    def test_all_save_mode_keeps_currents_explicit(self):
        win = self._window()
        win.outputs_widget._add_entry("out", "V(out)")
        win.outputs_widget._add_entry("V1.p", "I(V1)")

        self.assertEqual(win._output_save_lines(), [".SAVE ALL", ".SAVE I(V1)"])

    def test_outputs_can_delete_saved_voltage_and_current_rows(self):
        win = self._window()
        win.outputs_widget._add_entry("out", "V(out)")
        win.outputs_widget._add_entry("X1.S", "I(X1.S)")

        win.outputs_widget.table.selectAll()
        win.outputs_widget._delete_selected_rows()

        self.assertEqual(win.outputs_widget.table.rowCount(), 0)
        self.assertEqual(win.outputs_widget.get_save_lines(), [])

    def test_simenv_run_cleanup_clears_stale_dc_annotations(self):
        win = self._window()
        editor = SimpleNamespace(cleared=False)
        editor.clear_dc_annotations = lambda: setattr(editor, "cleared", True)
        win._find_schematic_editor = lambda: (editor, None)

        win._clear_schematic_dc_annotations_for_run()

        self.assertTrue(editor.cleared)

    def test_attached_library_pdk_is_preferred(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = LibraryDatabase(tmp.name)
        db.create_library("lib")
        db.set_library_pdk("lib", "ihp-sg13g2")
        win = ADEWindow(db, "lib", "cell")
        self.addCleanup(win.close)
        win._pdk_registry_loaded = True
        win._pdk_registry = SimpleNamespace(
            get_pdk=lambda name: SimpleNamespace(name=name) if name == "ihp-sg13g2" else None,
            get_active_name=lambda: "other_pdk",
        )

        self.assertEqual(win._infer_pdk_name(), "ihp-sg13g2")

    def test_attached_library_pdk_can_auto_apply_manifest(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        model_path = os.path.join(tmp.name, "demo.lib")
        with open(model_path, "w", encoding="utf-8") as fh:
            fh.write(".LIB tt\n.ENDL tt\n")
        db = LibraryDatabase(tmp.name)
        db.create_library("lib")
        db.set_library_pdk("lib", "demo")
        win = ADEWindow(db, "lib", "cell")
        self.addCleanup(win.close)
        pdk = SimpleNamespace(
            name="demo",
            display_name="Demo PDK",
            supply_voltage=1.8,
            model_files=[SimpleNamespace(path=model_path, corners=["tt"])],
            corners=[SimpleNamespace(name="tt", temperature=25, voltage=1.8, lib_section="tt")],
        )
        win._pdk_registry_loaded = True
        win._pdk_registry = SimpleNamespace(
            get_pdk=lambda name: pdk if name == "demo" else None,
            get_active_name=lambda: "",
        )

        self.assertTrue(win._auto_apply_attached_pdk_setup())
        self.assertEqual(win.pdk_combo.currentData(), "demo")
        self.assertEqual(win.model_table.rowCount(), 1)

    def test_dc_op_trace_name_parser_accepts_common_device_formats(self):
        self.assertEqual(SchematicEditorWindow._parse_dc_op_trace_name("@M1[gm]"), ("m1", "gm"))
        self.assertEqual(SchematicEditorWindow._parse_dc_op_trace_name("M1.id"), ("m1", "id"))
        self.assertEqual(SchematicEditorWindow._parse_dc_op_trace_name("XU1:M1:vth"), ("xu1m1", "vth"))

    def test_industry_style_menus_are_present(self):
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
        self.assertEqual(win.corner_matrix_table.verticalHeaderItem(0).text(), "Single")
        self.assertIn("1/1 PASS", win.corner_matrix_table.item(0, 0).text())
        self.assertIn("1 plot", win.corner_matrix_table.item(0, 0).text())

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
        self.assertIn("Variable Sweep,TT_25C", data)
        self.assertIn("Single,", data)
        self.assertIn("1/1 PASS", data)
        self.assertIn("1 plot", data)

    def test_run_matrix_status_tracks_result_state(self):
        win = self._window()
        job = ("TT_25C", "* netlist", "simenv_cell_tt")

        win._mark_jobs_pending([job])
        self.assertEqual(win._run_matrix_status[("TT_25C", "Single")], "Pending")

        win._mark_run_cell_status("TT_25C", "Running")
        self.assertEqual(win._run_matrix_status[("TT_25C", "Single")], "Running")

    def test_sort_results_preserves_waveform_row_mapping(self):
        win = self._window()
        fail = SimpleNamespace(
            success=False,
            waveforms={},
            netlist_path="",
            output_path="",
            artifacts={},
            log="",
            errors=[],
        )
        passed = SimpleNamespace(
            success=True,
            waveforms={"time": [0, 1], "V(out)": [0, 1.2]},
            netlist_path="",
            output_path="",
            artifacts={},
            log="",
            errors=[],
        )

        win._handle_simulation_result(passed, "TT_25C")
        win._handle_simulation_result(fail, "SS_125C")
        win.results_sort_combo.setCurrentText("Status")
        win._sort_results_rows()

        self.assertIn("FAIL", win.results_table.item(0, 6).text())
        self.assertEqual(win._count_plottable_signals(win._result_waveforms_by_row.get(1, {})), 1)

    def test_expression_can_promote_to_spec(self):
        win = self._window()

        row = win._add_spec_from_expression("V(out)", "max")

        self.assertGreaterEqual(row, 0)
        self.assertEqual(win.spec_widget.table.item(row, 1).text(), "V(out)")
        self.assertEqual(win.spec_widget.table.cellWidget(row, 2).currentText(), "max")

    def test_sort_results_by_spec_margin(self):
        win = self._window()
        win._add_spec_from_expression("V(out)", "final")
        win._set_table_text(win.spec_widget.table, 0, 3, "1.0")
        win._set_table_text(win.spec_widget.table, 0, 4, "1.3")
        weak = SimpleNamespace(
            success=True,
            waveforms={"time": [0, 1], "V(out)": [0, 1.01]},
            netlist_path="",
            output_path="",
            artifacts={},
            log="",
            errors=[],
        )
        strong = SimpleNamespace(
            success=True,
            waveforms={"time": [0, 1], "V(out)": [0, 1.2]},
            netlist_path="",
            output_path="",
            artifacts={},
            log="",
            errors=[],
        )

        win._handle_simulation_result(strong, "TT_25C")
        win._handle_simulation_result(weak, "FF_m40C")
        win.results_sort_combo.setCurrentText("Spec Margin")
        win._sort_results_rows()

        self.assertEqual(win.results_table.item(0, 0).text(), "FF_m40C")

    def test_model_libraries_are_saved_and_restored(self):
        win = self._window()
        model_path = os.path.join(str(win.db.workspace), "corner.lib")
        with open(model_path, "w", encoding="utf-8") as fh:
            fh.write(".LIB tt\n.ENDS tt\n")

        win._add_model_directive_row("lib", model_path, "tt")
        setup = win._collect_simenv_setup()

        restored = self._window()
        restored._apply_simenv_setup(setup)

        directives = restored._collect_model_table_directives()
        self.assertEqual(len(directives), 1)
        self.assertEqual(directives[0].path, model_path)
        self.assertEqual(directives[0].section, "tt")

    def test_model_library_ui_keeps_advanced_tables_in_subtabs(self):
        win = self._window()

        self.assertIn("Model Setup", [win.main_tabs.tabText(i) for i in range(win.main_tabs.count())])
        self.assertNotIn("Model Libraries", [win.main_tabs.tabText(i) for i in range(win.main_tabs.count())])
        self.assertTrue(hasattr(win, "model_advanced_tabs"))
        self.assertEqual(win.model_advanced_tabs.tabText(0), "Discovered Models")
        self.assertEqual(win.model_advanced_tabs.tabText(1), "Device Bindings")
        self.assertLessEqual(win.model_table.maximumHeight(), 190)
        self.assertTrue(hasattr(win, "model_corner_summary_table"))
        self.assertTrue(hasattr(win, "model_pdk_label"))
        self.assertTrue(hasattr(win, "model_pdk_health_label"))
        self.assertIn("PDK:", win.model_pdk_label.text())

    def test_cockpit_header_has_readiness_workflow(self):
        win = self._window()

        self.assertTrue(hasattr(win, "readiness_title"))
        self.assertTrue(hasattr(win, "readiness_detail"))
        self.assertIn("pdk", win.workflow_buttons)
        self.assertIn("run", win.workflow_buttons)

        status = win._setup_readiness()

        self.assertIn("pdk", status)
        self.assertEqual(win.readiness_title.text(), "Needs Setup")

    def test_corner_specific_model_directive_overrides_shared_models(self):
        win = self._window()
        shared = os.path.join(str(win.db.workspace), "shared.lib")
        corner = os.path.join(str(win.db.workspace), "corner.lib")
        for path in (shared, corner):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(".LIB tt\n.ENDS tt\n")

        win._add_model_directive_row("lib", shared, "tt")
        win._corner_model_directives["TT_25C"] = [ModelDirective("lib", corner, "tt")]

        resolved = win._resolved_model_directives("tt", "TT_25C", "")

        self.assertEqual([d.path for d in resolved], [corner])

    def test_model_setup_save_load_delete_helpers(self):
        win = self._window()
        model_path = os.path.join(str(win.db.workspace), "saved.lib")
        with open(model_path, "w", encoding="utf-8") as fh:
            fh.write(".LIB tt\n.ENDL tt\n")
        win._add_model_directive_row("lib", model_path, "tt")

        win._save_model_setup_named("MyModels")
        win.model_table.setRowCount(0)

        self.assertIn("MyModels", win._model_setup_names())
        self.assertTrue(win._load_model_setup_named("MyModels"))
        self.assertEqual(win._collect_model_table_directives()[0].path, model_path)
        self.assertTrue(win._delete_model_setup_named("MyModels"))
        self.assertNotIn("MyModels", win._model_setup_names())

    def test_model_sections_map_to_corner_processes(self):
        win = self._window()
        model_path = os.path.join(str(win.db.workspace), "corners.lib")
        with open(model_path, "w", encoding="utf-8") as fh:
            fh.write(".LIB mos_tt\n.ENDL mos_tt\n.LIB mos_ff\n.ENDL mos_ff\n.LIB mos_ss\n.ENDL mos_ss\n")
        win._add_model_directive_row("lib", model_path, "")

        win._map_model_sections_to_corners()

        self.assertEqual(win._corner_model_directives["TT_25C"][0].section, "mos_tt")
        self.assertEqual(win._corner_model_directives["FF_m40C"][0].section, "mos_ff")
        self.assertEqual(win._corner_model_directives["SS_125C"][0].section, "mos_ss")
        self.assertEqual(win.model_corner_summary_table.item(0, 2).text(), "mos_tt")

    def test_apply_pdk_setup_populates_models_and_corners(self):
        win = self._window()
        model_path = os.path.join(str(win.db.workspace), "demo.lib")
        with open(model_path, "w", encoding="utf-8") as fh:
            fh.write(".LIB tt\n.ENDL tt\n.LIB ff\n.ENDL ff\n")
        pdk = SimpleNamespace(
            name="demo",
            display_name="Demo PDK",
            supply_voltage=1.8,
            model_files=[SimpleNamespace(path=model_path, corners=["tt", "ff"])],
            corners=[
                SimpleNamespace(name="TT_25C", temperature=25, voltage=1.8, lib_section="tt"),
                SimpleNamespace(name="FF_m40C", temperature=-40, voltage=1.98, lib_section="ff"),
            ],
        )
        win._pdk_registry = SimpleNamespace(get_pdk=lambda name: pdk if name == "demo" else None)
        win._pdk_registry_loaded = True
        win.pdk_combo.addItem("Demo PDK", "demo")
        win.pdk_combo.setCurrentIndex(win.pdk_combo.findData("demo"))

        win._apply_selected_pdk_manifest()

        self.assertEqual(win.model_table.rowCount(), 1)
        self.assertEqual(win.corner_table.rowCount(), 2)
        self.assertEqual(win._corner_model_directives["FF_m40C"][0].section, "ff")
        self.assertEqual(win.corner_mode_combo.currentText(), "All Corners")

    def test_expression_history_and_baseline_are_saved(self):
        win = self._window()
        win._remember_expression("V(out)")
        win._set_result_baseline("TT_25C")

        setup = win._collect_simenv_setup()
        restored = self._window()
        restored._apply_simenv_setup(setup)

        self.assertEqual(restored._expression_history, ["V(out)"])
        self.assertEqual(restored._baseline_run_name, "TT_25C")

    def test_result_baseline_marks_run_row(self):
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
        win._set_result_baseline("TT_25C")

        row = win._latest_result_row_for_run("TT_25C")
        self.assertGreaterEqual(row, 0)
        self.assertEqual(win.results_table.item(row, 0).toolTip(), "Baseline run")


if __name__ == "__main__":
    unittest.main()
