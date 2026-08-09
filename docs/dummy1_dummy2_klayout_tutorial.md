# Dummy1/Dummy2: CMOS inverter layout in KLayout

This walkthrough is specific to the saved cell at
`C:\Users\hegde\LumenWorkspace\Dummy1\Dummy2`.

## What is in the source today

| Schematic instance | Source device | Imported IHP PCell | Parameters |
| --- | --- | --- | --- |
| `X0` | `sg13_lv_nmos` | `SG13_dev::nmos` | `w=0.15u l=0.13u ng=1`, one copy |
| `X1` | `sg13_lv_pmos` | `SG13_dev::pmos` | `w=0.15u l=0.13u ng=1`, one copy |

The common gates form the input and the common drains form the output. Each
bulk is tied to its source in the schematic. The cell currently has no pins or
net names, so do the source cleanup below before expecting LVS to match.

## 1. Clean the schematic source

1. Open `Dummy1 / Dummy2 / schematic` in Lumen.
2. Put a top-level input pin named `A` on the common gate net. Press **P**, click
   the gate wire, choose direction **input** and usage **signal**.
3. Put a top-level output pin named `Y` on the common drain net. Choose direction
   **output** and usage **signal**.
4. Put `VDD` on the PMOS `S+B` net and `VSS` on the NMOS `S+B` net. Use direction
   and usage **power** for `VDD`, and **ground** for `VSS`.
5. Confirm the intended device roles. A conventional drawing has PMOS `X1`
   connected to `VDD` and NMOS `X0` connected to `VSS`; their vertical position
   on the schematic does not matter, but those electrical connections do.
6. Choose **Simulation > Check & Save**. Resolve every floating-terminal warning
   on `X0` and `X1` before moving to layout.

## 2. Import the physical source

1. Restart Lumen once so the new KLayout actions are loaded.
2. Reopen `Dummy1 / Dummy2 / schematic`.
3. Choose **Layout > Import From Source Into KLayout** or press
   **Ctrl+Shift+I**.
4. If prompted, select the configured runtime:
   `C:\Users\hegde\LumenTools\KLayoutPortable\klayout-0.30.8-win64\klayout_app.exe`.
5. KLayout opens in edit mode with technology `sg13g2`. The Lumen bridge creates
   `X0` as an IHP `nmos` PCell and `X1` as an IHP `pmos` PCell. It replaces only
   instances previously managed by Lumen; hand-drawn routing is preserved.
6. If this is the first layout session, use **File > Save As** and save to:
   `C:\Users\hegde\LumenWorkspace\layout\Dummy1\Dummy2.gds`.

The same action also generates:

- `C:\Users\hegde\LumenWorkspace\layout\Dummy1\Dummy2.pcell-plan.json`
- `C:\Users\hegde\LumenWorkspace\layout\Dummy1\Dummy2.layout.cdl`

## 3. Prove device correspondence and highlighting

1. Leave KLayout open and return to the Lumen schematic.
2. Make sure **Layout > Device Highlight Sync** is checked.
3. Select `X0`. Within about 250 ms KLayout selects and zooms to its `nmos`
   instance.
4. Select `X1`. KLayout selects and zooms to its `pmos` instance.
5. In KLayout's instance-selection mode, select either imported PCell. Lumen
   selects and centers the matching `X0` or `X1` source device.
6. If automatic sync is disabled, select the schematic device and press
   **Ctrl+Shift+H**.

The bridge uses the persistent schematic identity attached to the KLayout
instance, not geometry order or a guessed model name. An `m` value greater than
one creates multiple layout instances under the same source identity, so all
copies highlight together.

## 4. Place the inverter

1. Move `X1` (PMOS) above `X0` (NMOS).
2. Align the gate sides so the two `G` terminals can share a short route.
3. Leave enough space for a drain/output route between the devices and for the
   well/substrate taps beside them.
4. Keep the PMOS n-well legal and continuous. Do not flatten or redraw the
   transistors: retain the `SG13_dev` PCells so parameter editing remains clean.
5. To change device size, change it in the Lumen schematic and run **Import From
   Source Into KLayout** again. Existing source identities retain their layout
   placement; Lumen-managed PCell variants are refreshed, while routing and
   other untagged geometry remain. Recheck terminal alignment after a size or
   finger-count change.

## 5. Add taps and route the four nets

1. From KLayout's **Libraries** panel, insert `SG13_dev::ntap1` near the PMOS and
   connect it to `VDD`. This ties the PMOS n-well.
2. Insert `SG13_dev::ptap1` near the NMOS and connect it to `VSS`. This ties the
   p-substrate.
3. The PCell `D` and `S` access regions are on `Metal1`; route:
   - PMOS `S` and `ntap1` to the `VDD` rail;
   - NMOS `S` and `ptap1` to the `VSS` rail;
   - both `D` terminals together to `Y`.
4. The PCell `G` access is on `GatPoly`. Join the gates with legal `GatPoly`, or
   use a legal poly/contact-to-Metal1 connection and route the input as `A`.
5. Use the PDK layer palette, grid, and DRC feedback; do not invent contact or
   via dimensions. For external net names used by LVS, put `A`, `Y`, `VDD`, and
   `VSS` text on `Metal1.text` (`8/25`) over their corresponding Metal1 shapes.
   Add `Metal1.pin` (`8/2`) shapes where you want explicit physical ports.

## 6. Check the layout

1. Save the GDS.
2. Choose **Layout > Run DRC** in Lumen, or **SG13G2 PDK > DRC** in KLayout.
3. Fix every geometry error and rerun until the report is clean.
4. Choose **Layout > Run LVS** and use the generated
   `Dummy2.layout.cdl` as the schematic netlist.
5. A correct result has two matched MOS devices and the same four external nets
   `A`, `Y`, `VDD`, and `VSS`. If bulk nets mismatch, check `ntap1`, `ptap1`, and
   their rail labels first.

## Lumen KLayout arrangement

For the one-time panel arrangement, IIC Productivity Suite setup, layer
shortcuts, and standalone launch command, follow
`docs/ihp_klayout_integration.md`, section **Layout editor workspace**.
