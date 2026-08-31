import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lumen.core.simulator import (
    SimulatorBridge,
    get_analysis_status,
    get_experimental_analyses,
    get_supported_analyses,
    get_simulator_timeout,
    get_unavailable_analyses,
)
from lumen.core.simulator_compare import compare_waveforms, format_reference_report, ReferenceRunComparison
from lumen.core.simulator_runtime import ACTIVE_SIMULATORS, SimulatorRuntimeManager


class SimulatorRuntimeManagerTest(unittest.TestCase):
    def test_model_directives_are_extracted_for_manifest(self):
        netlist = "\n".join([
            "* test",
            '.LIB "corner.lib" tt',
            '.INCLUDE "bias.sp"',
            '.GSDI "model.gsdi"',
            ".END",
        ])

        self.assertEqual(
            SimulatorBridge._extract_model_directives(netlist),
            ['.LIB "corner.lib" tt', '.INCLUDE "bias.sp"', '.GSDI "model.gsdi"'],
        )

    def test_set_active_and_apply_environment_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir(parents=True, exist_ok=True)
            fake_exe = workspace / "gspice.exe"
            fake_exe.write_text("", encoding="utf-8")

            manager = SimulatorRuntimeManager(str(workspace))
            self.assertTrue(manager.set_active_executable("GSPICE", str(fake_exe)))
            manager.apply_environment_overrides()
            self.assertEqual(
                os.environ.get("LUMEN_GSPICE_EXE", ""),
                str(fake_exe),
            )

    def test_runtime_summary_contains_gspice(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SimulatorRuntimeManager(tmp)
            summary = manager.runtime_summary()
            self.assertIn("simulators", summary)
            sims = summary["simulators"]
            self.assertIn("GSPICE", sims)
            self.assertNotIn("Ngspice", sims)
            self.assertNotIn("Xyce", sims)
            self.assertEqual(set(ACTIVE_SIMULATORS), set(sims.keys()))

    def test_gspice_default_timeout_is_bounded_for_production_runs(self):
        self.assertEqual(get_simulator_timeout("GSPICE"), 900)

    def test_gspice_rf_analyses_are_not_all_advertised_as_supported(self):
        supported = get_supported_analyses("GSPICE")
        experimental = get_experimental_analyses("GSPICE")
        unavailable = get_unavailable_analyses("GSPICE")

        self.assertIn("AC Small-Signal", supported)
        self.assertIn("Noise", supported)
        self.assertIn("S-Parameters", supported)
        self.assertIn("PSS (Periodic Steady-State)", experimental)
        self.assertIn("PNOISE (Periodic Noise)", experimental)
        self.assertIn("Harmonic Balance", unavailable)
        self.assertEqual(get_analysis_status("GSPICE", "S-Parameters"), "supported")

    def test_disabled_external_simulators_are_not_activated(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SimulatorRuntimeManager(tmp)
            self.assertFalse(manager.set_active_simulator("ngspice"))
            self.assertFalse(manager.set_active_simulator("xyce"))
            self.assertEqual(manager.get_active_simulator(), "GSPICE")

            reloaded = SimulatorRuntimeManager(tmp)
            self.assertEqual(reloaded.get_active_simulator(), "GSPICE")

    def test_default_gspice_config_upgrades_to_klu_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir(parents=True, exist_ok=True)
            internal = workspace / "internal" / "gspice.exe"
            release = workspace / "build" / "Release" / "gspice.exe"
            klu = workspace / "build-vcpkg" / "gspice.exe"
            internal.parent.mkdir(parents=True, exist_ok=True)
            release.parent.mkdir(parents=True, exist_ok=True)
            klu.parent.mkdir(parents=True, exist_ok=True)
            internal.write_text("", encoding="utf-8")
            release.write_text("", encoding="utf-8")
            klu.write_text("", encoding="utf-8")

            manager = SimulatorRuntimeManager(str(workspace))
            manager._config.setdefault("simulators", {})["GSPICE"] = {
                "active_executable": str(internal),
                "active_source": "default",
            }

            def has_klu(path: str) -> bool:
                return Path(path) == klu

            with patch.object(manager, "_preferred_candidate_paths", return_value=[str(release), str(klu)]), \
                    patch.object(manager, "probe_version", return_value="GSPICE test"), \
                    patch.object(manager, "_gspice_executable_has_klu", side_effect=has_klu):
                self.assertEqual(manager.get_active_executable("GSPICE"), str(klu))

    def test_gspice_klu_preference_selects_klu_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir(parents=True, exist_ok=True)
            internal = workspace / "internal" / "gspice.exe"
            klu = workspace / "build-vcpkg" / "gspice.exe"
            internal.parent.mkdir(parents=True, exist_ok=True)
            klu.parent.mkdir(parents=True, exist_ok=True)
            internal.write_text("", encoding="utf-8")
            klu.write_text("", encoding="utf-8")

            manager = SimulatorRuntimeManager(str(workspace))
            manager.set_active_executable("GSPICE", str(internal))

            def has_klu(path: str) -> bool:
                return Path(path) == klu

            with patch.object(manager, "_preferred_candidate_paths", return_value=[str(klu)]), \
                    patch.object(manager, "probe_version", return_value="GSPICE test"), \
                    patch.object(manager, "_gspice_executable_has_klu", side_effect=has_klu):
                self.assertTrue(manager.set_gspice_prefer_klu(True))
                self.assertEqual(manager.get_active_executable("GSPICE"), str(klu))

    def test_gspice_preferred_paths_try_vcpkg_before_plain_release(self):
        manager = SimulatorRuntimeManager(tempfile.gettempdir())
        preferred = manager._preferred_candidate_paths("GSPICE")
        self.assertLess(
            preferred.index(r"C:\EDA\GSPICE\build-vcpkg\gspice.exe"),
            preferred.index(r"C:\EDA\GSPICE\build\Release\gspice.exe"),
        )

    def test_external_raw_backends_are_not_launchable(self):
        for name in ("NGSPICE", "xyce"):
            bridge = SimulatorBridge(name, exe_path=name)
            self.assertFalse(bridge.is_available())
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                bridge._build_command("input.sp", "output.raw", threads=8)
            with patch("lumen.core.simulator.subprocess.Popen") as popen:
                result = bridge.simulate("V1 out 0 DC 1\n.OP\n.END\n")
            self.assertFalse(result.success)
            self.assertTrue(any("disabled" in error.lower() for error in result.errors))
            popen.assert_not_called()

    def test_bridge_collects_gspice_model_status_lines(self):
        bridge = SimulatorBridge("GSPICE", exe_path="gspice")
        statuses = bridge._collect_model_status(
            "MODEL_STATUS: NATIVE_COMPACT_MODEL model=nch type=psp103\n"
            "MODEL_STATUS: NATIVE_DEVICE instance=NM1 model=nch type=psp103\n",
            "",
        )
        self.assertEqual(
            statuses,
            [
                "NATIVE_COMPACT_MODEL model=nch type=psp103",
                "NATIVE_DEVICE instance=NM1 model=nch type=psp103",
            ],
        )

    def test_gspice_prepare_removes_markdown_separator_lines(self):
        bridge = SimulatorBridge("GSPICE", exe_path="gspice")
        prepared, notes = bridge._prepare_netlist_for_simulator(
            "* title\n-\nV1 out 0 DC 1\n.TRAN 1n 10n\n.END\n"
        )
        self.assertNotIn("\n-\n", prepared)
        self.assertIn("V1 out 0 DC 1", prepared)
        self.assertTrue(any("markdown separator" in note for note in notes))

    def test_gspice_prepare_preserves_method_for_psp_uic_auto_transient(self):
        bridge = SimulatorBridge("GSPICE", exe_path="gspice")
        prepared, notes = bridge._prepare_netlist_for_simulator(
            "X1 out in vdd vdd sg13_lv_pmos l=0.5u w=0.15u\n"
            ".OPTIONS METHOD=AUTO RELTOL=1e-4\n"
            ".TRAN 1p 1n UIC\n"
            ".END\n"
        )
        self.assertIn("METHOD=AUTO", prepared)
        self.assertNotIn("METHOD=BE", prepared)
        self.assertFalse(any("METHOD=BE selected" in note for note in notes))

    def test_gspice_prepare_preserves_method_for_non_uic_psp_transient(self):
        bridge = SimulatorBridge("GSPICE", exe_path="gspice")
        prepared, notes = bridge._prepare_netlist_for_simulator(
            "X1 out in vdd vdd sg13_lv_pmos l=0.5u w=0.15u\n"
            ".OPTIONS METHOD=AUTO RELTOL=1e-4\n"
            ".TRAN 1p 1n\n"
            ".END\n"
        )
        self.assertIn("METHOD=AUTO", prepared)
        self.assertNotIn("METHOD=BE", prepared)
        self.assertFalse(any("METHOD=BE selected" in note for note in notes))

    def test_gspice_prepare_does_not_insert_method_for_psp_transient(self):
        bridge = SimulatorBridge("GSPICE", exe_path="gspice")
        prepared, notes = bridge._prepare_netlist_for_simulator(
            "X1 out in vdd vdd sg13_lv_pmos l=0.5u w=0.15u\n"
            ".OPTIONS RELTOL=1e-4\n"
            ".TRAN 1p 1n\n"
            ".END\n"
        )
        self.assertIn(".OPTIONS RELTOL=1e-4", prepared)
        self.assertNotIn("METHOD=BE", prepared)
        self.assertFalse(any("METHOD=BE selected" in note for note in notes))

    def test_gspice_prepare_adds_ihp_model_library_for_naked_pdk_deck(self):
        bridge = SimulatorBridge("GSPICE", exe_path="gspice")
        prepared, notes = bridge._prepare_netlist_for_simulator(
            "* inverter\n"
            "XM1 out in vdd vdd sg13_lv_pmos l=0.13u w=0.15u\n"
            "XM2 out in 0 0 sg13_lv_nmos l=0.13u w=0.15u\n"
            ".TRAN 1n 1u\n"
            ".END\n"
        )
        if bridge._ihp_model_root():
            self.assertIn("cornerMOSlv.lib", prepared)
            self.assertIn("mos_tt", prepared)
            self.assertTrue(any("local IHP model" in note for note in notes))

    def test_gspice_crash_safe_keeps_subcircuit_instances(self):
        bridge = SimulatorBridge("GSPICE", exe_path="gspice")
        safe, notes = bridge._build_crash_safe_netlist(
            '.LIB "models.lib" mos_tt\n'
            "X1 out in vdd vdd sg13_lv_pmos l=0.5u w=0.15u\n"
            ".SAVE ALL\n"
            "C1 out 0 100f\n"
            ".PSS 60M 7 OSCILLATOR=YES USE_INITIAL_CONDITIONS=YES\n"
            ".END\n"
        )
        self.assertIn('.LIB "models.lib" mos_tt', safe)
        self.assertIn("X1 out in vdd vdd sg13_lv_pmos", safe)
        self.assertIn(".SAVE ALL", safe)
        self.assertIn(".PSS 60M 7 OSCILLATOR=YES USE_INITIAL_CONDITIONS=YES", safe)
        self.assertFalse(notes)

    def test_gspice_quality_rejects_stripped_or_loose_trivial_psp_transient(self):
        bridge = SimulatorBridge("GSPICE", exe_path="gspice")
        stdout = (
            "Transient summary: accepted=56 rejected=0 output_points=50002 min_step=1e-12 max_step=2.2e-08\n"
            "Accuracy summary: method=Auto reltol=1.000000000e+00 lte_reltol=1.000000000e+00\n"
            "Simulation Completed Successfully.\n"
        )
        deck = (
            "X1 out in vdd vdd sg13_lv_pmos l=0.5u w=0.15u\n"
            ".TRAN 2.2e-11 1.1u UIC\n"
            ".END\n"
        )
        errors = bridge._gspice_result_quality_errors(
            stdout,
            deck,
            transient_point_estimate=50002,
            crash_safe_notes=["[GSPICE crash-safe] Stripped 10 line(s) with risky/unsupported constructs and retried."],
        )
        self.assertTrue(any("crash-safe retry stripped" in error for error in errors))
        self.assertTrue(any("RELTOL=1" in error for error in errors))
        self.assertTrue(any("LTE_RELTOL=1" in error for error in errors))
        self.assertTrue(any("accepted only 56" in error for error in errors))

    def test_gspice_quality_allows_reasonable_transient_summary(self):
        bridge = SimulatorBridge("GSPICE", exe_path="gspice")
        stdout = (
            "Transient summary: accepted=240 rejected=2 output_points=50002 min_step=1e-14 max_step=2.2e-11\n"
            "Accuracy summary: method=Auto reltol=1.000000000e-04 lte_reltol=3.000000000e-04\n"
        )
        deck = "X1 out in vdd vdd sg13_lv_pmos l=0.5u w=0.15u\n.TRAN 2.2e-11 1.1u\n.END\n"
        self.assertEqual(
            bridge._gspice_result_quality_errors(stdout, deck, transient_point_estimate=50002, crash_safe_notes=[]),
            [],
        )

    def test_gspice_min_timestep_failure_gets_actionable_diagnostic(self):
        bridge = SimulatorBridge("GSPICE", exe_path="gspice")
        deck = (
            "X1 out in vdd vdd sg13_lv_pmos l=0.5u w=0.15u\n"
            ".OPTIONS RELTOL=1 LTE_RELTOL=1\n"
            ".TRAN 2.2e-11 1.1u UIC\n"
            ".END\n"
        )
        notes = bridge._backend_specific_diagnostics(
            "",
            "ERROR: Simulation failed: Transient step failed to converge at minimum timestep "
            "at time=2.356728984e-08 step=2.2e-14 update_error=inf residual_error=inf\n",
            deck,
        )
        self.assertTrue(any("minimum timestep" in note for note in notes))
        self.assertTrue(any("RELTOL=1" in note for note in notes))
        self.assertTrue(any("LTE_RELTOL=1" in note for note in notes))

    def test_gspice_dc_op_failure_gets_ring_startup_diagnostic(self):
        bridge = SimulatorBridge("GSPICE", exe_path="gspice")
        deck = (
            "X1 out in vdd vdd sg13_lv_pmos l=0.5u w=0.15u\n"
            ".PSS 60M 7 DRIVEN TSTAB=100n\n"
            ".TRAN 2.2e-11 1.1u\n"
            ".END\n"
        )
        notes = bridge._backend_specific_diagnostics(
            "Calculating DC Operating Point...\n",
            "ERROR: Simulation failed: DC operating point did not converge during "
            "Calculating DC Operating Point... PTC final\n",
            deck,
        )
        self.assertTrue(any("could not find a DC operating point" in note for note in notes))
        self.assertTrue(any("ring oscillators" in note for note in notes))
        self.assertTrue(any("driven PSS" in note for note in notes))

    def test_waveform_comparison_interpolates_reference_axis(self):
        primary = {
            "time": [0.0, 0.5, 1.0],
            "V(out)": [0.0, 0.5, 1.0],
        }
        reference = {
            "time": [0.0, 1.0],
            "V(out)": [0.0, 1.0],
        }
        comparisons = compare_waveforms(primary, reference)
        self.assertEqual(len(comparisons), 1)
        self.assertTrue(comparisons[0].passed)
        self.assertAlmostEqual(comparisons[0].max_abs_error, 0.0)

    def test_reference_report_marks_missing_reference_as_skip(self):
        report = format_reference_report([
            ReferenceRunComparison(
                simulator="Xyce",
                status="SKIP",
                message="Xyce executable not configured or not found",
            )
        ])
        self.assertIn("[Reference Xyce] SKIP", report)

    def test_xyce_routes_ihp_ngspice_model_library_to_xyce(self):
        deck = (
            '.LIB "C:\\EDA\\LumenCircuitStudio\\external\\ihp_pdk\\ihp-sg13g2\\libs.tech\\ngspice\\models\\cornerMOSlv.lib" mos_tt\n'
            "XM1 out in vdd vdd sg13_lv_pmos l=0.13u w=0.15u\n"
            ".TRAN 1n 1u\n"
            ".END\n"
        )
        bridge = SimulatorBridge("Xyce", exe_path="Xyce")
        prepared, notes = bridge._prepare_netlist_for_simulator(deck)
        self.assertIn("libs.tech\\xyce\\models\\cornerMOSlv.lib", prepared)
        self.assertIn(".PREPROCESS replaceground true", prepared)
        self.assertTrue(any("Routed IHP model library to xyce" in note for note in notes))

    def test_xyce_does_not_add_external_psp_plugin(self):
        deck = (
            '.LIB "C:\\EDA\\LumenCircuitStudio\\external\\ihp_pdk\\ihp-sg13g2\\libs.tech\\xyce\\models\\cornerMOSlv.lib" mos_tt\n'
            "XM1 out in vdd vdd sg13_lv_pmos l=0.13u w=0.15u\n"
            ".TRAN 1n 1u\n"
            ".END\n"
        )
        bridge = SimulatorBridge("Xyce", exe_path="Xyce")
        self.assertEqual(bridge._prepare_command_line_rules(deck), [])

    def test_xyce_prepare_adds_print_and_skips_generic_options(self):
        deck = "V1 out 0 DC 1\n.OPTIONS RELTOL=1e-4\n.TRAN 1n 10n\n.END\n"
        bridge = SimulatorBridge("Xyce", exe_path="Xyce")
        prepared, notes = bridge._prepare_netlist_for_simulator(deck)
        self.assertIn(".PRINT TRAN FORMAT=RAW V(*)", prepared)
        self.assertIn("skipped SPICE/GSPICE options", prepared)
        self.assertTrue(any("Added .PRINT TRAN" in note for note in notes))

    def test_ngspice_uses_console_executable_on_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "ngspice.exe"
            con = Path(tmp) / "ngspice_con.exe"
            exe.write_text("", encoding="utf-8")
            con.write_text("", encoding="utf-8")
            bridge = SimulatorBridge("Ngspice", exe_path=str(exe))
            self.assertFalse(bridge.is_available())
            self.assertEqual(
                bridge._ngspice_batch_executable(),
                str(con) if os.name == "nt" else str(exe),
            )

    def test_ngspice_does_not_write_external_model_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = SimulatorBridge("Ngspice", exe_path="ngspice", work_dir=tmp)
            deck = (
                "XM1 out in vdd vdd sg13_lv_pmos l=0.13u w=0.15u\n"
                ".TRAN 1n 1u\n"
                ".END\n"
            )
            prepared, notes = bridge._prepare_netlist_for_simulator(deck)
            self.assertNotIn(".spiceinit", prepared.lower())
            self.assertFalse(any(".spiceinit" in note for note in notes))

            run_notes = bridge._prepare_simulator_run_directory(prepared)
            startup = Path(tmp) / ".spiceinit"
            self.assertFalse(startup.exists())
            self.assertEqual(run_notes, [])

    def test_ngspice_psp_load_failure_gets_actionable_diagnostic(self):
        deck = "XM1 out in vdd vdd sg13_lv_pmos l=0.13u w=0.15u\n.END\n"
        bridge = SimulatorBridge("Ngspice", exe_path="ngspice")
        notes = bridge._backend_specific_diagnostics(
            "Unknown model type psp103va - ignored\ncould not find a valid modelname\n",
            "",
            deck,
        )
        self.assertTrue(notes)
        self.assertIn("PSP-class compact model", notes[0])

    def test_ascii_raw_parser_accepts_gspice_unindexed_rows(self):
        raw = (
            "Title: GSPICE RAW output\n"
            "Plotname: Transient Analysis\n"
            "Flags: real\n"
            "No. Variables: 3\n"
            "No. Points: 2\n"
            "Variables:\n"
            "0\ttime\ttime\n"
            "1\tV(out)\tvoltage\n"
            "2\tV(in)\tvoltage\n"
            "Values:\n"
            "0.0 2.0 0.0\n"
            "1e-9 0.0 2.0\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".raw", delete=False) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name
        try:
            waveforms = SimulatorBridge("GSPICE")._parse_raw(tmp_path)
        finally:
            os.remove(tmp_path)
        self.assertEqual(waveforms["time"], [0.0, 1e-9])
        self.assertEqual(waveforms["V(out)"], [2.0, 0.0])
        self.assertEqual(waveforms["V(in)"], [0.0, 2.0])

    def test_gspice_stdout_frequency_tables_keep_rf_axis_and_noise_names(self):
        stdout = (
            "freq | onoise_sqrt(V/rtHz) onoise_psd(V^2/Hz) noise_sources\n"
            "1.000000000e+09 | 2.0e-9 4.0e-18 3\n"
            "2.000000000e+09 | 3.0e-9 9.0e-18 3\n"
        )

        waveforms = SimulatorBridge("GSPICE")._parse_gspice_stdout(stdout)

        self.assertEqual(waveforms["frequency"], [1e9, 2e9])
        self.assertEqual(waveforms["onoise_psd(V^2/Hz)"], [4.0e-18, 9.0e-18])
        self.assertNotIn("time", waveforms)
        self.assertNotIn("V(onoise_psd(V^2/Hz))", waveforms)

    def test_gspice_stdout_parses_current_pss_converged_summary(self):
        stdout = (
            "Starting PSS shooting: f0=1.000000000e+03 period=1.000000000e-03 "
            "samples_per_period=64\n"
            "PSS Converged: periods=2 residual=3.3e-09\n"
        )

        waveforms = SimulatorBridge("GSPICE")._parse_gspice_stdout(stdout)

        self.assertEqual(waveforms["sample"], [0.0])
        self.assertEqual(waveforms["PSS_frequency"], [1e3])
        self.assertEqual(waveforms["PSS_period"], [1e-3])
        self.assertEqual(waveforms["PSS_periods"], [2.0])
        self.assertEqual(waveforms["PSS_residual"], [3.3e-9])

    def test_ascii_raw_parser_accepts_periodic_rf_outputs(self):
        raw = (
            "Title: GSPICE RAW output\n"
            "Plotname: PNOISE Analysis\n"
            "Flags: real\n"
            "No. Variables: 4\n"
            "No. Points: 2\n"
            "Variables:\n"
            "0\tfrequency\tfrequency\n"
            "1\tpnoise_sqrt(V/rtHz)\tvoltage_noise\n"
            "2\tpnoise_psd(V^2/Hz)\tnoise_psd\n"
            "3\tnoise_sources\tcount\n"
            "Values:\n"
            "1e3 2e-9 4e-18 1\n"
            "2e3 3e-9 9e-18 1\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".raw", delete=False) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name
        try:
            waveforms = SimulatorBridge("GSPICE")._parse_raw(tmp_path)
        finally:
            os.remove(tmp_path)
        self.assertEqual(waveforms["frequency"], [1e3, 2e3])
        self.assertEqual(waveforms["pnoise_psd(V^2/Hz)"], [4e-18, 9e-18])

    def test_gspice_pss_summary_writes_one_point_raw_fallback(self):
        bridge = SimulatorBridge("GSPICE")
        stdout = (
            "PSS summary: oscillator=yes autonomous=yes residual=1.2e-03 "
            "period=1.136e-08 frequency=8.8e+07 phase_unknown=3\n"
        )
        waveforms = bridge._parse_gspice_stdout(stdout)
        self.assertEqual(waveforms["sample"], [0.0])
        self.assertEqual(waveforms["PSS_frequency"], [8.8e7])
        self.assertEqual(waveforms["PSS_period"], [1.136e-8])
        self.assertEqual(waveforms["PSS_residual"], [1.2e-3])

        with tempfile.TemporaryDirectory() as tmp:
            raw_path = Path(tmp) / "pss.raw"
            self.assertTrue(bridge._write_ascii_raw_fallback(str(raw_path), waveforms))
            parsed = bridge._parse_raw(str(raw_path))
            self.assertEqual(parsed["sample"], [0.0])
            self.assertEqual(parsed["PSS_frequency"], [8.8e7])


if __name__ == "__main__":
    unittest.main()
