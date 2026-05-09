import sys
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

# Add current directory to path
sys.path.append(os.getcwd())

from lumen.core.database import LibraryDatabase
from lumen.gui.library_manager_window import LibraryManagerWindow

class MockPDK:
    def __init__(self):
        self.name = "sky130"
        self.display_name = "SkyWater SKY130"
        self.foundry = "SkyWater"
        self.process = "SKY130"
        self.node = "130nm"
        self.description = "Test PDK"
        from lumen.core.pdk import PDKDevice
        self.devices = [
            PDKDevice("nfet", "MOSFET", "nmos", "M", "nfet", "NMOS", {}, ["D", "G", "S", "B"])
        ]

class MockRegistry:
    def __init__(self):
        self.pdk = MockPDK()
    def get_active_pdk(self):
        return self.pdk
    def get_pdk(self, name):
        return self.pdk

class MockCIW:
    def __init__(self):
        self.pdk_registry = MockRegistry()

app = QApplication([])
workspace = os.path.join(os.path.expanduser("~"), "LumenWorkspace")
db = LibraryDatabase(workspace)
mock_ciw = MockCIW()
win = LibraryManagerWindow(db, ciw=mock_ciw)

print("Simulating selection...")

# Find PDK item
pdk_item = None
for i in range(win.lib_tree.topLevelItemCount()):
    item = win.lib_tree.topLevelItem(i)
    if item.data(0, Qt.ItemDataRole.UserRole + 1) == "pdk":
        pdk_item = item
        break

if pdk_item:
    print(f"Selecting PDK: {pdk_item.text(0)}")
    win.lib_tree.setCurrentItem(pdk_item)
    
    # Check if cells populated
    print(f"Cells in table: {win.cell_table.rowCount()}")
    if win.cell_table.rowCount() > 0:
        cell_item = win.cell_table.item(0, 0)
        print(f"Selecting cell: {cell_item.text()}")
        win.cell_table.setCurrentItem(cell_item)
        print(f"Views in table: {win.view_table.rowCount()}")

print("Simulation finished OK")
