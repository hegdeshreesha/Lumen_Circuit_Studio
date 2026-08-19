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

    def test_workspace_schema_state_created(self):
        state = Path(self.test_dir) / ".lumen_schema.json"
        self.assertTrue(state.exists())
        with open(state, "r") as f:
            data = json.load(f)
        self.assertGreaterEqual(int(data.get("version", 0)), 2)

    def test_primitives_include_analoglib_style_catalog(self):
        """Test that the built-in catalog exposes common analogLib-style cells."""
        expected_cells = {
            "res", "res_var", "cap", "cap_var", "ind", "mutual_ind",
            "vsource", "isource", "vdc", "idc", "vac", "iac",
            "vpulse", "ipulse", "vsin", "isin", "vpwl", "ipwl",
            "gnd", "vdd", "vss", "port", "opin", "ipin", "iopin",
            "no_conn", "iprobe", "nmos", "pmos", "nmos3", "pmos3",
            "diode", "zener", "led", "npn", "pnp", "njfet", "pjfet",
            "nmes", "pmes", "vcvs", "vccs", "cccs", "ccvs",
            "bsource_v", "bsource_i", "sw_v", "sw_i", "tline",
        }
        cells = set(self.db.get_cells("primitives"))

        self.assertTrue(expected_cells.issubset(cells))
        for cell in expected_cells:
            self.assertTrue(self.db.view_exists("primitives", cell, "symbol"))

    def test_primitives_include_qucs_component_families(self):
        """Built-ins should include QUCS-compatible lumped/source/nonlinear/system/digital components."""
        expected_qucs_cells = {
            # Lumped
            "dc_block", "dc_feed", "bias_t", "attenuator", "isolator",
            "circulator", "phase_shifter", "coupler_ideal", "hybrid",
            "voltage_probe", "time_switch", "relay", "transformer_ideal",
            "transformer_sym", "mutual_ind_3",
            # Sources
            "ac_power", "am_vsource", "pm_vsource", "noise_vsource",
            "noise_isource", "pulse_vsingle", "pulse_isingle",
            "pulse_vrect", "pulse_irect", "pulse_vexp", "pulse_iexp",
            "file_vsource", "file_isource", "noise_corr", "noise_corr_v",
            "noise_corr_i",
            # Nonlinear
            "diac", "thyristor", "triac", "mos_depl", "mos_bulk",
            "hjt_sub", "ekv26mos_va", "mesfet_va", "fbh_hbt_va",
            # System
            "eqn_device", "eqn_rf_device", "eqn_rf_2port", "sparam_file",
            "spice_netlist", "subckt_file", "vhdl_file", "verilog_file",
            # Digital
            "digital_source", "gate_or", "gate_nor", "gate_and", "gate_nand",
            "gate_xor", "gate_xnor", "inverter_dig", "buffer_dig",
            "dff", "rsff", "jkff", "logic0", "logic1", "mux2to1",
            "mux4to1", "mux8to1", "demux2to4", "demux3to8", "demux4to16",
            "half_adder_1bit", "full_adder_1bit", "full_adder_2bit",
        }
        cells = set(self.db.get_cells("primitives"))
        self.assertTrue(expected_qucs_cells.issubset(cells))
        for cell in expected_qucs_cells:
            self.assertTrue(self.db.view_exists("primitives", cell, "symbol"))

    def test_primitive_symbols_have_meaningful_markings(self):
        """Visual primitive symbols should include readable markings."""
        for cell in ("vdc", "vpulse", "vsin", "vcvs", "nmos", "npn", "port"):
            symbol = self.db.load_view("primitives", cell, "symbol")
            text_shapes = [
                shape for shape in symbol.get("shapes", [])
                if shape.get("type") == "text" and shape.get("text")
            ]
            self.assertTrue(text_shapes, f"{cell} should include text markings")

    def test_independent_sources_expose_ac_parameters(self):
        for cell in (
            "vsource", "isource", "vdc", "idc", "vac", "iac",
            "vpulse", "ipulse", "vsin", "isin", "vpwl", "ipwl",
        ):
            symbol = self.db.load_view("primitives", cell, "symbol")
            params = {param.get("name") for param in symbol.get("parameters", [])}
            self.assertIn("acmag", params, f"{cell} should expose AC magnitude")
            self.assertIn("acphase", params, f"{cell} should expose AC phase")

    def test_existing_primitives_library_is_reconciled(self):
        """Older workspaces should receive newly added primitive cells."""
        self.db.delete_cell("primitives", "vpulse")
        self.assertFalse(self.db.cell_exists("primitives", "vpulse"))

        reopened = LibraryDatabase(self.test_dir)

        self.assertTrue(reopened.cell_exists("primitives", "vpulse"))
        self.assertTrue(reopened.view_exists("primitives", "vpulse", "symbol"))
    
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
