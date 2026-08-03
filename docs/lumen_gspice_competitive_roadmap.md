# Lumen And GSPICE Competitive Roadmap

Date: 2026-07-14

Scope: Lumen Circuit Studio, SigView, SimENV/APW, PDK integration, simulator backends, and GSPICE. The goal is not to copy industry-standard feature-by-feature. The goal is to build a custom IC design platform that is reliable, transparent, automation-friendly, and eventually competitive with custom IC editor/ADE/Viva/signoff-class workflows.

## Product North Star

Lumen should become a complete analog/mixed-signal design environment where a designer can:

- Create and manage libraries, cells, and views.
- Draw schematics with deterministic connectivity and hierarchy.
- Bind designs to validated PDKs and simulator-specific model rules.
- Run the same design intent through GSPICE, Ngspice, or Xyce using backend-specific decks.
- Inspect, compare, and calculate waveforms in SigView.
- Run corners, sweeps, Monte Carlo, measurements, and regression campaigns.
- Trust results because every simulator run has a manifest, model provenance, validation status, and clear diagnostics.

GSPICE should become a serious open simulator backend for Lumen, but it must be honest at every stage. If GSPICE cannot simulate a deck accurately, it must fail loudly or mark the result as experimental. Silent fallback is forbidden.

## Core Principles

1. Correctness before feature count.
2. No silent fallbacks for active devices, compact models, or unsupported syntax.
3. Simulator-specific backend rules, not one universal netlist.
4. Reference validation against Ngspice and Xyce for every supported GSPICE capability.
5. Reproducibility by default: deck hash, model hash, simulator version, PDK version, run settings, and result files.
6. Fast feedback in the UI: progress, warnings, logs, diagnostics, and waveform availability must be visible.
7. Automation-first design: every GUI workflow should eventually have a stable Python/API equivalent.

## Current Baseline

### Lumen Strengths

- Library/cell/view database exists.
- Schematic editor, symbol editor, hierarchy navigation, SimENV, APW, and SigView foundations exist.
- Multi-simulator runtime plumbing exists for GSPICE, Ngspice, and Xyce.
- IHP SG13G2 device symbols and model libraries are partially integrated.
- External compact-model startup loading has been removed from the independent architecture.
- Xyce backend rules now route IHP model libraries to `libs.tech/xyce/models` and require the Xyce PSP plugin when needed.
- GSPICE RAW parsing in Lumen now handles GSPICE unindexed rows and Ngspice indexed/multi-plot RAW files.

### GSPICE Strengths

- Basic OP, DC, transient, AC-related infrastructure, behavioral sources, measurements, and some advanced analysis prototypes exist.
- native PSP-class plumbing has started.
- GSPICE emits model-status diagnostics.
- Transient progress and RAW output exist.
- It has a growing CTest/deck regression suite.

### Critical Reality

Lumen is becoming a usable cockpit. GSPICE is not yet a signoff-accurate signoff-simulator replacement. GSPICE must be treated as an actively developing simulator until validated against Ngspice/Xyce across a broad public regression suite.

## Architecture Target

```text
Lumen schematic / hierarchy / config
  -> canonical design intent
  -> backend rule engine
      -> GSPICE deck + GSPICE model setup
      -> Ngspice deck + Ngspice model setup
      -> Xyce deck + Xyce plugin/model setup
  -> simulator runner
  -> result database
  -> SigView + calculator + measurements
  -> comparison/regression reports
```

The backend rule engine is mandatory. IIC-OSIC uses this pattern implicitly: Ngspice uses Ngspice model libraries and native model loading; Xyce uses Xyce model libraries and `-plugin` compiled native compact-model source models. Lumen should make that explicit and visible.

## Phase 0: Stabilization Gate

Target: make existing features reliable enough that future work has a stable base.

### Lumen Work

- Fix all known waveform parsing issues.
- Ensure every run writes `input.sp`, `stdout.log`, `stderr.log`, `waveforms.raw`, and `run_manifest.json`.
- Add live progress heartbeat for quiet simulators.
- Ensure Stop Simulation kills the correct process and records cancellation.
- Make SimENV simulator selection persist reliably.
- Add a visible backend-rules summary before each run.
- Add clear errors for unsupported native compact models.

