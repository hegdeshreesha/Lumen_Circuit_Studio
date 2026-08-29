# Lumen Circuit Studio Agent Guide

Lumen is a Python/PySide6 desktop EDA workbench. Keep changes focused on the
requested GUI/core/simulator flow and preserve local run artifacts.

## Commands

```powershell
cd C:\EDA\LumenCircuitStudio
.\scripts\bootstrap_dev.ps1
.\.venv\Scripts\Activate.ps1
python -m lumen
python scripts\verify_environment.py
python -m unittest discover -s tests -v
```

Focused tests are preferred during development:

```powershell
python -m unittest tests.test_simulator_runtime tests.test_waveform_calculator
```

## Repo Map

- `lumen`: application code.
- `tests`: unittest suite.
- `schemas`: JSON schemas for project/design data.
- `scripts`: bootstrap, validation, debug, and batch helpers.
- `docs`: architecture notes and workflow docs.
- `external`: vendor/PDK content; do not edit unless explicitly requested.
- `scratch`, `runs`, `logs`, `tmp`: local outputs; do not commit.

## Development Rules

- Check `git status --short` before edits; this repo often has active local
  work in progress.
- For simulator bugs, inspect both `lumen/core/simulator.py` and the relevant
  GUI/setup tests before patching symptoms.
- For schematic or symbol behavior, add or update a focused test under `tests`
  when practical.
- Keep GUI changes consistent with existing PySide6 patterns. Avoid adding new
  dependencies unless the existing stack cannot handle the task.
- Preserve run folders and logs when debugging failed simulations.

## Verification Ladder

1. Import or unit test for the touched module.
2. Focused workflow test, for example simulator runtime or waveform calculator.
3. `python -m unittest discover -s tests -v` for broad changes.
4. Manual `python -m lumen` only when visual GUI behavior changed.

