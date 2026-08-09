# custom IC editor Functionality Matrix

This is the working parity checklist for making Lumen Circuit Studio behave like
a practical custom-IC environment. It is intentionally concrete: each row should
either map to working code, a known partial implementation, or a future module.

## Schematic Capture

| Area | commercial custom IC platforms Behavior | Lumen Status | Next Work |
| --- | --- | --- | --- |
| Open/edit/save cellviews | Library/cell/view database, check-and-save flow | Implemented for schematic/symbol new/open/save/save-as | Add copy/rename cellview manager |
| Wire drawing | Manhattan wires, snap grid, labels, junction-aware net extraction | Implemented for wires, bus-colored wires, names, taps | Add true vector expansion for bus taps |
| Instances | Place from library/PDK, edit params, move/delete/copy/paste | Implemented for user libraries and generated PDK symbols | Add richer CDF-driven forms |
| Orientation | Rotate/mirror visible instance and netlist with matching pin coordinates | Implemented for save/load and netlist connectivity | Add orientation labels like R0/MX/MY |
| Top-level pins | Pins are first-class ports used by symbols and netlisting | Implemented as industry-style terminal objects with direction, usage, orientation, marker, stub, and label | Add richer batch pin placement templates |
| Selection/edit | Select all, find/select, duplicate, stretch, object properties | Implemented for core objects | Add advanced filters and selection sets |
| Zoom/navigation | Fit, wheel zoom, right-drag zoom area, pan | Implemented | Add bindkeys/preferences panel |
| DRC/check-save | Detect missing pins, floating nets, bad refs | Implemented lightweight health check | Add full rule-deck schematic DRC/ERC |

## Symbol Editor

| Area | commercial custom IC platforms Behavior | Lumen Status | Next Work |
| --- | --- | --- | --- |
| Draw primitives | Lines, rectangles, circles, arcs, polygons, text | Implemented for creation/save/load of basic shapes and text | Add full Bezier/path editing |
| Pins | Pin placement with direction/order/orientation | Implemented with terminal marker, stub, direction, orientation, pin order, and selected pin property editor | Add side-assignment templates |
| Auto symbol | Generate symbol from schematic ports | Implemented from schematic pins/labels | Add layout templates and side assignment |
| Edit operations | Copy/paste/delete/select/rotate/mirror/properties/undo/redo | Implemented for symbol items with snapshot undo | Add granular command history |
| Health check | Find missing pins/shapes/netlist prefix | Implemented lightweight check | Add deeper CDF/model consistency checks |

## Simulation Cockpit

| Area | commercial custom IC platforms Behavior | Lumen Status | Next Work |
| --- | --- | --- | --- |
| Analysis setup | OP/DC/AC/tran/noise/corners/sweeps | Implemented for major analysis setup, variables, corners, sweeps, save/load | Add advanced analysis-specific validators |
| Netlist generation | PDK includes, CDF params, selected outputs | Implemented for core path, PDK model includes, outputs, measurements | Add output picker from schematic probes |
| Run simulation | Launch simulator, capture logs/results | Implemented GSPICE/ngspice-style bridge path | Add cancellation/progress streaming |
| Waveforms | Plot selected nodes and currents | Implemented basic viewer and Simulation Cockpit launch | Add calculator markers and measurement browser |

## Hierarchy And Config Views

| Area | commercial custom IC platforms Behavior | Lumen Status | Next Work |
| --- | --- | --- | --- |
| Descend/return | Navigate instance hierarchy | Implemented basic instance descend/return stack | Add in-place edit/read mode distinction |
| Config view | Choose schematic/symbol/veriloga/extracted per cell | Implemented as storable config cellview skeleton | Add full binding-rule GUI |
| Cross probing | Select in hierarchy and schematic together | Partial hierarchy engine plus quick probe | Add docked hierarchy tree cross-selection |

## PDK Management

| Area | commercial custom IC platforms Behavior | Lumen Status | Next Work |
| --- | --- | --- | --- |
| Model linkage | Symbols/CDF bind to model/subckt names and .lib sections | Implemented through PDK device metadata and model includes | Add model-section chooser per corner |
| Dynamic symbols | PDK devices appear without copying symbol files into user libs | Implemented via `pdk:<name>` libraries | Cache generated symbols for faster browsing |
| Parameter mapping | CDF maps GUI params to simulator params | Implemented basic symbol CDF metadata and PDK params | Add validation, units, defaults, limits |
| Corners | `.lib` / `.scs` sections selected by Simulation Cockpit | Implemented corner table and corner netlists | Add per-run manifest export |

## Lumen Improvements Beyond custom IC editor

| Area | Improvement | Status |
| --- | --- | --- |
| Native PDK registry | One registry can generate symbols and netlist metadata | Implemented basic flow |
| Design health checks | Fast, friendly checks surfaced in editor | Implemented lightweight checks |
| Modern zoom UX | Right-drag zoom window and clean fit behavior | Implemented |
| Open simulator bridge | GSPICE integration instead of closed simulator-only flow | Implemented basic bridge |
