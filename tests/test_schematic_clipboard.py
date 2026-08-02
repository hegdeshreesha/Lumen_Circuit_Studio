import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from lumen.qt.QtWidgets import QApplication

    from lumen.core.database import LibraryDatabase
    from lumen.core.xschem_symbol_import import XschemSymbolParser
    from lumen.gui.schematic_editor import (
        InstanceItem,
        NetLabelItem,
        SchematicEditor,
        WireItem,
    )
except ModuleNotFoundError as exc:
    if exc.name in {"PySide6", "lumen.qt"}:
        QApplication = None
        LibraryDatabase = None
        NetLabelItem = None
        SchematicEditor = None
        WireItem = None
    else:
        raise
else:
    HAS_QT = True

if "HAS_QT" not in globals():
    HAS_QT = False


def _app():
    return QApplication.instance() or QApplication([])


@unittest.skipUnless(HAS_QT, "PySide6 is not installed in this Python environment")
class SchematicClipboardTest(unittest.TestCase):
    def test_copy_paste_between_schematic_editors(self):
        app = _app()
        with tempfile.TemporaryDirectory() as tmp:
            db = LibraryDatabase(tmp)
            src = SchematicEditor(db, "", "source", "schematic")
            dst = SchematicEditor(db, "", "dest", "schematic")

            wire = WireItem(0, 0, 100, 0)
            wire.net_name = "vin"
            src.scene.addItem(wire)
            src.wires.append(wire)

            label = NetLabelItem("vin", 10, -20)
            src.scene.addItem(label)
            src.labels.append(label)

            wire.setSelected(True)
            label.setSelected(True)
            src.copy_selected()

            self.assertFalse(dst.wires)
            self.assertFalse(dst.labels)

            dst.paste_clipboard()
            app.processEvents()

            self.assertEqual(len(dst.wires), 1)
            self.assertEqual(dst.wires[0].net_name, "vin")
            self.assertEqual(len(dst.labels), 1)
            self.assertEqual(dst.labels[0].toPlainText(), "vin")
            dst.instances.append(SimpleNamespace(instance_name="R0"))
            self.assertEqual(dst._next_instance_name("R"), "R1")
            dst.instances.append(SimpleNamespace(instance_name="R1"))
            self.assertEqual(dst._next_instance_name("R"), "R2")

    def test_junction_dots_follow_schematic_crossing_rules(self):
        _ = _app()
        with tempfile.TemporaryDirectory() as tmp:
            db = LibraryDatabase(tmp)
            editor = SchematicEditor(db, "", "top", "schematic")
            for wire in (WireItem(0, 0, 20, 0), WireItem(10, -10, 10, 10)):
                editor.scene.addItem(wire)
                editor.wires.append(wire)

            editor._refresh_junction_dots()
            self.assertEqual(len(editor.junction_dots), 0)

            stub = WireItem(10, 0, 30, 0)
            editor.scene.addItem(stub)
            editor.wires.append(stub)
            editor._refresh_junction_dots()
            self.assertEqual(len(editor.junction_dots), 1)

    def test_connected_horizontal_wires_share_name_without_dot(self):
        _ = _app()
        with tempfile.TemporaryDirectory() as tmp:
            db = LibraryDatabase(tmp)
            editor = SchematicEditor(db, "", "top", "schematic")
            left = WireItem(0, 0, 10, 0)
            right = WireItem(10, 0, 20, 0)
            for wire in (left, right):
                editor.scene.addItem(wire)
                editor.wires.append(wire)

            left.setSelected(True)
            editor.name_selected_wires("VIN")
            editor._refresh_junction_dots()

            self.assertEqual(left.net_name, "VIN")
            self.assertEqual(right.net_name, "VIN")
            self.assertEqual(len(editor.junction_dots), 0)

    def test_instance_refresh_keeps_position_and_transform(self):
        _ = _app()
        symbol_path = Path("external/ihp_pdk/ihp-sg13g2/libs.tech/xschem/sg13g2_pr/sg13_lv_nmos.sym")
        if symbol_path.exists():
            symbol = XschemSymbolParser().parse_file(str(symbol_path)).to_lumen_json()
        else:
            symbol = {
                "name": "sg13_lv_nmos",
                "library": "pdk:ihp_sg13g2",
                "parameters": [{"name": "m", "default": "1"}],
                "shapes": [{"type": "text", "text": "m=@m", "x": 0, "y": 0}],
                "pins": [],
            }
        inst = InstanceItem(symbol, "M1", 120, -40, {"m": "1"})
        inst.setRotation(90)
        child_count = len(inst.childItems())
        pin_positions = dict(inst.pin_positions)
        inst.parameters["m"] = "2"
        inst.refresh_graphics()

        self.assertEqual(inst.pos().x(), 120)
        self.assertEqual(inst.pos().y(), -40)
        self.assertEqual(inst.rotation(), 90)
        self.assertEqual(len(inst.childItems()), child_count)
        self.assertEqual(inst.pin_positions, pin_positions)

    def test_property_edit_saves_updated_instance_params(self):
        _ = _app()

        class FakePropertyEditor:
            def show_properties(self, _name, _props, callback=None):
                self.callback = callback

        with tempfile.TemporaryDirectory() as tmp:
            db = LibraryDatabase(tmp)
            db.create_library("work")
            db.save_view("work", "res", "symbol", {
                "type": "symbol",
                "name": "res",
                "library": "work",
                "parameters": [{"name": "R", "default": "1k"}],
                "shapes": [{"type": "text", "text": "R=@R", "x": 0, "y": 0}],
                "pins": [],
            })
            db.save_view("work", "top", "schematic", {
                "type": "schematic",
                "name": "top",
                "library": "work",
                "instances": [{
                    "name": "R1", "library": "work", "cell": "res",
                    "x": 30, "y": 40, "params": {"R": "1k"},
                }],
                "wires": [],
                "labels": [],
                "pins": [],
            })
            editor = SchematicEditor(db, "work", "top", "schematic")
            editor.prop_editor = FakePropertyEditor()
            inst = editor.instances[0]

            editor._show_instance_properties(inst)
            editor.prop_editor.callback("R", "2k")

            saved = db.load_view("work", "top", "schematic")
            self.assertEqual(saved["instances"][0]["params"]["R"], "2k")
            self.assertEqual(saved["instances"][0]["x"], 30)
            self.assertEqual(saved["instances"][0]["y"], 40)


if __name__ == "__main__":
    unittest.main()
