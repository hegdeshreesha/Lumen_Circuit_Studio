# Third-Party Notices

Lumen Circuit Studio source code is licensed under Apache-2.0 unless a file or
subtree says otherwise.

## Runtime Dependencies

- PySide6 / Qt for Python: LGPL/commercial license. Preserve the applicable Qt
  notices and dynamic-linking/relinking rights when distributing binary bundles.
- jsonschema: MIT license.
- NumPy: BSD-style license.
- pytest: MIT license, test dependency only.

## Bundled Or Referenced EDA Content

- IHP Open Source PDK under `external/ihp_pdk`: Apache-2.0 overall, with
  subcomponents carrying their own notices. Preserve the upstream LICENSE files
  when redistributing this subtree.
- IHP `libs.tech/verilog-a/r3_cmc`: Educational Community License 2.0.
- IHP `libs.tech/klayout/python/pycell4klayout-api`: GPL-3.0. Keep this as
  third-party PDK/KLayout helper content and preserve its license when
  redistributed.
- IHP `libs.tech/klayout/python/pypreprocessor`: license as provided in its
  upstream LICENSE file.
- xschem_sky130 under `external/xschem_sky130`: Apache-2.0 overall, with
  subdirectories carrying their own notices.

## External Tools

Lumen can interoperate with external tools such as KLayout, ngspice, Xyce,
Magic, OpenROAD, and related PDK toolchains. Those tools are not relicensed by
Lumen; follow each upstream project's license when installing or redistributing
them.
