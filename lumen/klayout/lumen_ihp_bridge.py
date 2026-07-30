"""Interactive Lumen/IHP bridge executed by KLayout with ``-rr``.

The script deliberately depends only on KLayout's built-in ``pya`` module and
the JSON handoff written by :mod:`lumen.core.layout_xl`.  It imports exact
``SG13_dev`` PCell variants, tags every created layout instance with its
schematic instance name, and watches a small command file for cross-probing.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pya


PROP_SCHEMATIC_INSTANCE = 12600
PROP_SCHEMATIC_LIBRARY = 12601
PROP_SCHEMATIC_CELL = 12602
PROP_PCELL_NAME = 12603
PROP_MULTIPLICITY_INDEX = 12604


def _log(message: str) -> None:
    print(f"[Lumen] {message}")


def _active_context(plan: dict):
    main_window = pya.Application.instance().main_window()
    view = main_window.current_view()
    if view is None:
        main_window.create_layout(str(plan.get("technology", "sg13g2")), 1)
        view = main_window.current_view()
    cellview = view.active_cellview()
    layout = cellview.layout()
    top = layout.top_cell()
    if top is None:
        top = layout.create_cell(str(plan.get("cell", "TOP")) or "TOP")
        cellview.cell = top
    return view, cellview, layout, top


def _managed_instances(top):
    return [inst for inst in top.each_inst() if inst.property(PROP_SCHEMATIC_INSTANCE) is not None]


def import_from_source(plan: dict) -> int:
    """Replace only Lumen-managed instances with the current schematic PCells."""
    view, _cellview, layout, top = _active_context(plan)
    library_name = str(plan.get("pcell_library", "SG13_dev"))
    library = pya.Library.library_by_name(library_name)
    if library is None:
        raise RuntimeError(
            f"KLayout library '{library_name}' is not registered. "
            "Check the IHP PyCell dependencies and restart KLayout."
        )

    # Source update is intentionally scoped: hand-drawn geometry and any
    # untagged instances remain untouched. Existing source identities retain
    # their placement so a parameter refresh does not scatter the layout.
    existing_positions = {}
    for inst in _managed_instances(top):
        key = (
            str(inst.property(PROP_SCHEMATIC_INSTANCE) or ""),
            int(inst.property(PROP_MULTIPLICITY_INDEX) or 0),
        )
        existing_positions[key] = inst.cplx_trans
        inst.delete()

    cursor_x = 0
    cursor_y = 0
    spacing = max(1, int(round(20.0 / layout.dbu)))
    placed = 0
    for item in plan.get("placements", []):
        pcell_name = str(item.get("pcell_name", ""))
        declaration = library.layout().pcell_declaration(pcell_name)
        if declaration is None:
            _log(f"Skipping missing PCell {library_name}::{pcell_name}")
            continue
        params = dict(item.get("pcell_parameters") or {})
        variant = layout.add_pcell_variant(library, declaration.id(), params)
        variant_cell = layout.cell(variant)
        bbox = variant_cell.bbox()
        count = max(1, int(item.get("multiplicity", 1)))
        for copy_index in range(count):
            key = (str(item.get("instance", "")), copy_index)
            transform = existing_positions.get(key)
            if transform is None:
                transform = pya.Trans(
                    pya.Trans.R0,
                    cursor_x - bbox.left,
                    cursor_y - bbox.bottom,
                )
            instance = top.insert(pya.CellInstArray(variant, transform))
            instance.set_property(PROP_SCHEMATIC_INSTANCE, str(item.get("instance", "")))
            instance.set_property(PROP_SCHEMATIC_LIBRARY, str(plan.get("library", "")))
            instance.set_property(PROP_SCHEMATIC_CELL, str(plan.get("cell", "")))
            instance.set_property(PROP_PCELL_NAME, pcell_name)
            instance.set_property(PROP_MULTIPLICITY_INDEX, copy_index)
            cursor_x += max(bbox.width(), spacing) + spacing
            placed += 1

    view.zoom_fit()
    view.update_content()
    _log(f"Imported {placed} physical instance(s) into {plan.get('library')}/{plan.get('cell')}")
    return placed


def highlight_instance(instance_name: str) -> bool:
    plan = _load_plan()
    if not plan:
        return False
    view, _cellview, _layout, top = _active_context(plan)
    matches = [
        inst
        for inst in top.each_inst()
        if str(inst.property(PROP_SCHEMATIC_INSTANCE) or "") == str(instance_name)
    ]
    view.clear_object_selection()
    cv_index = view.active_cellview_index
    for inst in matches:
        path = pya.ObjectInstPath()
        path.cv_index = cv_index
        path.top = top.cell_index()
        path.append_path(pya.InstElement(inst))
        view.select_object(path)
    if matches:
        view.zoom_fit_sel()
        view.update_content()
        _log(f"Highlighted schematic device {instance_name} ({len(matches)} layout instance(s))")
        return True
    _log(f"No imported layout instance corresponds to {instance_name}")
    return False


def _load_plan() -> dict:
    path = os.environ.get("LUMEN_PCELL_PLAN", "").strip()
    if not path or not Path(path).is_file():
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _log(f"Cannot read PCell plan: {exc}")
        return {}


class LumenBridgeTimer(pya.QObject):
    """Exchange cross-probe events without blocking KLayout's UI thread."""

    def __init__(self, parent, bridge_file: str, event_file: str):
        super(LumenBridgeTimer, self).__init__(parent)
        self._bridge_file = Path(bridge_file)
        self._event_file = Path(event_file) if event_file else None
        self._last_sequence = ""
        self._last_selected_instance = ""
        self._timer = pya.QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout = self._poll
        self._timer.start()

    def _poll(self):
        if self._bridge_file.is_file():
            try:
                command = json.loads(self._bridge_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                command = {}
            sequence = str(command.get("sequence", ""))
            if sequence and sequence != self._last_sequence:
                self._last_sequence = sequence
                plan = _load_plan()
                matches_session = not plan or (
                    str(command.get("library", "")) == str(plan.get("library", ""))
                    and str(command.get("cell", "")) == str(plan.get("cell", ""))
                )
                if matches_session and command.get("command") == "highlight":
                    highlight_instance(str(command.get("instance", "")))
                elif matches_session and command.get("command") == "clear_highlight":
                    view = pya.Application.instance().main_window().current_view()
                    if view is not None:
                        view.clear_object_selection()
        try:
            self._publish_layout_selection()
        except Exception as exc:
            _log(f"Cannot inspect layout selection: {exc}")

    def _publish_layout_selection(self):
        if self._event_file is None:
            return
        main_window = pya.Application.instance().main_window()
        view = main_window.current_view()
        selected_name = ""
        if view is not None:
            for selected in view.each_object_selected():
                if selected.is_cell_inst():
                    selected_instance = selected.inst()
                    selected_name = str(
                        selected_instance.property(PROP_SCHEMATIC_INSTANCE) or ""
                    )
                    if selected_name:
                        break
        if selected_name == self._last_selected_instance:
            return
        self._last_selected_instance = selected_name
        if not selected_name:
            return
        plan = _load_plan()
        event = {
            "schema": "lumen.klayout-bridge-event/v1",
            "sequence": time.time_ns(),
            "event": "select_source_device",
            "library": str(plan.get("library", "")),
            "cell": str(plan.get("cell", "")),
            "instance": selected_name,
        }
        temporary = self._event_file.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps(event, indent=2), encoding="utf-8")
            temporary.replace(self._event_file)
        except OSError as exc:
            _log(f"Cannot publish layout selection: {exc}")


