"""
Test script to diagnose symbol visibility issue
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtCore import QTimer
from lumen.core.database import LibraryDatabase
from lumen.gui.schematic_editor import SchematicEditor, InstanceItem

def test_symbol_rendering():
    print("=== Testing Symbol Visibility ===\n")
    
    app = QApplication(sys.argv)
    
    # Create database and load a symbol
    db = LibraryDatabase('test_workspace')
    print("1. Loading symbol from database...")
    sym_data = db.load_view('primitives', 'res', 'symbol')
    
    if sym_data:
        print(f"   Symbol loaded: {sym_data.get('name')}")
        print(f"   Shapes: {len(sym_data.get('shapes', []))}")
        print(f"   Pins: {len(sym_data.get('pins', []))}")
        print(f"   Prefix: '{sym_data.get('prefix')}'")
        print(f"   Library: '{sym_data.get('library')}'")
        print()
        
        # Print shapes details
        print("2. Shape details:")
        for i, shape in enumerate(sym_data.get('shapes', [])):
            print(f"   Shape {i}: type={shape.get('type')}", end='')
            if shape.get('type') == 'line':
                print(f", x1={shape.get('x1')}, y1={shape.get('y1')}, x2={shape.get('x2')}, y2={shape.get('y2')}")
            elif shape.get('type') == 'polyline':
                print(f", points={len(shape.get('points', []))} points")
            else:
                print()
        print()
        
        # Create editor and add instance
        print("3. Creating schematic editor...")
        editor = SchematicEditor(db, "test_lib", "test_cell", "schematic")
        print(f"   Scene created: {editor.scene}")
        print(f"   Scene rect: {editor.scene.sceneRect()}")
        print()
        
        # Try to create an instance directly
        print("4. Creating InstanceItem directly...")
        inst = InstanceItem(sym_data, "R0", 100, 100)
        print(f"   Instance created: {inst}")
        print(f"   Instance position: {inst.pos()}")
        print(f"   Instance boundingRect: {inst.boundingRect()}")
        print(f"   Instance isVisible: {inst.isVisible()}")
        print(f"   Instance childItems: {len(inst.childItems())}")
        print()
        
        # Add to scene
        print("5. Adding to scene...")
        editor.scene.addItem(inst)
        print(f"   Added to scene")
        print(f"   Scene items count: {len(editor.scene.items())}")
        print()
        
        # Check if item is in scene
        if inst in editor.scene.items():
            print("   [OK] Instance is in scene items list")
        else:
            print("   [ERROR] Instance NOT in scene items list!")
        print()
        
        # Create window to visually test
        print("6. Creating window for visual test...")
        window = QMainWindow()
        window.setCentralWidget(editor)
        window.setWindowTitle("Symbol Visibility Test")
        window.resize(800, 600)
        window.show()
        
        print("   Window displayed - you should see a resistor at position (100, 100)")
        print("   Check if the symbol is visible on the canvas")
        print()
        
        # Auto-close after 5 seconds
        QTimer.singleShot(5000, app.quit)
        
        sys.exit(app.exec())
    else:
        print("   [ERROR] Failed to load symbol!")

if __name__ == '__main__':
    test_symbol_rendering()
