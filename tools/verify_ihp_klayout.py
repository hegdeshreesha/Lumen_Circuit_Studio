"""KLayout-side smoke test for the IHP SG13G2 PCell runtime.

Run through KLayout (not CPython), for example ``klayout -b -r <this-file>``
with the same environment used by Lumen's KLayout launcher.
"""
import json
import os
from pathlib import Path

import pya


library = pya.Library.library_by_name("SG13_dev")
if library is None:
    raise RuntimeError("SG13_dev is not registered")

layout = pya.Layout()
top = layout.create_cell("LUMEN_PCELL_SMOKE_TEST")
checks = [
    ("nmos", {"w": "0.15u", "l": "0.13u", "ng": 1}),
    ("pmos", {"w": "0.15u", "l": "0.13u", "ng": 1}),
]
for index, (name, parameters) in enumerate(checks):
    declaration = library.layout().pcell_declaration(name)
    if declaration is None:
        raise RuntimeError(f"SG13_dev::{name} is not registered")
    variant = layout.add_pcell_variant(library, declaration.id(), parameters)
    instance = top.insert(pya.DCellInstArray(variant, pya.DTrans(index * 5.0, 0.0)))
    if instance is None or layout.cell(variant).bbox().empty():
        raise RuntimeError(f"SG13_dev::{name} produced no geometry")
    print(f"LUMEN_VERIFY_OK SG13_dev::{name} {parameters}")

print("LUMEN_VERIFY_OK Dummy1/Dummy2 physical device runtime ready")
stamp = os.environ.get("LUMEN_VERIFY_STAMP", "").strip()
if stamp:
    Path(stamp).write_text(
        json.dumps(
            {
                "success": True,
                "library": "SG13_dev",
                "pcells": [name for name, _parameters in checks],
                "parameters": checks[0][1],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
