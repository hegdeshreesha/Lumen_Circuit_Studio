# Lumen Circuit Studio Project Index

Last indexed: 2026-08-01

## Snapshot

- Python/PyQt6 desktop EDA workbench for schematic capture, symbols, PDKs, Simulation Cockpit simulation, GSPICE, SigView, and KLayout integration.
- Entry point: `python -m lumen`
- App bootstrap: `lumen/__main__.py` -> `lumen/app.py`
- Project-owned files excluding `.git`, `.venv`, and `external`: about 355 files, 112 Python files, 27 test files.
- Large vendor/PDK payloads live under `external/` and are not project code.

## Commands

```powershell
cd C:\EDA\LumenCircuitStudio
.\.venv\Scripts\Activate.ps1
python -m lumen
python -m pytest tests
python scripts\verify_environment.py
```

## Top-Level Layout

- `lumen/`: application source.
- `lumen/core/`: non-GUI engines: database, netlisting, PDKs, simulation, hierarchy, layout, calculators.
- `lumen/gui/`: PyQt6 windows and widgets.
- `lumen/klayout/`: KLayout bridge/client scripts.
- `lumen/pdk/`: built-in PDK registry/model helpers.
- `lumen/*_symbols/`, `lumen/symbols_imported/`: generated/imported symbol JSON payloads.
- `tests/`: unit and GUI smoke tests.
- `schemas/`: JSON schemas for schematic, symbol, and PDK manifest data.
- `scripts/`: bootstrap, batch, debug, import, and environment helpers.
- `tools/`: KLayout/IHP verification helpers.
- `docs/`: architecture notes and workflow docs.
- `external/`: third-party PDK/vendor content.
- `scratch/`, `runs/`, `logs/`, `exports/`: generated working/output areas.

## Main GUI Modules

- `lumen/gui/apw_window.py`: application/project window.
- `lumen/gui/main_window.py`: primary Lumen main window.
- `lumen/gui/schematic_editor.py`: schematic canvas, wires, labels, pins, instances, output picking.
- `lumen/gui/schematic_editor_window.py`: schematic editor shell, menus, netlisting, SimENV handoff.
- `lumen/gui/symbol_editor.py`: symbol canvas and editing model.
- `lumen/gui/symbol_editor_window.py`: symbol editor shell.
- `lumen/GUI/Simulation Cockpit_window.py`: SimENV/Simulation Cockpit GUI, analyses, outputs, measurements, convergence helpers, run orchestration.
- `lumen/gui/waveform_viewer.py`: SigView waveform viewer and calculator UI.
- `lumen/gui/pdk_manager_window.py`: PDK management UI.
- `lumen/gui/simulator_manager_window.py`: simulator discovery/install UI.
- `lumen/gui/library_manager_window.py`, `library_browser.py`, `cellview_window.py`: library/cell/view navigation.

## Core Modules By Area

### Design Database

- `lumen/core/database.py`: JSON-backed library database used by the GUI.
- `lumen/core/db_engine.py`: richer design database model with libraries, cells, views, config, snapshots.
- `lumen/core/project_system.py`: project metadata and project creation/opening.
- `lumen/core/config_view.py`: config view bindings.
- `lumen/core/validation.py`: schema validation.

### Schematic And Netlisting

- `lumen/core/connectivity.py`: wire segments, junctions, net extraction.
- `lumen/core/hierarchy.py`: hierarchy tree and cross-probing helpers.
- `lumen/core/netlist.py`: SPICE netlist generation and directives.
- `lumen/core/component_validation.py`: SPICE numeric parsing and parameter validation.
- `lumen/core/component_imports.py`: file-backed component validation.
- `lumen/core/component_capabilities.py`: simulator support checks for component models.
- `lumen/core/commands.py`: undo/redo command stack.

### Simulation Cockpit

