"""
Lumen Circuit Studio - Symbol Editor Window

Standalone shell for editing symbol views.
"""
from lumen.qt.QtWidgets import (
    QMainWindow, QStatusBar, QLabel, QToolBar, QMessageBox, QInputDialog,
    QFileDialog
)
from lumen.qt.QtCore import Qt, QSize
from lumen.qt.QtGui import QAction, QKeySequence
from pathlib import Path

from lumen.core.database import LibraryDatabase
from lumen.gui.symbol_editor import SymbolEditor
from lumen.gui.branding import apply_window_branding
from lumen.gui.icons import editor_icon


class SymbolEditorWindow(QMainWindow):
    """Standalone window for editing a symbol view."""

    def __init__(self, db: LibraryDatabase, library: str, cell: str,
                 view: str = "symbol", ciw=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.library = library
        self.cell = cell
        self.view = view
        self.ciw = ciw

        self.setWindowTitle(f"Lumen - {cell} ({view}) - [{library}]")
        apply_window_branding(self)
        self.setMinimumSize(900, 650)
        self.resize(1100, 760)

        self.editor = SymbolEditor(db, library, cell, view, parent=self)
        self.editor.coord_changed.connect(self._update_coords)
        self.setCentralWidget(self.editor)

        self._create_actions()
        self._create_menus()
        self._create_toolbars()
        self._create_status_bar()

    def _make_action(self, text: str, shortcut: str = "", slot=None) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        if slot:
            action.triggered.connect(lambda _=False, s=slot: s())
        else:
            action.triggered.connect(lambda _=False, t=text: self._not_implemented(t))
        return action

    def _create_actions(self):
        self.act_save = QAction("Save", self)
        self.act_save.setShortcut(QKeySequence("Ctrl+S"))
        self.act_save.triggered.connect(self._on_save)

        self.act_check_save = self._make_action("Check && Save", "Ctrl+Shift+S", self._on_save)
        self.act_new_symbol = self._make_action("New Symbol...", slot=self._on_new_symbol)
        self.act_open_symbol = self._make_action("Open Symbol...", "Ctrl+O", self._on_open_symbol)
        self.act_save_as = self._make_action("Save As...", slot=self._on_save_as)
        self.act_print = self._make_action("Print / Plot...", "Ctrl+P", self._on_export_image)

        self.act_close = QAction("Close", self)
        self.act_close.setShortcut(QKeySequence("Ctrl+W"))
        self.act_close.triggered.connect(self.close)

        self.act_undo = self._make_action("Undo", "Ctrl+Z", self._on_undo)
        self.act_redo = self._make_action("Redo", "Ctrl+Y", self._on_redo)
        self.act_copy = self._make_action("Copy", "Ctrl+C", self.editor.copy_selected)
        self.act_paste = self._make_action("Paste", "Ctrl+V", self.editor.paste_clipboard)
        self.act_delete = self._make_action("Delete", "Delete", self.editor.delete_selected)
        self.act_select_all = self._make_action("Select All", "Ctrl+A", self.editor.select_all)
        self.act_move = self._make_action("Move (M)", "M", lambda: self._set_symbol_tool("select"))
        self.act_rotate = self._make_action("Rotate (R)", "R", self.editor.rotate_selected)
        self.act_mirror = self._make_action("Mirror", slot=self.editor.mirror_selected)
        self.act_properties = self._make_action(
            "Object Properties (Q)", "Q", self._on_object_properties)

        self.act_select_tool = self._make_action(
            "Select", "Esc", lambda: self._set_symbol_tool("select"))
        self.act_line_tool = self._make_action(
            "Line (L)", "L", lambda: self._set_symbol_tool("line"))
        self.act_rect_tool = self._make_action(
            "Rectangle (R)", "Shift+R", lambda: self._set_symbol_tool("rect"))
        self.act_circle_tool = self._make_action(
            "Circle (C)", "C", lambda: self._set_symbol_tool("circle"))
        self.act_arc_tool = self._make_action(
            "Arc (A)", "A", lambda: self._set_symbol_tool("arc"))
        self.act_polygon_tool = self._make_action(
            "Polygon (P)", "P", lambda: self._set_symbol_tool("polygon"))
        self.act_pin_tool = self._make_action(
            "Pin (I)", "I", lambda: self._set_symbol_tool("pin"))
        self.act_text_tool = self._make_action(
            "Text", "T", lambda: self._set_symbol_tool("text"))
        self.act_label_tool = self._make_action(
            "Instance Label", slot=lambda: self._set_symbol_tool("label"))

        self.act_pin_order = self._make_action("Pin Order...", slot=self._on_pin_order)
        self.act_pin_properties = self._make_action("Pin Properties...", slot=self._on_pin_properties)
        self.act_auto_generate = self._make_action(
            "Auto Generate From Schematic", slot=self.editor._auto_generate)
        self.act_symbol_properties = self._make_action("Symbol Properties...", slot=self._on_symbol_properties)
        self.act_cdf = self._make_action("CDF / Netlisting Parameters...", slot=self._on_cdf)
        self.act_check_symbol = self._make_action(
            "Symbol Health Check", slot=self._on_symbol_health_check)
        self.act_display_options = self._make_action("Display Options...", slot=self._on_display_options)
        self.act_grid_options = self._make_action("Grid / Snap Options...", slot=self._on_grid_options)
        self.act_zoom_in = self._make_action("Zoom In", "Ctrl+=", self.editor.zoom_in)
        self.act_zoom_out = self._make_action("Zoom Out", "Ctrl+-", self.editor.zoom_out)
        self.act_zoom_fit = self._make_action("Zoom Fit", "F", self.editor.zoom_fit)
        self.act_command_palette = self._make_action("Command Palette...", "Ctrl+K", self._on_command_palette)
        self._assign_action_icons()

    def _assign_action_icons(self):
        icon_map = {
            self.act_open_symbol: "open",
            self.act_save: "save",
            self.act_check_save: "check",
            self.act_undo: "undo",
            self.act_redo: "redo",
            self.act_move: "move",
            self.act_select_tool: "move",
            self.act_line_tool: "wire",
            self.act_rect_tool: "instance",
            self.act_circle_tool: "palette",
            self.act_arc_tool: "wave",
            self.act_polygon_tool: "bus",
            self.act_pin_tool: "pin",
            self.act_auto_generate: "check",
            self.act_check_symbol: "health",
            self.act_zoom_in: "zoom_in",
            self.act_zoom_out: "zoom_out",
            self.act_zoom_fit: "zoom_fit",
            self.act_command_palette: "palette",
        }
        for action, icon_name in icon_map.items():
            action.setIcon(editor_icon(icon_name))

    def _create_menus(self):
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self.act_new_symbol)
        file_menu.addAction(self.act_open_symbol)
        file_menu.addSeparator()
        file_menu.addAction(self.act_save)
        file_menu.addAction(self.act_check_save)
        file_menu.addAction(self.act_save_as)
        file_menu.addSeparator()
        file_menu.addAction(self.act_print)
        file_menu.addSeparator()
        file_menu.addAction(self.act_close)

        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addAction(self.act_undo)
        edit_menu.addAction(self.act_redo)
        edit_menu.addSeparator()
        edit_menu.addAction(self.act_copy)
        edit_menu.addAction(self.act_paste)
        edit_menu.addAction(self.act_delete)
        edit_menu.addSeparator()
        edit_menu.addAction(self.act_move)
        edit_menu.addAction(self.act_rotate)
        edit_menu.addAction(self.act_mirror)
        edit_menu.addSeparator()
        edit_menu.addAction(self.act_select_all)
        edit_menu.addAction(self.act_properties)

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(self.act_zoom_in)
        view_menu.addAction(self.act_zoom_out)
        view_menu.addAction(self.act_zoom_fit)
        view_menu.addSeparator()
        view_menu.addAction(self.act_display_options)
        view_menu.addAction(self.act_grid_options)

        create_menu = self.menuBar().addMenu("&Create")
        create_menu.addAction(self.act_select_tool)
        create_menu.addSeparator()
        create_menu.addAction(self.act_line_tool)
        create_menu.addAction(self.act_rect_tool)
        create_menu.addAction(self.act_circle_tool)
        create_menu.addAction(self.act_arc_tool)
        create_menu.addAction(self.act_polygon_tool)
        create_menu.addSeparator()
        create_menu.addAction(self.act_pin_tool)
        create_menu.addAction(self.act_text_tool)
        create_menu.addAction(self.act_label_tool)

        pin_menu = self.menuBar().addMenu("&Pin")
        pin_menu.addAction(self.act_pin_properties)
        pin_menu.addAction(self.act_pin_order)

        tools_menu = self.menuBar().addMenu("&Tools")
        tools_menu.addAction(self.act_auto_generate)
        tools_menu.addAction(self.act_symbol_properties)
        tools_menu.addAction(self.act_cdf)
        tools_menu.addSeparator()
        tools_menu.addAction(self.act_check_symbol)

        lumen_menu = self.menuBar().addMenu("&Lumen")
        lumen_menu.addAction(self.act_command_palette)

    def _create_toolbars(self):
        file_tb = QToolBar("File")
        file_tb.setIconSize(QSize(18, 18))
        file_tb.addAction(self.act_save)
        file_tb.addAction(self.act_check_save)
        self.addToolBar(file_tb)

        draw_tb = QToolBar("Symbol Draw")
        draw_tb.setIconSize(QSize(18, 18))
        draw_tb.addAction(self.act_select_tool)
        draw_tb.addAction(self.act_line_tool)
        draw_tb.addAction(self.act_rect_tool)
        draw_tb.addAction(self.act_circle_tool)
        draw_tb.addAction(self.act_arc_tool)
        draw_tb.addAction(self.act_polygon_tool)
        draw_tb.addAction(self.act_pin_tool)
        self.addToolBar(draw_tb)

        view_tb = QToolBar("View")
        view_tb.setIconSize(QSize(18, 18))
        view_tb.addAction(self.act_zoom_in)
        view_tb.addAction(self.act_zoom_out)
        view_tb.addAction(self.act_zoom_fit)
        self.addToolBar(view_tb)

        tools_tb = QToolBar("Symbol Tools")
        tools_tb.setIconSize(QSize(18, 18))
        tools_tb.addAction(self.act_auto_generate)
        tools_tb.addAction(self.act_check_symbol)
        self.addToolBar(tools_tb)

    def _create_status_bar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)

        self.cell_label = QLabel(f"{self.library}/{self.cell}")
        self.cell_label.setStyleSheet("color: #ffffff; padding: 0 12px;")
        self.mode_label = QLabel("Tool: Select")
        self.mode_label.setStyleSheet(
            "color: #ffffff; font-weight: bold; padding: 0 12px;")
        self.coord_label = QLabel("X: 0  Y: 0")
        self.coord_label.setStyleSheet("color: #ffffff; padding: 0 12px;")

        sb.addWidget(self.cell_label)
        sb.addPermanentWidget(self.mode_label)
        sb.addPermanentWidget(self.coord_label)

    def _update_coords(self, x: float, y: float):
        self.coord_label.setText(f"X: {x:.1f}  Y: {y:.1f}")

    def _set_symbol_tool(self, tool: str):
        self.editor._set_tool(tool)
        self.mode_label.setText(f"Tool: {tool.capitalize()}")
        self.statusBar().showMessage(f"Symbol tool: {tool}", 2000)

    def _not_implemented(self, action_name: str):
        self.statusBar().showMessage(f"{action_name}: UI command is planned", 4000)
        QMessageBox.information(
            self,
            "Command Planned",
            f"'{action_name}' is part of the industry-style symbol GUI surface.\n\n"
            "The command is visible now so the workflow can be designed, but "
            "the underlying behavior still needs implementation.",
        )

    def _on_symbol_health_check(self):
        data = self.db.load_view(self.library, self.cell, self.view) or {}
        pins = len(data.get("pins", []))
        shapes = len(data.get("shapes", []))
        params = len(data.get("parameters", []))
        issues = []
        if pins == 0:
            issues.append("Symbol has no pins.")
        if shapes == 0:
            issues.append("Symbol has no drawing shapes.")
        if not data.get("prefix"):
            issues.append("Symbol has no netlisting prefix.")

        summary = f"Pins: {pins}\nShapes: {shapes}\nParameters: {params}"
        if issues:
            summary += "\n\nSuggestions:\n- " + "\n- ".join(issues)
        else:
            summary += "\n\nNo obvious symbol hygiene issues found."
        QMessageBox.information(self, "Symbol Health Check", summary)

    def _on_pin_order(self):
        current = ", ".join(self.editor.pin_names())
        text, ok = QInputDialog.getText(
            self, "Pin Order", "Comma-separated pin order:", text=current)
        if not ok:
            return
        names = [name.strip() for name in text.split(",") if name.strip()]
        self.editor.set_pin_order(names)
        self.statusBar().showMessage("Pin order updated", 3000)

    def _on_pin_properties(self):
        props = self.editor.selected_properties()
        if "direction" not in props:
            QMessageBox.information(self, "Pin Properties", "Select a symbol pin first.")
            return
        name, ok = QInputDialog.getText(
            self, "Pin Properties", "Pin name:", text=str(props.get("name", "")))
        if not ok or not name:
            return
        directions = ["input", "output", "inout", "power", "ground"]
        current = directions.index(props.get("direction", "inout")) if props.get("direction") in directions else 2
        direction, ok = QInputDialog.getItem(
            self, "Pin Properties", "Direction:", directions, current, False)
        if not ok:
            return
        orientations = ["R0", "R90", "R180", "R270"]
        current_orient = orientations.index(props.get("orientation", "R0")) if props.get("orientation") in orientations else 0
        orientation, ok = QInputDialog.getItem(
            self, "Pin Properties", "Orientation:", orientations, current_orient, False)
        if not ok:
            return
        self.editor.update_selected_pin(name, direction, orientation)
        self.statusBar().showMessage("Pin properties updated", 3000)

    def _on_symbol_properties(self):
        props = self.editor.symbol_properties()
        prefix, ok = QInputDialog.getText(
            self, "Symbol Properties", "Netlist prefix:", text=str(props.get("prefix", "X")))
        if not ok:
            return
        model, ok = QInputDialog.getText(
            self, "Symbol Properties", "SPICE model/subckt name:", text=str(props.get("spice_model", self.cell)))
        if not ok:
            return
        label, ok = QInputDialog.getText(
            self, "Symbol Properties", "Instance label template:", text=str(props.get("label", "@name")))
        if not ok:
            return
        self.editor.update_symbol_properties(prefix, model, label)
        self.statusBar().showMessage("Symbol properties updated", 3000)

    def _on_cdf(self):
        text, ok = QInputDialog.getMultiLineText(
            self,
            "CDF / Netlisting Parameters",
            "One parameter per line as name=default:",
            self.editor.cdf_lines(),
        )
        if not ok:
            return
        self.editor.update_cdf_lines(text)
        self.statusBar().showMessage("CDF parameters updated", 3000)

    def _on_display_options(self):
        visible = not self.editor.canvas._zoom_band and True
        self.editor.redraw()
        QMessageBox.information(
            self, "Display Options",
            "Symbol display options active:\n\n- Grid background\n- Crosshair origin\n"
            "- Selectable/movable primitives\n- Right-drag zoom window")

    def _on_grid_options(self):
        import lumen.gui.symbol_editor as symbol_editor
        value, ok = QInputDialog.getInt(
            self, "Grid / Snap Options", "Grid size:", symbol_editor.GRID_SIZE, 1, 500, 1)
        if not ok:
            return
        symbol_editor.GRID_SIZE = value
        self.statusBar().showMessage(f"Symbol grid set to {value}", 3000)
        self.editor.redraw()

    def _on_command_palette(self):
        QMessageBox.information(
            self,
            "Command Palette",
            "\n".join([
                "Line (L)", "Rectangle (Shift+R)", "Circle (C)", "Polygon (P)",
                "Pin (I)", "Text (T)", "Select (Esc)", "Object Properties (Q)",
                "Pin Order", "CDF / Netlisting Parameters", "Zoom Fit (F)",
            ]),
        )

    def _on_new_symbol(self):
        cell, ok = QInputDialog.getText(
            self, "New Symbol", "Cell name:", text=f"{self.cell}_sym")
        if not ok or not cell:
            return
        if not self.db.cell_exists(self.library, cell):
            try:
                lib_info = self.db.get_library(self.library)
                default_cell_path = str(Path(lib_info.path) / cell) if lib_info else cell
                cell_path, ok_path = QInputDialog.getText(
                    self,
                    "New Cell Path",
                    f"Path for {self.library}/{cell}:",
                    text=default_cell_path,
                )
                if not ok_path or not cell_path.strip():
                    return
                self.db.create_cell(self.library, cell, cell_path.strip())
            except ValueError as exc:
                QMessageBox.warning(self, "New Symbol", str(exc))
                return
        win = SymbolEditorWindow(self.db, self.library, cell, "symbol", self.ciw)
        win.show()
        self._child_window = win

    def _on_open_symbol(self):
        cell, ok = QInputDialog.getText(
            self, "Open Symbol", "Cell name:", text=self.cell)
        if not ok or not cell:
            return
        win = SymbolEditorWindow(self.db, self.library, cell, "symbol", self.ciw)
        win.show()
        self._child_window = win

    def _on_save_as(self):
        cell, ok = QInputDialog.getText(
            self, "Save Symbol As", "New cell name:", text=f"{self.cell}_copy")
        if not ok or not cell:
            return
        data = self.editor._snapshot()
        data["name"] = cell
        data["library"] = self.library
        if not self.db.cell_exists(self.library, cell):
            try:
                lib_info = self.db.get_library(self.library)
                default_cell_path = str(Path(lib_info.path) / cell) if lib_info else cell
                cell_path, ok_path = QInputDialog.getText(
                    self,
                    "New Cell Path",
                    f"Path for {self.library}/{cell}:",
                    text=default_cell_path,
                )
                if not ok_path or not cell_path.strip():
                    return
                self.db.create_cell(self.library, cell, cell_path.strip())
            except ValueError as exc:
                QMessageBox.warning(self, "Save Symbol As", str(exc))
                return
        self.db.save_view(self.library, cell, "symbol", data)
        self.statusBar().showMessage(f"Saved symbol as {self.library}/{cell}/symbol", 3000)

    def _on_export_image(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Symbol Image", f"{self.cell}_symbol.png", "PNG Image (*.png)")
        if not path:
            return
        self.editor.canvas.grab().save(path)
        self.statusBar().showMessage(f"Exported symbol image: {path}", 4000)

    def _on_undo(self):
        if not self.editor.undo():
            self.statusBar().showMessage("Nothing to undo", 2000)

    def _on_redo(self):
        if not self.editor.redo():
            self.statusBar().showMessage("Nothing to redo", 2000)

    def _on_object_properties(self):
        props = self.editor.selected_properties()
        if not props:
            self.statusBar().showMessage("No symbol object selected", 3000)
            return
        rows = [f"{key}: {value}" for key, value in props.items()]
        QMessageBox.information(self, "Object Properties", "\n".join(rows))

    def _on_save(self):
        self.editor.save()
        if self.ciw:
            self.ciw.log(f"Saved {self.library}/{self.cell}/{self.view}")
        self.statusBar().showMessage("Saved", 2000)