### GSPICE Work

- Keep GSPICE failing loudly for unsupported PDK/compact-model syntax.
- Keep primitive MOS fallback opt-in only for debug decks.
- Stabilize ASCII RAW output format and add parser compatibility tests in Lumen.
- Add tiny regression decks for RC, diode, inverter, PULSE, PWL, AC, and transient measurements.

### Acceptance Criteria

- The same inverter schematic runs in GSPICE and Ngspice with correctly named signals in SigView.
- Xyce either runs with the required plugin or fails before launch with an actionable message.
- No run can show a random waveform due to parser column shifts.
- Every failed simulation has a readable log and manifest.

## Phase 1: Backend Rule Engine And PDK Discipline

Target: make simulator selection behave like a real rule profile.

### Lumen Work

- Create a formal backend-rule registry:
  - `GSPICE`
  - `Ngspice`
  - `Xyce`
  - future: simulator-compatible export, simulator-compatible export
- For each backend define:
  - supported analyses
  - supported source syntax
  - model-library folder preference
  - native compact-model availability
  - required output directives
  - unsupported directives and rewrite policy
  - raw/result parser
- Add PDK model resolver:
  - IHP Ngspice path: `libs.tech/ngspice/models`
  - IHP Xyce path: `libs.tech/xyce/models`
  - native compact-model registry
  - Xyce plugin path: `libs.tech/xyce/plugins`
- Add PDK lockfile:
  - PDK name/version/hash
  - model-library hash
  - simulator plugin hash
  - symbol/CDF schema version

### GSPICE Work

- Define a GSPICE model-loading contract:
  - `native model directive`
  - `native model directive`
  - `GSPICE_MODEL_DIR`
  - supported compact-model ABI versions
- Emit model fidelity status for every active compact-model instance.
- Add a strict mode that refuses any unvalidated compact model.

### Acceptance Criteria

- Selecting Ngspice, Xyce, or GSPICE visibly changes the rule profile.
- A deck generated for Xyce never points to Ngspice IHP model folders.
- A deck generated for Ngspice never requires Xyce plugins.
- Lumen can explain exactly why a backend cannot run a selected design.

## Phase 2: Schematic And Hierarchy Reliability

Target: make schematic capture deterministic and professional.

### Lumen Work

- Implement full Check and Save:
  - floating pins
  - shorted outputs
  - missing bulk connections
  - duplicate instance names
  - off-grid pins/wires
  - invalid parameters
  - unsupported simulator-device combinations
- Make wire motion and instance motion strictly grid-snapped.
- Add first-class ports, globals, labels, buses, bus taps, and inherited connections.
- Add net highlighting and terminal-current selection:
  - voltage probe selection highlights nets
  - current probe selection marks terminals with circles
  - selections are saved into SimENV outputs
- Add hierarchy/config views:
  - descend into schematic/symbol/other view
  - switch/stop view lists
  - per-instance view binding
  - unresolved reference browser
- Add schematic regression tests:
  - symbol pin order
  - connectivity graph
  - net naming
  - generated netlist lines

### Acceptance Criteria

- A schematic cannot silently netlist with disconnected MOS bulk terminals.
- Moving objects never causes random off-grid displacement.
- Net names in schematic, netlist, simulator raw, and SigView are consistent.
- Hierarchical descend/edit-in-context works for schematic and symbol views.

## Phase 3: SimENV, SigView, And Calculator Integration

Target: reach ADE/Viva-style daily usability, then exceed it.

### SimENV Work

- Results tab should be the primary waveform launch point.
- Right-click signal/result actions:
  - plot
  - plot in new pane
  - send to calculator
  - mark as output
  - compare with previous run
  - export data
- Add output save controls:
  - selected voltages
  - selected branch currents
  - all node voltages
  - all device currents
  - save none except requested outputs
- Add simulation dump settings:
  - default project dump directory
  - per-cell dump override
  - run retention policy
  - latest-run pointer

### SigView Work

