"""
Test script to trace the full symbol placement flow
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from PyQt6.QtWidgets import QApplication
from lumen.core.database import LibraryDatabase
from lumen.gui.schematic_editor import SchematicEditor, InstanceBrowserDialog

def test_placement_flow():
    print("=== Testing Symbol Placement Flow ===\n")
    
    # Create minimal Qt app
    app = QApplication(sys.argv)
    
    # Create database
    db = LibraryDatabase('test_workspace')
    print(f"1. Database initialized")
    print(f"   Libraries: {[lib.name for lib in db.get_libraries()]}")
    
    # Create schematic editor
    editor = SchematicEditor(db, "test_lib", "test_cell", "schematic")
    print(f"\n2. Schematic editor created")
    
    # Create instance browser dialog
    dialog = InstanceBrowserDialog(db, parent=editor)
    print(f"\n3. Instance browser dialog created")
    
    # Simulate selecting a library
    print(f"\n4. Simulating library selection...")
    dialog.lib_list.setCurrentRow(0)  # Select first library (primitives)
    selected_lib = dialog.lib_list.currentItem().text() if dialog.lib_list.currentItem() else None
    print(f"   Selected library: {selected_lib}")
    print(f"   dialog.selected_library: {dialog.selected_library}")
    
    # Check cells populated
    cell_count = dialog.cell_list.count()
    print(f"\n5. Cells populated: {cell_count} cells")
    if cell_count > 0:
        for i in range(min(5, cell_count)):
            print(f"   - {dialog.cell_list.item(i).text()}")
    
    # Simulate selecting a cell
    if cell_count > 0:
        print(f"\n6. Simulating cell selection...")
        dialog.cell_list.setCurrentRow(0)  # Select first cell
        selected_cell = dialog.cell_list.currentItem().text() if dialog.cell_list.currentItem() else None
        print(f"   Selected cell: {selected_cell}")
        print(f"   dialog.selected_cell: {dialog.selected_cell}")
        
        # Try to get symbol data
        print(f"\n7. Getting symbol data...")
        sym_data = dialog.get_symbol_data()
        if sym_data:
            print(f"   [OK] Symbol data retrieved!")
            print(f"   Type: {sym_data.get('type')}")
            print(f"   Name: {sym_data.get('name')}")
            print(f"   Library: {sym_data.get('library')}")
            print(f"   Pins: {len(sym_data.get('pins', []))}")
            print(f"   Has shapes: {len(sym_data.get('shapes', [])) > 0}")
        else:
            print(f"   [ERROR] get_symbol_data() returned None!")
            print(f"   dialog.selected_library = {dialog.selected_library}")
            print(f"   dialog.selected_cell = {dialog.selected_cell}")
            print(f"   dialog._pdk_device = {dialog._pdk_device}")
    
    print(f"\n=== Test Complete ===")

if __name__ == '__main__':
    test_placement_flow()
