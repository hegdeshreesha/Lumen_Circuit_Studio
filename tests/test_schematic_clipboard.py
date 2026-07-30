import os
import tempfile
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication

    from lumen.core.database import LibraryDatabase
    from lumen.gui.schematic_editor import (
        NetLabelItem,
        SchematicEditor,
        WireItem,
    )
except ModuleNotFoundError as exc:
    if exc.name == "PyQt6":
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


@unittest.skipUnless(HAS_QT, "PyQt6 is not installed in this Python environment")
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


if __name__ == "__main__":
    unittest.main()
