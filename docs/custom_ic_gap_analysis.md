# Lumen Circuit Studio: Custom-IC-Class Gap Analysis

This document is a working map for turning Lumen Circuit Studio from a promising
prototype into a competitive custom IC design environment. Layout integration is
intentionally deferred; the focus here is PDK management, ADE, schematic capture,
hierarchy, and symbol generation.

## Current Snapshot

The repository already has useful foundations:

- A file-based library/cell/view database in `lumen/core/database.py`.
- Schematic editing on a `QGraphicsView` canvas with instances, wires, labels,
  selection, undo/redo, rotate/mirror, copy/paste, and netlist generation.
- A newer explicit connectivity engine in `lumen/core/connectivity.py`.
- An ADE core and ADE GUI with analyses, corners, sweeps, outputs, run history,
  convergence helpers, and simulator bridge plumbing.
- PDK discovery/catalog work in both `lumen/core/pdk_schema.py` and
  `lumen/pdk/registry.py`.
- A symbol generator and an interactive symbol editor.

The main problem is not ambition. The problem is that these pieces are not yet a
single reliable design platform.

## Blocking Shortcomings

1. The repo had a syntax error in `lumen/pdk/symbols.py`, which prevented clean
   module compilation. This has been fixed.
2. `HierarchyEngine` called `LibraryDatabase.view_exists`, but the database did
   not implement it. This has been fixed by adding `view_exists` and
   `cell_exists`.
3. Symbol editing existed but was not properly routed from the app shell. Opening
   a symbol through the CIW/library flow now uses a real `SymbolEditorWindow`.
4. `lumen/pdk/pdk.yaml` is not a valid manifest. It mixes YAML documents, sample
   values, and an invalid `g Hash:` line. It should not be treated as an
   authoritative PDK schema.
5. There are duplicated PDK systems: `lumen/core/pdk.py`,
   `lumen/core/pdk_schema.py`, and `lumen/pdk/registry.py`. They overlap but do
   not share one canonical data model.
6. There are no tests in `tests/`, so behavior can regress silently.

## PDK Management Gaps

custom IC editor is strong because the PDK is not just a list of devices. Lumen currently
has catalog discovery and model parsing, but lacks a complete PDK contract.

Missing or weak:

- One canonical PDK manifest format with schema validation and migration.
- A technology binding between user libraries and one or more PDKs.
- Device parameter constraints that are enforced in the property editor.
- Model file/corner resolution that is deterministic and simulator-specific.
- CDF-like device metadata: display fields, callbacks, pin order, netlisting
  procedure, defaults, units, allowed ranges, and derived parameters.
- Version pinning and project reproducibility. A design should record exactly
  which PDK version and model files were used.
- PDK import adapters for Xschem, KLayout, OpenPDK/Sky130, IHP, GF180, and custom
  vendor bundles.
- Audit tooling: missing models, broken symbols, duplicate device names, bad pin
  order, invalid corners, stale generated symbols.

Competitive target:

- Treat PDKs as installable, validated packages with a lockfile.
- Provide a PDK dashboard that reports health, coverage, model/corner mapping,
  symbol coverage, and netlisting readiness.
- Make symbols and CDF metadata generated but editable, with clear provenance.

## ADE Gaps

The ADE code is ambitious, but it is not yet production-grade in behavior.

Missing or weak:

- Simulation setups are not clearly tied to a project/library/cell lifecycle.
- Corners and sweeps exist as data structures, but result organization and UI
  exploration need hardening.
- Output expressions use a limited calculator and need safer parsing, units, and
  waveform-family semantics.
- No spec/assertion system for pass/fail design goals.
- No job manager for queued, parallel, cancellable multi-corner sweeps.
- No robust result database with provenance: netlist hash, PDK hash, simulator
  version, corner, variables, timestamp, and logs.
- Limited simulator abstraction. Advanced analyses listed for GSPICE/PSS/HB need
  capability checks and graceful degradation per backend.
- Waveform viewer is basic: no buses, eye diagrams, measurements browser,
  cursors table, calculator integration, or linked ADE outputs.

Competitive target:

- ADE should be experiment-centric: each run is reproducible, comparable, and
  queryable.
- Add specs, corners, sweeps, Monte Carlo, output expressions, and run history as
  first-class project objects.
- Provide "why did this fail?" diagnostics: missing supply, floating nodes,
  singular matrix hints, model include mistakes, unsupported analysis, and bad
  parameter values.

## Schematic Capture Gaps

The editor is usable but still far from professional schematic capture.

Missing or weak:

- No formal design rule check/check-and-save pipeline.
- Pins/ports are not first-class in schematic save data.
- Connectivity around labels, junction dots, crossings, and pin attachment needs
  tests and UI feedback.
- Moving multiple items uses one delta, which can be wrong for diverse selections.
- Property edits update instance parameters directly and may bypass undo/redo.
- Rotation/mirroring are not persisted in saved instance data.
- No instance rename flow, name uniqueness enforcement, or refdes allocator.
- No wire stretch, bus wires, bus taps, inherited connections, global nets policy,
  or net highlighting.
- No annotations for warnings/errors directly on the canvas.
- No schematic compare/diff or batch validation.

Competitive target:

- The schematic editor should feel more deterministic than custom IC editor: instant
  connectivity highlighting, explicit net conflict markers, robust undoable
  property edits, and a validation panel that explains every issue.

## Hierarchy Gaps

The hierarchy engine can build a tree, but hierarchy editing is not yet a real
workflow.

Missing or weak:

- No dedicated hierarchy browser/editor UI.
- No config views or switch/stop view lists.
- No library mapping rules for resolving symbols to schematics, native compact-model source,
  extracted views, or simulator views.
- Cycle detection only uses a visited set, which can hide repeated legitimate
  instances of the same cell.
- Parameter propagation is approximate and currently merges all child instance
  parameters together at a node.
- Cross-probing has a skeleton, but navigation state and selection linkage are
  incomplete.

Competitive target:

- Add a hierarchy/config manager that lets users choose per-instance views,
  inspect unresolved references, descend/edit in context, and generate either
  flat or hierarchical netlists predictably.

## Symbol Generation Gaps

The symbol generator is a good start for primitive devices.

Missing or weak:

- Generated symbols do not yet preserve provenance or round-trip cleanly after
  user edits.
- Pin locations are template-based but not validated against PDK pin order.
- Symbol editor cannot serialize arbitrary paths/polygons/arcs back to shapes in
  all cases.
- No automatic symbol generation from schematic ports beyond a simple UI button.
- No symbol quality checks: duplicate pins, off-grid pins, missing labels, bad
  directions, unconnected inherited pins.

Competitive target:

- Generate symbols from schematic interfaces, PDK device metadata, or native compact-model source
  modules; validate pin order and netlisting metadata; allow user edits without
  losing generated intent.

## Architecture Risks

- The codebase has three PDK abstractions. Consolidation is urgent.
- File-based JSON is good for now, but schemas and migrations are needed before
  designs become durable.
- GUI code and design logic are tightly coupled in places. Core behavior needs
  headless tests.
- There is no plugin/API boundary for PDK adapters, simulators, calculators,
  checks, or generators.
- Mojibake in comments/docs suggests encoding mishandling. All source should be
  normalized to UTF-8 or rewritten as ASCII comments.

## Recommended Build Order

1. Stabilize the core: compile, add smoke tests, define JSON schemas, and make
   library/cell/view APIs complete.
2. Consolidate PDK management into one canonical registry and manifest.
3. Make schematic save/check/netlist deterministic with tested connectivity.
4. Build the hierarchy/config editor and resolve view selection rules.
5. Upgrade symbol generation and symbol editing round-trip behavior.
6. Harden ADE run management, result storage, expressions, specs, corners, and
   sweeps.
7. Add import/export bridges and compatibility tests against known open-source
   PDK examples.

## Near-Term Implementation Milestones

- M1: Core health
  - `python -m compileall lumen` passes.
  - Add unit tests for database, symbols, connectivity, hierarchy, and netlist.
  - Add schema version fields and validation for schematic/symbol/sim files.

- M2: PDK package contract
  - Replace `lumen/pdk/pdk.yaml` with a valid manifest schema.
  - Merge duplicate PDK dataclasses or provide adapters to one canonical model.
  - Add PDK health checks and deterministic model/corner selection.

- M3: production-grade schematic loop
  - Save rotation/mirror, ports, and property changes correctly.
  - Add check-and-save errors for floating pins, duplicate names, missing symbols,
    bad pin order, and net conflicts.
  - Add tests using small resistor divider, inverter, and hierarchical amplifier
    examples.

- M4: ADE beta
  - Persist ADE sessions with run records and provenance.
  - Implement specs and pass/fail summaries.
  - Add result browser and waveform/output linking.

The product goal should not be "clone custom IC editor." The sharper goal is: make the
custom IC loop more transparent, reproducible, scriptable, and debuggable than
custom IC editor while keeping familiar library/cell/view workflows.