- `lumen/core/ade_engine.py`: Simulation Cockpit Session/state, analyses, outputs, corners, sweeps, run records.
- `lumen/core/simulator.py`: simulator bridge, netlist preparation, GSPICE/ngspice/Xyce execution.
- `lumen/core/simulator_runtime.py`: simulator executable discovery/config.
- `lumen/core/simulator_compare.py`: reference simulator comparison.
- `lumen/core/results_store.py`: run manifests and result hashing.
- `lumen/core/run_plan.py`: run planning/execution helpers.
- `lumen/core/gspice_diagnostics.py`: simulator log diagnostics.
- `lumen/core/pss.py`: PSS statement builder and validation.

### Waveforms

- `lumen/core/waveform_calculator.py`: waveform math engine.
- `lumen/core/decimation.py`: LTTB decimation for plotting.

### PDK And Symbols

- `lumen/core/pdk.py`: built-in PDK registry and generated symbols.
- `lumen/core/pdk_unified.py`: unified PDK schema, lockfile, model parser, registry.
- `lumen/core/pdk_schema.py`: PDK data classes and discovery parser.
- `lumen/core/pdk_service.py`: workspace-scoped registry cache.
- `lumen/core/pdk_library_manager.py`: technology libraries, lib corners, PDK installs.
- PDK workflow manager: PDK-style CDF/CDS/model management.
- `lumen/core/skywater_symbols.py`, `gf180mcu_symbols.py`, `ihp_symbols.py`: generated primitive symbol data.
- `lumen/core/xschem_parser.py`, `xschem_symbol_import.py`: Xschem import path.

### Layout And KLayout

- `lumen/core/layout_layers.py`: KLayout layer-property parsing.
- `lumen/core/layout_xl.py`: layout service actions.
- `lumen/core/klayout_runtime.py`: KLayout executable discovery/config.
- `lumen/core/klayout_adapter.py`: KLayout CLI bridge.
- `lumen/core/klayout_ipc.py`: KLayout IPC selection server.
- `lumen/core/ihp_klayout_devices.py`: IHP schematic-device to KLayout PCell mapping.
- `lumen/klayout/lumen_ihp_bridge.py`: KLayout-side IHP bridge.
- `lumen/klayout/lumen_klayout_client.py`: client helper.

## Tests

- GUI/Simulation Cockpit: `tests/test_all_analysis_gui.py`, `tests/test_pss_setup.py`, `tests/test_ac_setup.py`, `tests/test_simenv_accuracy.py`.
- Simulation: `tests/test_simulator_runtime.py`, `tests/test_simulator_ssh.py`, `tests/test_gspice_diagnostics.py`.
- Database/project: `tests/test_database.py`, `tests/test_project_system.py`, `tests/test_workflow_foundations.py`.
- Schematic/netlist: `tests/test_core_smoke.py`, `tests/test_netlist_qucs.py`, `tests/test_net_naming_sigview.py`, `tests/test_schematic_clipboard.py`.
- PDK/import: `tests/test_pdk_service.py`, `tests/test_pdk_unified_lockfile.py`, `tests/test_pdk_registry_install_state.py`, `tests/test_ihp_xschem_import.py`, `tests/test_ihp_klayout_devices.py`.
- Layout/KLayout: `tests/test_layout_layers.py`, `tests/test_layout_xl.py`, `tests/test_klayout_runtime.py`, `tests/test_klayout_ipc.py`, `tests/test_klayout_client.py`.
- Waveforms: `tests/test_waveform_calculator.py`, `tests/test_calculator_window.py`, `tests/test_decimation.py`.

## Current Working Tree Notes

- Modified: `lumen/core/pss.py`, `lumen/GUI/Simulation Cockpit_window.py`, `tests/test_all_analysis_gui.py`, `tests/test_pss_setup.py`.
- Untracked at index time: `.lumen_simulators.json`, `docs/dummy1_dummy2_klayout_tutorial.md`, `external/xschem_sky130/`.
- Recent focused verification: `.\.venv\Scripts\python.exe -m pytest .\tests\test_pss_setup.py .\tests\test_all_analysis_gui.py` passed.


