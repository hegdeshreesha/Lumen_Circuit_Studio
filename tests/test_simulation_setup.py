import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from lumen.core.simulation_setup import (
    CornerSetup,
    DeviceModelBinding,
    ModelDirective,
    SpecLimit,
    apply_device_parameter_callbacks,
    build_pdk_model_manifest,
    directives_to_netlist_entries,
    evaluate_specs,
    expand_run_matrix,
    extract_lib_sections,
    normalize_device_parameter_specs,
    parse_model_entries,
    symbol_data_with_parameter_specs,
    validate_model_bindings,
    validate_model_directives,
)
from lumen.core.database import LibraryDatabase
from lumen.core.netlist import NetlistGenerator


class SimulationSetupTest(unittest.TestCase):
    def test_extract_lib_sections_and_validate_missing_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib = Path(tmp) / "models.lib"
            lib.write_text(".LIB tt\n.model n nmos\n.ENDS tt\n.LIB ff\n.ENDS ff\n", encoding="utf-8")

            self.assertEqual(extract_lib_sections(lib), ["tt", "ff"])
            self.assertEqual(validate_model_directives([ModelDirective("lib", str(lib), "tt")]), [])
            self.assertIn(
                "Section 'ss' not found",
                validate_model_directives([ModelDirective("lib", str(lib), "ss")])[0],
            )

    def test_directives_convert_to_netlist_entries_without_duplicates(self):
        directives = [
            ModelDirective("lib", "a.lib", "tt"),
            ModelDirective("lib", "a.lib", "tt"),
            ModelDirective("include", "bias.sp", ""),
        ]

        includes, libs = directives_to_netlist_entries(directives)

        self.assertEqual(includes, [{"path": "bias.sp"}])
        self.assertEqual(libs, [{"path": "a.lib", "section": "tt"}])

    def test_corner_round_trip_preserves_manual_directives(self):
        corner = CornerSetup.from_dict({
            "name": "TT_25C",
            "temp": 25,
            "vdd": 1.2,
            "process": "tt",
            "model_directives": [{"kind": "lib", "path": "corner.lib", "section": "mos_tt"}],
        })

        data = corner.to_dict()

        self.assertEqual(data["name"], "TT_25C")
        self.assertEqual(data["model_directives"][0]["section"], "mos_tt")

    def test_run_matrix_expands_analyses_corners_and_sweeps(self):
        jobs = expand_run_matrix(
            ["TRAN", "AC"],
            [CornerSetup("tt"), CornerSetup("ff")],
            [("VDD=1.0", {"VDD": "1.0"}), ("VDD=1.2", {"VDD": "1.2"})],
            "All Corners",
        )

        self.assertEqual(len(jobs), 8)
        self.assertEqual(jobs[0].run_name, "tt | TRAN | VDD=1.0")
        self.assertEqual(jobs[-1].variables, {"VDD": "1.2"})

    def test_evaluate_specs_checks_metric_limits(self):
        results = evaluate_specs(
            [
                SpecLimit("final_ok", "V(out)", "final", "1.0", "1.3"),
                SpecLimit("pp_fail", "V(out)", "pp", "", "0.1"),
            ],
            {"V(out)": [0.0, 1.2]},
        )

        self.assertTrue(results[0]["passed"])
        self.assertFalse(results[1]["passed"])

    def test_parse_model_entries_discovers_models_and_subckts(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib = Path(tmp) / "models.lib"
            lib.write_text(
                ".LIB tt\n"
                ".MODEL nch NMOS LEVEL=1\n"
                ".SUBCKT gain in out vss\n"
                ".ENDS gain\n"
                ".ENDL tt\n",
                encoding="utf-8",
            )

            entries = parse_model_entries([ModelDirective("lib", str(lib), "tt")])

            self.assertEqual([entry.name for entry in entries], ["nch", "gain"])
            self.assertEqual(entries[0].device_type, "NMOS")
            self.assertEqual(entries[1].pins, ["in", "out", "vss"])

    def test_model_binding_validation_requires_known_instance_and_model(self):
        errors = validate_model_bindings(
            [DeviceModelBinding("M1", "missing")],
            [],
            {"M2"},
        )

        self.assertIn("unknown instance", errors[0])

    def test_device_parameter_specs_normalize_symbol_and_cdf_fields(self):
        symbol = symbol_data_with_parameter_specs({
            "parameters": [{
                "name": "w",
                "defValue": "1u",
                "display": "Width",
                "parseAsNumber": True,
                "choices": ["1u", "2u"],
            }]
        })
        specs = normalize_device_parameter_specs(symbol)

        self.assertEqual(specs[0].name, "w")
        self.assertEqual(specs[0].default, "1u")
        self.assertEqual(specs[0].display, "Width")
        self.assertTrue(symbol["parameters"][0]["numeric"])
        self.assertEqual(symbol["parameters"][0]["enum"], ["1u", "2u"])

    def test_device_parameter_callbacks_apply_data_only_updates(self):
        symbol = symbol_data_with_parameter_specs({
            "parameters": [
                {"name": "w", "default": "1u"},
                {"name": "display_w", "callback": "copy:w", "read_only": True},
            ]
        })

        params = apply_device_parameter_callbacks(symbol, {"w": "2u", "display_w": ""}, "w")

        self.assertEqual(params["display_w"], "2u")

    def test_netlist_generator_applies_model_binding_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = LibraryDatabase(tmp)
            gen = NetlistGenerator(db)
            gen.set_model_bindings({"M1": "custom_nch"})
            data = {
                "instances": [{
                    "name": "M1",
                    "library": "primitives",
                    "cell": "nmos",
                    "params": {"model": "nch", "W": "2u", "L": "180n"},
                }]
            }

            lines = gen._netlist_instances(
                data,
                {"M1.D": "d", "M1.G": "g", "M1.S": "s", "M1.B": "b"},
            )

            self.assertEqual(lines, ["M1 d g s b custom_nch W=2u L=180n nf=1"])

    def test_pdk_model_manifest_maps_corners_to_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib = Path(tmp) / "models.lib"
            lib.write_text(".LIB tt\n.ENDL tt\n.LIB ff\n.ENDL ff\n", encoding="utf-8")
            pdk = SimpleNamespace(
                name="demo",
                display_name="Demo PDK",
                supply_voltage=1.8,
                model_files=[SimpleNamespace(path=str(lib), corners=["tt", "ff"])],
                corners=[
                    SimpleNamespace(name="TT_25C", temperature=25, voltage=1.8, lib_section="tt"),
                    SimpleNamespace(name="FF_m40C", temperature=-40, voltage=1.98, lib_section="ff"),
                ],
            )

            manifest = build_pdk_model_manifest(pdk, "GSPICE")

            self.assertEqual(manifest.display_name, "Demo PDK")
            self.assertEqual(manifest.model_directives[0].section, "")
            self.assertEqual(manifest.corners[0].model_directives[0].section, "tt")
            self.assertEqual(manifest.corners[1].model_directives[0].section, "ff")


if __name__ == "__main__":
    unittest.main()
