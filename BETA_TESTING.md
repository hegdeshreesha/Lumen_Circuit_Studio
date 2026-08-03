# Lumen Circuit Studio Beta Testing Guide

Date: 2026-07-16

This beta is for dogfooding the Lumen schematic, SimENV, simulator-run, and SigView workflow. It is not a signoff release. GSPICE is included as Lumen's native experimental simulator, and Ngspice/Xyce backends are available when their local executables and model/plugin files are installed.

## Beta Goal

The main goal is to prove that a tester can:

1. Launch Lumen.
2. Open or create a schematic.
3. Configure SimENV.
4. Run a simulation.
5. Inspect the generated run folder.
6. Open waveforms in SigView.
7. Report any mismatch with the deck, logs, manifest, and screenshots.

## Quick Start

```powershell
cd C:\EDA\LumenCircuitStudio
python -m pip install -r requirements.txt
python -m lumen
```

If Python dependencies are already installed, only the last command is needed.

## Recommended First Tests

Use small circuits first:

- DC resistor divider
- RC transient step
- Diode DC operating point
- Pulse source transient
- CMOS inverter with a small load capacitor
- Simple behavioral source
- Simple AC analysis

Avoid very long runs for the first beta pass. For transient analysis, start with a short stop time and avoid forcing extremely small output steps unless needed.

## Simulation Backends

Lumen can target:

- GSPICE: native experimental backend.
- Ngspice: external open-source backend.
- Xyce: external open-source backend.

Each backend has different model-library and plugin requirements. A beta run is valid only if the SimENV log shows the selected backend, the generated command, and the run folder.

## Run Folder Checklist

Every simulation run should create a timestamped folder containing:

- `input.sp`
- `stdout.log`
- `stderr.log`
- `run_manifest.json`
- `waveforms.raw` when the simulator produced a RAW file

If SigView shows unexpected waveforms, attach the whole run folder when reporting the issue.

## Expected Beta Behavior

- Failed simulations should fail loudly with readable diagnostics.
- Unsupported model syntax should not silently fall back to a primitive device.
- SigView should not show random cross-connected traces from malformed or partial RAW files.
- Stopping a simulation should stop the simulator process and leave a manifest/log trail.
- Switching simulators should visibly change backend rules and generated deck behavior.

## Known Limitations

- GSPICE is not yet signoff-class or mature-reference-class for all compact-model cases.
- Native PSP-class compact-model support is not production-ready yet.
- Xyce PSP flows require the matching Xyce plugin to be installed.
- Unsupported PSP-class decks should fail closed until native support exists.
- Large RAW files may still need further lazy-loading and decimation work.
- Layout-related flows are not part of this beta gate.

## Useful Validation Commands

```powershell
cd C:\EDA\LumenCircuitStudio
python -m unittest tests.test_simulator_runtime tests.test_net_naming_sigview
```

For GSPICE:

```powershell
cd C:\EDA\GSPICE
ctest --test-dir build -C Release --output-on-failure
```

If `cmake` is not on `PATH`, try:

```powershell
& "C:\Program Files\CMake\bin\cmake.exe" --build C:\EDA\GSPICE\build --config Release
```

## Bug Reports

Please include:

- What circuit was run.
- Which simulator backend was selected.
- The full run folder.
- Screenshot of SigView or SimENV if relevant.
- Whether Ngspice/Xyce gives a different result for the same intent.

