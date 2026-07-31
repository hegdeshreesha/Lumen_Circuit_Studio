# Lumen Circuit Studio

Open-source analog/mixed-signal EDA workbench with schematic capture, symbol editing, PDK management, ADE flow, and GSPICE integration.

## Quick Start

```powershell
cd C:\EDA\LumenCircuitStudio
.\scripts\bootstrap_dev.ps1
.\.venv\Scripts\Activate.ps1
python -m lumen
```

If startup reports a missing dependency, run:

```powershell
python -m pip install -r requirements.txt
```

## Run Tests

```powershell
python -m unittest discover -s tests -v
```

## Verify Environment

```powershell
python scripts\verify_environment.py
```

## Beta Testing

For the current dogfood flow, start with `BETA_TESTING.md`. The beta focus is schematic to SimENV to simulator run to SigView, with run folders and logs preserved for every issue report.

## Repository Layout

- `lumen`: application code (GUI, core engines, netlisting, simulation integration)
- `tests`: automated test suite
- `schemas`: JSON schemas for design data validation
- `external`: third-party/vendor content
- `examples`: sample workspaces and designs
- `scripts`: utility scripts and manual debug tools
- `docs`: architecture notes, feature matrix, and migration notes
- `scratch`: temporary simulation/output workspace

## Current Feature Set

- Schematic editor with wires, labels, pins, instances, rotate/mirror, hierarchy navigation
- Symbol editor with drawing tools, pin editing, and auto-generate from schematic
- Library/cell/view database with analog primitive catalog
- PDK discovery and model parsing for built-in open PDK flows
- Netlist generation and simulator bridge
- ADE-style setup for analyses/corners/sweeps
- IHP SG13G2 KLayout integration with `SG13_dev` PCells, schematic/device
  correspondence, layer setup, and DRC/LVS command flow. See
  [IHP KLayout setup and Cadence-style workflow](docs/ihp_klayout_integration.md).

## License

Lumen Circuit Studio source code is licensed under the Apache License 2.0. See
`LICENSE`.

Third-party PDKs, model files, helper scripts, and Python packages keep their
own licenses. See `THIRD_PARTY_NOTICES.md`.

Note: the current GUI dependency is PyQt6, which is GPLv3/commercial licensed.
For Apache-only binary distribution, use a commercial PyQt license or port the
GUI binding layer to an LGPL/commercial Qt binding such as PySide6.
