# Lumen Circuit Studio: Database Gap Analysis and Improvement Plan

Date: 2026-05-27  
Scope: `lumen/core/database.py` primitive catalog, schematic component availability, and parity direction vs QUCS + Virtuoso-class workflows.

## 1) Current Database Inventory

- Built-in primitives library: `primitives`
- Total primitive cells generated at startup: **148**
- QUCS-compatible tagged components: **99**
- Category distribution:
  - `native`: 49
  - `lumped components`: 15
  - `sources`: 16
  - `nonlinear components`: 19
  - `system components`: 8
  - `digital components`: 41

## 2) What Was Added for QUCS Coverage

To satisfy the immediate requirement, the database now includes QUCS-style component families beyond the existing analogLib-style set:

- Lumped additions:
  - `dc_block`, `dc_feed`, `bias_t`, `attenuator`, `isolator`, `circulator`, `phase_shifter`, `coupler_ideal`, `hybrid`, `voltage_probe`, `time_switch`, `relay`, `transformer_ideal`, `transformer_sym`, `mutual_ind_3`
- Sources additions:
  - `ac_power`, `am_vsource`, `pm_vsource`, `noise_vsource`, `noise_isource`, `pulse_vsingle`, `pulse_isingle`, `pulse_vrect`, `pulse_irect`, `pulse_vexp`, `pulse_iexp`, `file_vsource`, `file_isource`, `noise_corr`, `noise_corr_v`, `noise_corr_i`
- Nonlinear additions:
  - `diac`, `thyristor`, `triac`, `mos_depl`, `mos_bulk`, `hjt_sub`, plus compact-model placeholders (`fbh_hbt_va`, `hicum_*`, `mesfet_va`, `ekv26mos_va`, `opamp_mod_va`, `log_amp_va`, `pot_va`, `photodiode_va`, `phototransistor_va`)
- System additions:
  - `eqn_device`, `eqn_rf_device`, `eqn_rf_2port`, `sparam_file`, `spice_netlist`, `subckt_file`, `vhdl_file`, `verilog_file`
- Digital additions:
  - Core logic gates, FF/latch set, encoders/converters, mux/demux blocks, pattern generators, comparators, adders, A2D/D2A shifters, `digital_source`

## 3) Shortcomings (What Is Still Not Virtuoso-Class)

### A. Device Presence vs Device Fidelity
- Most new QUCS-compatible entries are currently **symbol + parameter schema stubs**.
- Netlisting/model semantics for many new components are not yet fully implemented in `netlist.py`.
- Compact-model devices (HICUM/FBH/EKV/MESFET Verilog-based variants) are not wired to full model loaders/corners yet.

### B. Incomplete Behavior Models
- Digital components are present in the library but not yet tied to a dedicated mixed-signal simulation backend.
- System/file components exist as symbols but need robust parser/import pipelines (Touchstone/SPICE/VHDL/Verilog).

### C. PDK/Library Semantics
- Need stronger CDF/parameter validation (types, units, legal ranges, dependencies).
- Need versioned library schema migrations for long-lived projects.

### D. Verification and Signoff Depth
- Device-level LVS/DRC decks and setup are not yet integrated end-to-end by technology.
- Multi-corner statistical signoff (MC/MMC) orchestration is still early.

### E. Virtuoso-Superset Workflow Gaps
- No complete config-view / hierarchy binding flow yet.
- No full ADE-XL equivalent for large campaign management and result DB comparisons.
- Limited batch API consistency for enterprise-scale regression and CI.

## 4) Plan to Become Better Than Virtuoso

## Phase 1: Functional Completion (Near-term)
1. Implement netlist emission handlers for every new QUCS-compatible primitive.
2. Add strict parameter typing/units and schema validation.
3. Add symbol QA checks (pins/orientation/default labels) and component-level tests.
4. Add import validation for `sparam_file`, `spice_netlist`, `vhdl_file`, `verilog_file`.

## Phase 2: Simulation and Data Infrastructure
1. Mixed-signal co-simulation path (analog + digital primitives).
2. Unified results database for corners/sweeps/expressions.
3. Deterministic run manifests for reproducibility (seed, model hash, deck hash).
4. Fast compare tools across runs/corners with tolerance and pass/fail rules.

## Phase 3: Virtuoso-Superset UX/Automation
1. ADE-XL style run plans with distributed execution.
2. Config-view/hierarchy manager with bind rules and variant control.
3. Full SKILL-like automation layer (Python-first) with compatibility wrappers.
4. Team collaboration: design review comments, run provenance, artifact sharing.

## Phase 4: Signoff and Foundry-Grade Readiness
1. PDK package signing, version locks, and reproducible install manifests.
2. DRC/LVS/PEX orchestration with result ingestion and waiver tracking.
3. Reliability/aging/Monte-Carlo campaign automation at scale.

## 5) Immediate Next Actions

1. Finish netlist support matrix for the newly added QUCS-compatible devices.
2. Add per-component test vectors (symbol -> netlist line expectations).
3. Add model/back-end capability flags so unsupported devices fail with actionable diagnostics.
4. Build a component browser filter by `qucs_category` and simulator capability.

## 6) Notes

- Expression editor/calculator improvements are intentionally deferred to a separate track.
- This document covers database/component readiness and the roadmap for simulation/signoff parity and beyond.