- Stable large-RAW loading with lazy/decimated rendering.
- Zoom/pan behavior like a serious waveform viewer:
  - mouse wheel zoom
  - right-drag zoom box
  - fit X/Y
  - stack/overlay
  - linked axes
- Cursors and markers:
  - A/B cursors
  - delta readout
  - slope
  - frequency/period
  - rise/fall delay
- Measurements browser:
  - min/max/avg/rms/pp
  - crossing time
  - propagation delay
  - setup/hold style expressions
- Calculator integration:
  - send waveform from SigView to calculator
  - send expression from calculator to SigView
  - save expressions as SimENV outputs
  - expression dependency tracking

### Acceptance Criteria

- After simulation, the user can right-click any result and plot it without manually browsing files.
- SigView opens a million-point raw file without freezing.
- Calculator expressions are reproducible and stored in the run manifest.

## Phase 4: GSPICE Correctness And Validation

Target: make GSPICE trustworthy on a defined subset before expanding scope.

### Device And Model Coverage

- Passives:
  - R, C, L, mutual inductance, transmission-line basics
- Sources:
  - DC, AC, PULSE, PWL, SIN, EXP, SFFM, noise sources
- Nonlinear primitives:
  - diode
  - BJT
  - JFET/MESFET first-pass
  - primitive MOS as educational/debug only
- Compact models:
  - PSP via native compact-model
  - BSIM family via native compact-model or native integration
  - HICUM via native compact-model
  - resistor/capacitor foundry compact models

### Solver Work

- Matrix scaling and condition diagnostics.
- Robust sparse direct solve with KLU when available.
- Better singular-matrix reporting:
  - floating node candidates
  - missing DC path
  - voltage-source loop hints
- Newton improvements:
  - device limiting
  - line search
  - source stepping
  - gmin stepping
  - pseudo-transient continuation
- Transient integration:
  - backward Euler
  - trapezoidal
  - Gear2/BDF2
  - adaptive LTE
  - breakpoints for sources/events
  - charge conservation checks

### Analysis Coverage

- Must be production-quality:
  - OP
  - DC
  - TRAN
  - AC
  - NOISE
- Must become reliable:
  - `.STEP`
  - corners
  - Monte Carlo
  - `.MEASURE`
  - `.TF`
  - `.SENS`
- Later advanced track:
  - exact pole-zero extraction
  - distortion
  - PSS
  - PAC
  - PNoise
  - harmonic balance
  - S-parameter/RF port analysis

### Validation Strategy

- For every supported deck, run:
  - GSPICE
  - Ngspice
  - Xyce when supported
- Compare:
  - DC operating points
  - transient sampled waveforms
  - crossing times
  - min/max
  - AC magnitude/phase
  - noise integrated values
- Store tolerances per deck and per signal.
- Every bug fix should add a golden regression deck.

### Acceptance Criteria

- GSPICE has a published support matrix.
- Each green feature has a passing reference comparison.
- Each yellow feature is marked experimental in Lumen.
- Each red feature is blocked in Lumen with a clear message.

## Phase 5: ADE-XL-Class Campaigns

Target: make Lumen useful for real design exploration.

### Lumen Work

- Run plans:
  - corners
  - sweeps
  - nested sweeps
  - Monte Carlo
  - operating conditions
  - parameter sets
- Job manager:
  - queue
  - pause/resume
  - cancel
  - parallel local runs
  - future remote workers
- Result database:
  - run manifest
  - deck/model hashes
  - output vectors
  - measurement table
  - pass/fail specs
  - run comparison
- Spec system:
  - min/max specs
  - yield specs
  - assertions
  - failure triage

### Acceptance Criteria

- A user can run a corner/sweep plan and see a table of specs with pass/fail.
- Runs are reproducible from a manifest.
- Failed runs link directly to logs, deck, model setup, and schematic warnings.

## Phase 6: Layout And Signoff Integration

Layout is deferred for current work, but it must be planned.

### Lumen Work

- KLayout integration:
  - open layout view
  - layer map
  - DRC launch
  - result markers
- LVS:
  - schematic netlist
  - layout-extracted netlist
  - mismatch browser
- PEX:
  - extracted view
  - parasitic netlist
  - back-annotation into SimENV
