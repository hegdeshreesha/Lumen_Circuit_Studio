"""
Test script to diagnose symbol placement issue
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))

from lumen.core.database import LibraryDatabase

def test_database():
    print("=== Testing Database ===")
    db = LibraryDatabase('test_workspace')
    
    print(f"\nLibraries found: {len(db.get_libraries())}")
    for lib in db.get_libraries():
        print(f"  - {lib.name} at {lib.path}")
        
    print(f"\nCells in 'primitives':")
    cells = db.get_cells('primitives')
    print(f"  Found {len(cells)} cells: {cells}")
    
    if cells:
        print(f"\nTesting symbol load for 'res':")
        sym_data = db.load_view('primitives', 'res', 'symbol')
        if sym_data:
            print(f"  [OK] Symbol loaded successfully")
            print(f"    Type: {sym_data.get('type')}")
            print(f"    Name: {sym_data.get('name')}")
            print(f"    Pins: {len(sym_data.get('pins', []))}")
            print(f"    Shapes: {len(sym_data.get('shapes', []))}")
        else:
            print(f"  [ERROR] Symbol load returned None!")
    else:
        print("  [ERROR] No cells found in primitives library!")
        
if __name__ == '__main__':
    test_database()