def start() -> None:
    plan = _load_plan()
    placed = 0
    highlighted = False
    refreshed = False
    if plan and os.environ.get("LUMEN_IMPORT_SOURCE", "") == "1":
        try:
            placed = import_from_source(plan)
            if os.environ.get("LUMEN_VERIFY_REFRESH_SOURCE", "") == "1":
                placed = import_from_source(plan)
                refreshed = True
            verify_highlight = os.environ.get("LUMEN_VERIFY_HIGHLIGHT", "").strip()
            if verify_highlight:
                highlighted = highlight_instance(verify_highlight)
        except Exception as exc:  # KLayout must remain usable if import fails.
            _log(f"Import from source failed: {exc}")
            pya.QMessageBox.warning(None, "Lumen Import From Source", str(exc))

    verify_stamp = os.environ.get("LUMEN_BRIDGE_VERIFY_STAMP", "").strip()
    if verify_stamp:
        Path(verify_stamp).write_text(
            json.dumps(
                {
                    "success": True,
                    "placed": placed,
                    "highlighted": highlighted,
                    "refreshed": refreshed,
                    "library": plan.get("library", "") if plan else "",
                    "cell": plan.get("cell", "") if plan else "",
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    bridge_file = os.environ.get("LUMEN_KLAYOUT_BRIDGE_FILE", "").strip()
    if bridge_file:
        main_window = pya.Application.instance().main_window()
        # Parent ownership keeps the timer alive after this macro returns.
        global _LUMEN_BRIDGE_TIMER
        _LUMEN_BRIDGE_TIMER = LumenBridgeTimer(
            main_window,
            bridge_file,
            os.environ.get("LUMEN_KLAYOUT_EVENT_FILE", "").strip(),
        )
        if os.environ.get("LUMEN_VERIFY_PUBLISH_SELECTION", "") == "1":
            try:
                _LUMEN_BRIDGE_TIMER._publish_layout_selection()
            except Exception as exc:
                verify_stamp = os.environ.get("LUMEN_BRIDGE_VERIFY_STAMP", "").strip()
                if verify_stamp:
                    data = json.loads(Path(verify_stamp).read_text(encoding="utf-8"))
                    data["publish_error"] = repr(exc)
                    Path(verify_stamp).write_text(
                        json.dumps(data, indent=2),
                        encoding="utf-8",
                    )


start()
