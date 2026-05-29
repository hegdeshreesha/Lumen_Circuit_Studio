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
- KLayout runtime integration hooks for layout/DRC/LVS command flow

## License

Apache License 2.0
