# IHP SG13G2 KLayout Integration

Lumen uses the KLayout technology, PyCells, menus, DRC, and LVS shipped by the
bundled IHP Open PDK.  No PDK files need to be copied into a global KLayout
installation.

## One-time setup

1. Initialize the PDK and its nested KLayout PyCell dependencies.  A recursive
   clone already does this.  For an existing checkout, run from the repository
   root:

   ```powershell
   git submodule update --init external/ihp_pdk
   git -C external/ihp_pdk submodule update --init `
     ihp-sg13g2/libs.tech/klayout/python/pycell4klayout-api `
     ihp-sg13g2/libs.tech/klayout/python/pypreprocessor
   ```

   These two nested dependencies are mandatory.  Without them the layers load,
   but the `SG13_dev` PCell library does not register.

2. In Lumen, choose **Layout > KLayout Runtime...** once and select
   `klayout_app.exe` if it was not found automatically.  KLayout 0.30.2 or
   newer is required by the current IHP GUI LVS macro.

3. Optional, but recommended for an IIC-OSIC/Cadence-like editing workflow:
   open KLayout's **Tools > Manage Packages**, install the
   `KLayoutProductivitySuite` meta-package, and restart KLayout.  It installs
   the IIC align, move, pin, layer-shortcut, library-manager, backup, and
   netlist-import plugins.

## Starting KLayout

The simplest route is **Layout > Open Layout (KLayout)** in Lumen.  It launches
edit mode with the `sg13g2` technology, SG13G2 layers, PCells, and PDK menus.

For a standalone Windows session, from the repository root run:

```powershell
.\tools\start_ihp_klayout.ps1
```

Open an existing stream with:

```powershell
.\tools\start_ihp_klayout.ps1 -Layout .\workspace\layout\work\inv.gds
```

The equivalent command is `klayout -e -n sg13g2 <layout.gds>`, but use the
launcher unless you have already set the environment below.  `-e` is important:
it enables editor mode rather than read-only viewer mode.

## Cadence Layout Editor style workspace

After launch, arrange these panels once; KLayout persists the arrangement in
the workspace-local `.klayout` profile:

1. Enable **View > Panels > Layers**, **Cells**, **Libraries**, and **Navigator**.
2. Dock Layers and Libraries on the left, Cells/Navigator on the right, and keep
   the large canvas in the center.  This is the closest KLayout equivalent of
   Virtuoso's LSW/library browser/layout canvas.
3. In the Libraries panel expand **SG13_dev**.  Insert a device from there, or
   press **Insert**, select library `SG13_dev`, then choose `nmos`, `pmos`,
   `cmim`, `rppd`, `npn13G2`, and so on.  Press **F3** to edit the selected
   PCell parameters.
4. With the IIC Productivity Suite installed, enable
   **Tools > Layer Shortcut Plugin**.  For SG13G2, `1` through `7` focus the
   corresponding metal/via group, `8` focuses gate poly, `9` diffusion, `0`
   restores default layers, and Shift+number extends the visible group.
5. Use the IIC **Pin**, **Align**, and **Move Quickly** tools for a more
   Virtuoso-like interactive editing flow.  Enable automatic backups from
   **File > Automatic Backups**.

Expected checks after startup:

- the title/technology selector shows `sg13g2`;
- the layer list contains `Activ`, `GatPoly`, `Metal1` ... `TopMetal2`;
- the Libraries panel contains `SG13_dev` PCells;
- the menu contains **SG13G2 PDK** with DRC, LVS, options, filler, and netlist
  import commands.

If layers appear but `SG13_dev` does not, close KLayout and repeat the nested
submodule command in **One-time setup**.  Lumen's runtime summary now reports
this as `pcells_available: false` and lists the missing files.

## Device correspondence

Lumen reads the PDK's own
`python/import_netlist/ihp130_pcell_templates.py` file at runtime.  The mapping
therefore follows the installed PDK revision instead of a second hand-written
parameter table.  The principal mappings are:

| Schematic symbol/model | KLayout PCell |
| --- | --- |
| `sg13_lv_nmos`, `sg13_lv_pmos` | `SG13_dev::nmos`, `SG13_dev::pmos` |
| `sg13_hv_nmos`, `sg13_hv_pmos` | `SG13_dev::nmosHV`, `SG13_dev::pmosHV` |
| LV/HV RF MOS symbols | `rfnmos`, `rfpmos`, `rfnmosHV`, `rfpmosHV` with `rfmode=1` |
| `cap_cmim`, `cap_rfcmim` | `cmim`, `rfcmim` |
| `rsil`, `rppd`, `rhigh` | same-named PCells |
| `npn13G2`, `npn13G2l`, `npn13G2v` | `npn13G2`, `npn13G2L`, `npn13G2V` |

The built-in Lumen IHP symbols now use the official Xschem/PCell parameters and
terminal topology: RF MOS symbols netlist the base MOS model plus `rfmode=1`,
MIM capacitors use physical `w/l[/m]`, RF MIM includes its `bn` terminal, and
HBTs include substrate terminal `S` plus `Nx[/El]`.

**Layout > Import From Source Into KLayout** saves the schematic, writes two
handoff artifacts, starts KLayout, and directly instantiates the resolved
PCell variants:

- `<cell>.layout.cdl`, the schematic netlist for KLayout import/LVS;
- `<cell>.pcell-plan.json`, each resolved `SG13_dev` PCell, normalized
  parameters, multiplicity, and any non-layout instances that were skipped.

Each imported layout instance carries its Lumen schematic instance name. With
**Layout > Device Highlight Sync** enabled, selecting a device in the schematic
selects and zooms to all corresponding layout instances in KLayout. Selecting
an imported instance in KLayout also selects and centers the source device in
Lumen. Use **Ctrl+Shift+H** for an explicit schematic-to-layout highlight.

The stock **SG13G2 PDK > Import Netlist** command remains available for external
SPICE/CDL sources. If the IIC Productivity Suite is installed, its **Netlist
Import** flow provides a more structured source/mapping/placement wizard.

## Verification

- **Run DRC** uses the IHP `tech/drc/run_drc.py` helper.
- **Run LVS** uses `tech/lvs/run_lvs.py`; choose the generated
  `<cell>.layout.cdl` as the schematic netlist and use `deep` for hierarchical
  layouts.
- In the KLayout GUI, the IHP DRC/LVS entries and their option dialogs are in
  the **SG13G2 PDK** menu.

## Environment contract

The Lumen and PowerShell launchers set `PDK_ROOT`, `PDK`, `PDKPATH`,
`STD_CELL_LIBRARY`, `KLAYOUT_HOME`, `KLAYOUT_PATH`, `PYTHONPATH`,
`PYTHONPYCACHEPREFIX`, and prepend the chosen KLayout directory to `PATH`.
`KLAYOUT_HOME` and Python bytecode caches remain workspace-local.

## Remaining boundary

Import From Source places the correct physical device variants and preserves
device identity for cross-probing. It does not automatically route schematic
nets as layout geometry. Interactive placement/routing, pins, taps, and
connectivity verification remain KLayout tasks, followed by LVS.