- Reliability:
  - EM/IR hooks
  - device operating-point checks
  - voltage-domain checks
  - latch-up/ERC style checks

### Acceptance Criteria

- Lumen can run DRC/LVS/PEX for at least one open PDK flow.
- Extracted simulations are handled as another view choice in hierarchy/config.

## Phase 7: Better-Than-industry-standard Differentiators

industry-standard is powerful, but Lumen can win in transparency and automation.

### Differentiators

- Explainable simulator diagnostics:
  - why singular matrix happened
  - which node floats
  - which model is missing
  - which device is unsupported
- Built-in cross-simulator validation:
  - one click compare GSPICE vs Ngspice vs Xyce
  - tolerance-aware waveform reports
- Reproducible open run artifacts:
  - no hidden result database
  - every run is a folder with manifest, deck, logs, raw, and hashes
- Python-first automation:
  - script every GUI action
  - stable API for CI/regression
- PDK health dashboard:
  - symbol coverage
  - model coverage
  - simulator backend readiness
  - unsupported compact-model checks
- AI-assisted debug:
  - summarize failed runs
  - identify likely schematic mistakes
  - propose model/setup fixes
  - explain waveform anomalies

## Milestone Plan

### v0.6: Reliable Simulation Plumbing

- Backend rule registry.
- Ngspice/Xyce/GSPICE run manifests.
- Correct RAW parsing for all current backends.
- SigView result launch from SimENV Results tab.
- Stop simulation and heartbeat progress.

### v0.7: Schematic Reliability

- Check and Save.
- Floating terminal warnings.
- Grid-safe movement.
- Net/terminal probing saved to SimENV.
- Hierarchy descend and config basics.

### v0.8: SigView And Calculator

- Right-click plot from Results.
- Calculator waveform send/receive.
- Cursors, measurements, stacked/overlay panes.
- Large waveform decimation.

### v0.9: Reference Validation

- Automatic Ngspice/Xyce reference runs.
- Tolerance reports.
- GSPICE support matrix.
- Regression dashboard.

### v1.0: Open Analog Design Flow

- Stable schematic, hierarchy, SimENV, SigView, and multi-simulator flow.
- IHP SG13G2 baseline supported.
- Ngspice and Xyce backend rules functional.
- GSPICE validated on a published subset.
- Documentation for install, PDK setup, simulator setup, and first design.

### v2.0: Signoff-Oriented Flow

- Layout/LVS/PEX integration.
- ADE-XL-class campaigns.
- Production result database.
- Broader PDK support.
- Stronger GSPICE compact-model validation.

## Risk Register

| Risk | Impact | Mitigation |
| --- | --- | --- |
| GSPICE produces plausible but wrong results | Very high | Reference comparison, no silent fallback, experimental labels |
| Xyce plugin unavailable on Windows | High | Detect early, document build/install path, allow Ngspice fallback |
| Large RAW files freeze SigView | High | Lazy loading, decimation, background parsing |
| PDK metadata inconsistency | High | PDK lockfile and health dashboard |
| Feature count outruns testing | Very high | Every feature requires regression tests |
| Simulator dialect drift | Medium | Backend-rule registry with tests |

## Non-Negotiable Policies

1. Never silently ignore an active device.
2. Never silently replace a foundry model with a primitive model.
3. Never show a waveform unless the parser knows which signal column is which.
4. Never run Xyce with Ngspice model libraries.
5. Never run unsupported PSP-class decks through primitive fallback.
6. Every simulator run must be reproducible from its manifest.
7. Every GSPICE green feature must have reference validation.

## Immediate Next Actions

1. Move the current ad hoc backend rewrites into a formal backend-rule registry.
2. Add a SimENV panel that shows active backend rules before a run.
3. Build an IHP simulator readiness checker:
   - Ngspice executable
   - native compact-model availability
   - Xyce executable
   - Xyce PSP plugin
   - GSPICE native model registry
4. Add reference comparison for the inverter deck:
   - GSPICE vs Ngspice
   - Xyce when plugin is available
5. Add SigView large-waveform decimation.
6. Add GSPICE golden regression decks for the latest inverter and RC-step cases.

