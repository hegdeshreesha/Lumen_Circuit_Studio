# Lumen Circuit Studio - Project Plan

## Vision
Build a next-generation EDA tool that surpasses commercial custom IC platforms in every aspect:
- Modern, Python-based architecture
- Schema-driven data integrity
- Package manager-style PDK management
- Fully scriptable and automatable
- Open standards, no proprietary lock-in

## Current State Analysis

### Existing Components (LumenCircuitStudio/)
- ✅ Core database (LibraryDatabase) - file-based JSON storage
- ✅ Connectivity engine for netlist extraction
- ✅ Basic symbol generation
- ✅ Xschem parser/adapter
- ✅ Test suite (11 tests, all passing after stabilization)

### Critical Shortcomings (Now Fixed)
1. ❌ Incomplete core API → ✅ Added missing methods (cell_exists, view_exists)
2. ❌ Three divergent PDK systems → ✅ Unified into single system (pdk_unified.py)
3. ❌ No data validation → ✅ JSON Schema validation integrated
4. ❌ Fragile tests → ✅ All 11 tests passing

## Completed: Phase 1 - Core Stabilization

### 1. Unified PDK Management System
**File:** `lumen/core/pdk_unified.py`

Features that **surpass device-parameter metadata/technlib**:
- JSON Schema validation for PDK manifests
- Automatic device discovery from SPICE model files (.MODEL, .SUBCKT)
- Version pinning & lockfiles for reproducibility
- Multi-PDK support with active selection
- Health monitoring & audit trail
- Constraint metadata for property editor
- Built-in support for SkyWater 130nm, IHP SG13G2, GF180MCU

### 2. JSON Schema Validation
**Files:** `schemas/` directory
- `schematic.json` - Schematic view validation
- `symbol.json` - Symbol view validation
- `pdk_manifest.json` - PDK manifest validation

**Integration:** `lumen/core/validation.py` + `lumen/core/database.py`
- All data saved to database is validated
- Fail-fast with clear error messages

### 3. Core API Completion
Added to `LibraryDatabase`:
- `cell_exists(library, cell)` - Check cell existence
- `view_exists(library, cell, view)` - Check view existence

### 4. Test Suite
**All 11 tests passing:**
- `tests/test_database.py` - 8 tests (library, cell, view operations)
- `tests/test_core_smoke.py` - 3 tests (connectivity, symbols, database)

## Architecture: Superior to custom IC editor

### Key Differentiators

| Feature | commercial custom IC platforms | Lumen Circuit Studio |
|---------|-----------------|---------------------|
| **Data Format** | Proprietary binary (commercial design database) | Open JSON with schemas |
| **Validation** | Post-hoc, error-prone | Runtime schema validation |
| **PDK Management** | CDF/technlib, monolithic | Schema-driven, modular, versioned |
| **Scripting** | SKILL (LISP-like) | Python (modern, typed) |
| **Reproducibility** | Manual tracking | Automatic lockfiles |
| **Extensibility** | Closed APIs | Open, testable modules |
| **Multi-PDK** | Complex setup | Native support |
| **Health Monitoring** | Limited | Comprehensive audit trail |

