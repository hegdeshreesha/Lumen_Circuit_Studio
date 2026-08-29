# Lumen PDK Manifest

`lumen_pdk.json` is the local manifest Lumen writes or reads at a PDK root.
It is intentionally small: the manifest names the PDK and points Lumen at the
folder structure; model files, `.LIB` sections, and many devices can still be
discovered from disk during refresh.

## Install Flow

1. Put the PDK on disk, or use **PDK Manager > Install Open PDK...**.
2. Use **PDK Manager > Register Folder...** if the PDK already exists locally.
3. Use **Refresh Install** or **Health > Rescan** after changing model files.
4. In **Library Manager**, right-click the design library and choose
   **Attach PDK...**.
5. New SimENV sessions opened from that library inherit the attached PDK and
   auto-load discovered model/corner setup when no saved SimENV view exists.

## Minimal Manifest

```json
{
  "schema_version": "1.0",
  "name": "demo_pdk",
  "display_name": "Demo PDK",
  "foundry": "Demo Foundry",
  "process": "CMOS",
  "node": "130nm",
  "version": "1.0",
  "description": "Local demo PDK",
  "paths": {
    "models": "models",
    "tech": "tech",
    "cells": "cells",
    "symbols": "symbols"
  },
  "corners": [
    {
      "name": "tt",
      "description": "Typical",
      "temperature": 25,
      "voltage": 1.8,
      "lib_section": "tt"
    }
  ]
}
```

## Optional Devices

Devices can be supplied explicitly when filesystem discovery is not enough.

```json
{
  "devices": [
    {
      "name": "nmos_1v8",
      "category": "MOSFET",
      "prefix": "M",
      "model": "nmos_1v8",
      "component_name": "nmos_1v8",
      "term_order": ["D", "G", "S", "B"],
      "inst_parameters": ["w", "l", "m"],
      "netlist_kind": "primitive",
      "pins": [
        {"name": "D", "direction": "inout"},
        {"name": "G", "direction": "input"},
        {"name": "S", "direction": "inout"},
        {"name": "B", "direction": "inout"}
      ],
      "parameters": [
        {"name": "w", "type": "float", "default": "1u"},
        {"name": "l", "type": "float", "default": "130n"},
        {"name": "m", "type": "int", "default": "1"}
      ]
    }
  ]
}
```

## Discovery Rules

Lumen looks for `pdk.json` first, then `lumen_pdk.json`.

If no manifest exists, registering a folder still works when model files are
found. Lumen scans common SPICE file extensions such as `.lib`, `.model`,
`.spice`, `.sp`, `.va`, and `.gsdi`, then writes a generated
`lumen_pdk.json`.

For model corners, `.LIB <section>` names are discovered and mapped into
SimENV corner sections. If the manifest has explicit `corners`, those names are
preserved and refreshed model files are mapped to them by section/name.

## Current Limits

The generic path supports model/corner setup and explicit device catalogs. Full
PDK-quality layout rules, parameter callbacks, and advanced symbol generation
still need per-PDK adapters.
