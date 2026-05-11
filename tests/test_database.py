"""
Unit tests for Lumen Circuit Studio - Database Module
Tests library/cell/view database functionality.
"""
import unittest
import tempfile
import shutil
import json
from pathlib import Path

from lumen.core.database import LibraryDatabase, LibraryInfo, ViewType


class TestLibraryDatabase(unittest.TestCase):
    """Test cases for LibraryDatabase class."""
    
    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.db = LibraryDatabase(self.test_dir)
    
    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_library_creation(self):
        """Test creating a new library."""
        lib_info = self.db.create_library("test_lib", description="Test library")
        
        self.assertEqual(lib_info.name, "test_lib")
        self.assertEqual(lib_info.description, "Test library")
        self.assertTrue(Path(lib_info.path).exists())
        self.assertIn("test_lib", [lib.name for lib in self.db.get_libraries()])
    
    def test_library_exists(self):
        """Test checking if library exists."""
        self.db.create_library("test_lib")
        
        lib_info = self.db.get_library("test_lib")
        self.assertIsNotNone(lib_info)
        self.assertEqual(lib_info.name, "test_lib")
        
        nonexistent = self.db.get_library("nonexistent")
        self.assertIsNone(nonexistent)
    
    def test_cell_operations(self):
        """Test cell creation and existence checking."""
        self.db.create_library("test_lib")
        
        # Create cell
        cell_path = self.db.create_cell("test_lib", "test_cell")
        self.assertTrue(cell_path.exists())
        
        # Check cell exists
        self.assertTrue(self.db.cell_exists("test_lib", "test_cell"))
        self.assertFalse(self.db.cell_exists("test_lib", "nonexistent"))
        self.assertFalse(self.db.cell_exists("nonexistent", "test_cell"))
        
        # List cells
        cells = self.db.get_cells("test_lib")
        self.assertIn("test_cell", cells)
    
    def test_view_operations(self):
        """Test view creation, saving, and loading."""
        self.db.create_library("test_lib")
        self.db.create_cell("test_lib", "test_cell")
        
        # Test view existence
        self.assertFalse(self.db.view_exists("test_lib", "test_cell", "schematic"))
        
        # Save view data
        test_data = {
            "type": "schematic",
            "instances": [],
            "wires": [],
            "labels": []
        }
        self.db.save_view("test_lib", "test_cell", "schematic", test_data)
        
        # Check view exists
        self.assertTrue(self.db.view_exists("test_lib", "test_cell", "schematic"))
        
        # Load view data
        loaded_data = self.db.load_view("test_lib", "test_cell", "schematic")
        self.assertEqual(loaded_data["type"], "schematic")
        self.assertEqual(loaded_data["instances"], [])
        self.assertEqual(loaded_data["wires"], [])
        self.assertEqual(loaded_data["labels"], [])
        
        # List views
        views = self.db.get_views("test_lib", "test_cell")
        self.assertIn("schematic", views)
    
    def test_primitives_library(self):
        """Test that primitives library is automatically created."""
        libraries = self.db.get_libraries()
        primitives = [lib for lib in libraries if lib.name == "primitives"]
        
        self.assertEqual(len(primitives), 1)
        self.assertTrue(self.db.cell_exists("primitives", "res"))
        self.assertTrue(self.db.cell_exists("primitives", "cap"))
        self.assertTrue(self.db.cell_exists("primitives", "nmos"))
        self.assertTrue(self.db.cell_exists("primitives", "pmos"))
    
    def test_view_path(self):
        """Test getting view file path."""
        self.db.create_library("test_lib")
        self.db.create_cell("test_lib", "test_cell")
        
        view_path = self.db.get_view_path("test_lib", "test_cell", "schematic")
        expected_path = Path(self.test_dir) / "test_lib" / "test_cell" / "schematic.lumen.json"
        
        self.assertEqual(view_path, expected_path)
        
        # Test nonexistent library
        nonexistent_path = self.db.get_view_path("nonexistent", "test_cell", "schematic")
        self.assertIsNone(nonexistent_path)
    
    def test_library_deletion(self):
        """Test deleting a library."""
        lib_info = self.db.create_library("test_lib")
        lib_path = Path(lib_info.path)
        
        # Verify library exists
        self.assertTrue(lib_path.exists())
        self.assertIsNotNone(self.db.get_library("test_lib"))
        
        # Delete library
        self.db.delete_library("test_lib")
        
        # Verify deletion
        self.assertFalse(lib_path.exists())
        self.assertIsNone(self.db.get_library("test_lib"))
    
    def test_library_rename(self):
        """Test renaming a library."""
        lib_info = self.db.create_library("test_lib")
        old_path = Path(lib_info.path)
        
        # Rename library
        self.db.rename_library("test_lib", "new_lib")
        
        # Verify rename
        self.assertIsNone(self.db.get_library("test_lib"))
        new_lib_info = self.db.get_library("new_lib")
        self.assertIsNotNone(new_lib_info)
        self.assertEqual(new_lib_info.name, "new_lib")
        
        # Verify path was renamed
        new_path = Path(self.test_dir) / "new_lib"
        self.assertFalse(old_path.exists())
        self.assertTrue(new_path.exists())


if __name__ == '__main__':
    unittest.main()
