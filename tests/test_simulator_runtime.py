import os
import tempfile
import unittest
from pathlib import Path

from lumen.core.simulator import SimulatorBridge
from lumen.core.simulator_compare import compare_waveforms, format_reference_report, ReferenceRunComparison
from lumen.core.simulator_runtime import ACTIVE_SIMULATORS, SimulatorRuntimeManager


class SimulatorRuntimeManagerTest(unittest.TestCase):
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
            self.assertIn("Ngspice", sims)
            self.assertIn("Xyce", sims)
            self.assertEqual(set(ACTIVE_SIMULATORS), set(sims.keys()))

    def test_active_simulator_is_persisted_with_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SimulatorRuntimeManager(tmp)
            self.assertTrue(manager.set_active_simulator("ngspice"))
            self.assertEqual(manager.get_active_simulator(), "Ngspice")

            reloaded = SimulatorRuntimeManager(tmp)
            self.assertEqual(reloaded.get_active_simulator(), "Ngspice")

    def test_bridge_commands_for_external_raw_backends(self):
        ngspice = SimulatorBridge("NGSPICE", exe_path="ngspice")
        self.assertEqual(
            ngspice._build_command("input.sp", "output.raw", threads=8),
            ["ngspice", "-b", "-r", "output.raw", "input.sp"],
        )

        xyce = SimulatorBridge("xyce", exe_path="Xyce")
        self.assertEqual(
            xyce._build_command("input.sp", "output.raw", threads=8),
            ["Xyce", "-r", "output.raw", "input.sp"],
        )

    def test_bridge_collects_gspice_model_status_lines(self):
        bridge = SimulatorBridge("GSPICE", exe_path="gspice")
        statuses = bridge._collect_model_status(
            "MODEL_STATUS: OSDI_LOADED path=\"psp103.osdi\" models=PSP103VA\n"
            "MODEL_STATUS: OSDI_DEVICE instance=NM1 model=nch type=psp103va descriptor=PSP103VA\n",
            "",
        )
        self.assertEqual(
            statuses,
            [
                'OSDI_LOADED path="psp103.osdi" models=PSP103VA',
                "OSDI_DEVICE instance=NM1 model=nch type=psp103va descriptor=PSP103VA",
            ],
        )

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

    def test_xyce_adds_ihp_psp_plugin_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = Path(tmp) / "Xyce_Plugin_PSP103_VA.so"
            plugin.write_text("", encoding="utf-8")
            old = os.environ.get("LUMEN_XYCE_PLUGIN_DIR")
            os.environ["LUMEN_XYCE_PLUGIN_DIR"] = tmp
            try:
                deck = (
                    '.LIB "C:\\EDA\\LumenCircuitStudio\\external\\ihp_pdk\\ihp-sg13g2\\libs.tech\\xyce\\models\\cornerMOSlv.lib" mos_tt\n'
                    "XM1 out in vdd vdd sg13_lv_pmos l=0.13u w=0.15u\n"
                    ".TRAN 1n 1u\n"
                    ".END\n"
                )
                bridge = SimulatorBridge("Xyce", exe_path="Xyce")
                notes = bridge._prepare_command_line_rules(deck)
                cmd = bridge._build_command("input.sp", "waveforms.raw", threads=1)
            finally:
                if old is None:
                    os.environ.pop("LUMEN_XYCE_PLUGIN_DIR", None)
                else:
                    os.environ["LUMEN_XYCE_PLUGIN_DIR"] = old
            self.assertIn("-plugin", cmd)
            self.assertIn(str(plugin), cmd)
            self.assertTrue(any("Added IHP PSP plugin" in note for note in notes))

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
            cmd = bridge._build_command("input.sp", "waveforms.raw", threads=1)
            expected = str(con) if os.name == "nt" else str(exe)
            self.assertEqual(cmd[0], expected)

    def test_ngspice_writes_ihp_psp_osdi_startup_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = SimulatorBridge("Ngspice", exe_path="ngspice", work_dir=tmp)
            if not bridge._default_gspice_osdi_dir():
                self.skipTest("No local OSDI directory available")
            deck = (
                "XM1 out in vdd vdd sg13_lv_pmos l=0.13u w=0.15u\n"
                ".TRAN 1n 1u\n"
                ".END\n"
            )
            prepared, notes = bridge._prepare_netlist_for_simulator(deck)
            self.assertNotIn("pre_osdi", prepared.lower())
            self.assertTrue(any(".spiceinit" in note for note in notes))

            run_notes = bridge._prepare_simulator_run_directory(prepared)
            startup = Path(tmp) / ".spiceinit"
            self.assertTrue(startup.exists())
            startup_text = startup.read_text(encoding="utf-8").lower()
            self.assertIn("osdi", startup_text)
            self.assertIn("psp103va.osdi", startup_text)
            self.assertIn("pspnqs103va.osdi", startup_text)
            self.assertTrue(any(".spiceinit" in note for note in run_notes))

    def test_ngspice_psp_load_failure_gets_actionable_diagnostic(self):
        deck = "XM1 out in vdd vdd sg13_lv_pmos l=0.13u w=0.15u\n.END\n"
        bridge = SimulatorBridge("Ngspice", exe_path="ngspice")
        notes = bridge._backend_specific_diagnostics(
            "Unknown model type psp103va - ignored\ncould not find a valid modelname\n",
            "",
            deck,
        )
        self.assertTrue(notes)
        self.assertIn("did not load the IHP PSP", notes[0])

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


if __name__ == "__main__":
    unittest.main()