### System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Lumen Circuit Studio                    │
├─────────────────────────────────────────────────────────────┤
│  UI Layer (Qt6)                                            │
│  ├─ Schematic Editor                                       │
│  ├─ Hierarchy Browser                                      │
│  ├─ Property Editor (with PDK constraints)                │
│  ├─ Waveform Viewer                                        │
│  └─ Simulation Cockpit                                    │
├─────────────────────────────────────────────────────────────┤
│  Core Engine                                              │
│  ├─ LibraryDatabase (JSON file hierarchy)                 │
│  ├─ ConnectivityEngine (netlist extraction)              │
│  ├─ PDKRegistry (unified device management)              │
│  ├─ SchemaValidator (data integrity)                     │
│  └─ SymbolGenerator (auto from PDK)                      │
├─────────────────────────────────────────────────────────────┤
│  Backends                                                │
│  ├─ SPICE Netlist Generator                              │
│  ├─ NGSPICE/Xyce/simulator adapters                         │
│  ├─ KLayout (layout future)                              │
│  └─ Xschem importer                                      │
├─────────────────────────────────────────────────────────────┤
│  PDK Layer                                               │
│  ├─ sky130 (built-in)                                    │
│  ├─ ihp_sg13g2 (built-in)                               │
│  ├─ gf180mcu (built-in)                                 │
│  └─ Custom PDKs (user-installed)                        │
└─────────────────────────────────────────────────────────────┘
```

## Implementation Roadmap

### ✅ Phase 1: Core Stabilization (COMPLETE)
- [x] Fix missing database methods
- [x] Unify PDK systems
- [x] Add JSON schema validation
- [x] Ensure all tests pass (11/11)

### Phase 2: Simulation Cockpit Foundation (2-3 weeks)
**Goal:** Analog Design Environment with simulation support

Components:
1. **Simulation Configuration Model**
   - Multi-corner, multi-mode analysis
   - Parameter sweeps (Monte Carlo, parametric)
   - Testbench templates

2. **Netlist Backend Abstraction**
   - Interface for multiple simulators
   - NGSPICE backend (first implementation)
   - Model file resolution with corners

3. **Results Database**
   - Store simulation results
   - Waveform data management
   - Result caching

4. **Waveform Viewer Prototype**
   - Basic plot display
   - Signal navigation
   - Measurement cursors

### Phase 3: Schematic Capture (3-4 weeks)
**Goal:** Full-featured schematic editor

Components:
1. **Qt Canvas Widget**
   - High-performance rendering (QGraphicsView)
   - Zoom/pan with mouse wheel
   - Grid snapping
   - Selection rectangle

2. **Placement Engine**
   - Device placement from PDK catalog
   - Drag & drop
   - Alignment guides
   - Off-grid placement with snap

3. **Wire Routing**
   - Auto-completion (Manhattan routing)
   - Bus/vector support
   - Net name propagation
   - Real-time connectivity checking

4. **Property Editor**
   - PDK constraint validation
   - Parameter editing with units
   - Multi-instance editing
   - Undo/redo integration

5. **Hierarchy Navigation**
   - Push into hierarchy
   - Pop to parent
   - Cross-probing with waveform viewer

### Phase 4: Hierarchy & Symbol Tools (2 weeks)
**Goal:** Manage complex hierarchies and symbols

Components:
1. **Hierarchy Browser**
   - Tree view with instant search
   - Drag-and-drop re-parenting
   - In-place renaming
   - Cell instance flattening preview
   - Version comparison

2. **Symbol Generator**
   - Auto-generate from PDK device definition
   - Multiple symbol styles (ANSI, IEC, custom)
   - Pin positioning with auto-routing
   - Multi-page symbols
   - Export to PDF/SVG/PNG

3. **Batch Symbol Generation**
   - Generate symbols for entire PDK
   - Custom templates
   - Symbol library management

### Phase 5: Integration & Polish (2-3 weeks)
**Goal:** Production-ready application

Components:
1. **Project Management**
   - Create/open/save projects
   - Project file format (JSON)
   - Recent projects list
   - Auto-save/recovery

2. **Preferences System**
   - Theme selection (dark/light)
   - Grid settings
   - Simulation defaults
   - PDK management UI

3. **Full UI Integration**
   - Main window with docking
   - Menu bar & toolbars
   - Keyboard shortcuts
   - Status bar

4. **Documentation**
   - User guide
   - API documentation (Sphinx)
   - Tutorial videos
   - PDK authoring guide

5. **Testing & QA**
   - Integration tests
   - Performance benchmarks
   - Memory leak testing
   - Cross-platform validation

## Technical Specifications

### Technology Stack
- **Language:** Python 3.14+
- **UI Framework:** Qt6 (PySide6)
- **Data:** JSON with JSON Schema
- **Simulation:** NGSPICE (primary), Xyce, simulator compatibility
- **Layout (Phase 2):** KLayout integration
- **Testing:** pytest, unittest
- **Packaging:** PyInstaller for distribution

### File Formats
- **Design Data:** `cell.lumen.json` (schematic, symbol, layout)
- **Library Registry:** `lumen_libs.json`
- **PDK Manifest:** `pdk.json` (canonical format)
- **Lockfile:** `project.pdk.lock` (reproducibility)
- **Project:** `project.lumen.json`

### Performance Targets
- Schematic open: < 100ms for 1000-instance design
- Wire routing: Real-time (ms for typical connections)
- Simulation startup: < 2s
- Memory: < 500MB for 10k instance design

## Success Metrics

### Phase 1 Complete ✅
- [x] All existing tests pass (11/11)
- [x] Core API stable and documented
- [x] PDK system unified and validated
- [x] Schema validation integrated

### Phase 2 Success
- [ ] Simulation Cockpit can configure and run NGSPICE simulation
- [ ] Waveform viewer displays results
- [ ] Parameter sweep executes correctly
- [ ] Results caching reduces repeat runs by 10x

### Phase 3 Success
- [ ] Can create 1000-instance schematic without lag
- [ ] Wire routing completes in < 50ms
- [ ] Property editor validates against PDK constraints
- [ ] Undo/redo preserves 1000 operations

### Phase 4 Success
- [ ] Hierarchy browser handles 1000+ cells
- [ ] Symbol generation produces production-quality symbols
- [ ] Batch generation processes 500 devices in < 1 min

### Phase 5 Success
- [ ] End-to-end workflow: schematic → simulation → results
- [ ] Project save/load completes in < 2s
- [ ] No memory leaks over 8-hour continuous use
- [ ] Documentation covers all features

## Competitive Advantages Over custom IC editor

1. **Open Architecture**
   - No proprietary binary formats
   - Full Python API access
   - Easy to integrate with modern tools

2. **Modern Development**
   - Git-friendly (JSON files)
   - CI/CD compatible
   - Automated testing
   - Type hints for IDE support

3. **PDK as Packages**
   - Versioned like npm/pip
   - Lockfiles for reproducibility
   - Health checks
   - Easy distribution

4. **Performance**
   - Incremental saves (only changed cells)
   - Lazy loading of cells
   - Parallel simulation
   - Smart caching

5. **Collaboration**
   - No database server needed
   - File-based works with any VCS
   - Lockfiles prevent conflicts
   - Easy branching/merging

6. **Cost**
   - Completely free (open source)
   - No license servers
   - No seat limitations
   - Runs on commodity hardware

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Performance with large designs | Implement lazy loading, caching, profiling from start |
| Incomplete PDK support | Provide conversion tools from existing PDKs |
| User adoption (learning curve) | Comprehensive documentation, tutorials, example designs |
| Simulator compatibility | Abstract backend, test with multiple simulators early |
| Layout integration complexity | Use KLayout as proven backend, focus on API |

## Next Steps

1. **Immediate:** Begin Phase 2 (Simulation Cockpit Foundation)
   - Design simulation configuration model
   - Implement netlist generator interface
   - Create NGSPACE backend
   - Build results database

2. **Week 1-2:** Complete Simulation Cockpit prototype
   - Simple circuit simulation end-to-end
   - Waveform display
   - Parameter sweep

3. **Week 3-4:** Integrate with schematic editor
   - Generate netlist from schematic
   - Run simulation
   - Display results with cross-probing

4. **Parallel:** Continue improving core
   - Add more unit tests (target 80% coverage)
   - Document APIs
   - Create example PDKs

## Conclusion

Lumen Circuit Studio is positioned to become the modern alternative to commercial custom IC platforms. With its schema-driven architecture, unified PDK management, and Python-based extensibility, it offers a compelling value proposition for both individual designers and teams.

The foundation is solid (Phase 1 complete). Now we build the Simulation Cockpit and schematic capture to deliver a working prototype that demonstrates the full workflow.

**Status:** Phase 1 ✅ COMPLETE | Phase 2 🚧 READY TO START
