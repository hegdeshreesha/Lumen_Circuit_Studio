"""
Lumen Circuit Studio - PDK System Demo

Run this script to see the complete PDK management system in action.
Shows how commercial custom IC platforms-style PDK management works.
"""
import sys
import os
import json

# Add project to path
sys.path.insert(0, os.path.dirname(__file__))

from lumen.core.pdk_workflow_manager import PDKWorkflowManager
from lumen.core import skywater_symbols, ihp_symbols, gf180mcu_symbols


def print_header(title):
    """Print a formatted header."""
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


def demo_symbols():
    """Demo: Show generated symbols for all PDKs."""
    print_header("1. GENERATED SYMBOLS")
    
    # SkyWater symbols
    print("\n  SkyWater SKY130 Symbols:")
    sky = skywater_symbols.generate_all_skywater_primitives()
    for name, sym in sky.items():
        pins = ", ".join([f"{p['name']}({p['x']},{p['y']})" for p in sym['pins']])
        print(f"    {name:15s} -> {sym['prefix']}  pins: [{pins}]")
    
    # IHP symbols
    print("\n  IHP SG13G2 Symbols:")
    ihp = ihp_symbols.generate_all_ihp_primitives()
    for name, sym in ihp.items():
        pins = ", ".join([f"{p['name']}({p['x']},{p['y']})" for p in sym['pins']])
        print(f"    {name:20s} -> {sym['prefix']}  pins: [{pins}]")
    
    # GF180MCU symbols
    print("\n  GF180MCU Symbols:")
    gf = gf180mcu_symbols.generate_all_gf180mcu_primitives()
    for name, sym in gf.items():
        pins = ", ".join([f"{p['name']}({p['x']},{p['y']})" for p in sym['pins']])
        print(f"    {name:15s} -> {sym['prefix']}  pins: [{pins}]")
    
    print(f"\n  Total: {len(sky)} SkyWater + {len(ihp)} IHP + {len(gf)} GF180MCU = {len(sky)+len(ihp)+len(gf)} symbols")


def demo_pdk_installation():
    """Demo: Install and configure PDKs."""
    print_header("2. PDK INSTALLATION (industry-style)")
    
    manager = PDKWorkflowManager()
    
    # Install IHP PDK
    ihp_path = os.path.join(os.path.dirname(__file__), "..", "ihp_pdk")
    if os.path.isdir(ihp_path):
        print(f"\n  Installing IHP SG13G2 PDK from: {ihp_path}")
        manager.install_pdk("ihp_sg13g2", ihp_path)
        manager.set_active_pdk("ihp_sg13g2")
        print("  OK - IHP SG13G2 installed and set as active")
    
    # Show status
    print("\n  Installed PDKs:")
    for name, config in manager.get_installed_pdks().items():
        print(f"    * {name}: {config.display_name}")
        print(f"      Path: {config.install_path}")
        print(f"      Model libs: {len(config.model_libraries)}")
    
    return manager


def demo_corners(manager):
    """Demo: Show available process corners."""
    print_header("3. PROCESS CORNERS (like simulation setup)")
    
    corners = manager.get_available_corners("ihp_sg13g2")
    print(f"\n  Available corners for IHP SG13G2 ({len(corners)} total):")
    
    # Group by device type
    groups = {}
    for c in corners:
        prefix = c.split('_')[0] if '_' in c else c
        if prefix not in groups:
            groups[prefix] = []
        groups[prefix].append(c)
    
    for prefix, items in sorted(groups.items()):
        print(f"    {prefix.upper():8s}: {', '.join(items)}")
    
    # Set active corner
    manager.set_active_corner("ihp_sg13g2", "mos_tt")
    print(f"\n  OK - Active corner set to: mos_tt (Typical-Typical for MOS)")


def demo_cdf_devices(manager):
    """Demo: Show CDF device definitions."""
    print_header("4. CDF DEVICES (Component Description Format)")
    
    print("\n  Built-in CDF devices (like device-parameter metadata database):")
    for name, device in sorted(manager.cdf.devices.items()):
        params = ", ".join([f"{p.name}={p.def_value}" for p in device.parameters[:4]])
        print(f"    {name:20s} -> {device.prefix}  model={device.spice_model_name:15s}  params=[{params}]")
    
    # Show a specific device in detail
    print("\n  Detailed CDF for 'sg13_lv_nmos':")
    device = manager.get_device_cdf("ihp_sg13g2", "sg13_lv_nmos")
    if device:
        print(f"    Name:      {device.name}")
        print(f"    Library:   {device.library}")
        print(f"    Prefix:    {device.prefix}")
        print(f"    Model:     {device.spice_model_name}")
        print(f"    Simulator: {device.simulator}")
        print(f"    Parameters:")
        for p in device.parameters:
            print(f"      {p.name:10s} = {p.def_value:10s}  [{p.description}] ({p.param_type})")


def demo_netlist(manager):
    """Demo: Generate SPICE netlist header."""
    print_header("5. NETLIST GENERATION (like SPICE simulation)")
    
    print("\n  Generated SPICE netlist header with .LIB includes:")
    print()
    header = manager.generate_netlist_header("ihp_sg13g2")
    for line in header.split('\n'):
        print(f"    {line}")


def demo_cds_lib(manager):
    """Demo: Generate cds.lib file."""
    print_header("6. CDS.LIB GENERATION (like library manager)")
    
    print("\n  Generating project 'my_design' with cds.lib...")
    cds_path = manager.generate_cds_lib("my_design", ".")
    print(f"  OK - Generated: {cds_path}")
    
    print("\n  Contents of cds.lib:")
    print()
    with open(cds_path, 'r') as f:
        for line in f:
            print(f"    {line}", end='')


def demo_health_report(manager):
    """Demo: Show PDK health report."""
    print_header("7. PDK HEALTH REPORT")
    
    report = manager.get_health_report("ihp_sg13g2")
    print(f"\n  PDK: {report['display_name']}")
    print(f"  Foundry: {report['foundry']}")
    print(f"  Node: {report['node']}")
    print(f"  Model libraries: {report['model_libraries_count']}")
    print(f"  Total devices: {report['total_devices']}")
    print(f"  Available corners: {len(report['available_corners'])}")
    print(f"  Active corner: {report['active_corner']}")
    print(f"  CDF devices: {report['cdf_devices']}")
    
    print("\n  Model Library Details:")
    for lib in report['lib_details']:
        print(f"    * {lib['name']:30s}  {lib['format']:12s}  {lib['devices']:3d} devices  {len(lib['corners']):2d} corners")


def demo_workflow():
    """Demo: Complete industry-style workflow."""
    print_header("8. COMPLETE INDUSTRY-STYLE WORKFLOW")
    
    print("""
  This is how you would use Lumen Circuit Studio like commercial custom IC platforms:

  +-----------------------------------------------------------+
  |  1. DOWNLOAD PDK locally (like getting TSMC PDK)          |
  |     git clone https://github.com/IHP-GmbH/IHP-Open-PDK    |
  |                                                           |
  |  2. INSTALL PDK in Lumen (like running PDK setup)         |
  |     manager.install_pdk("ihp_sg13g2", "/path/to/ihp-pdk") |
  |                                                           |
  |  3. SELECT MODEL LIBRARIES (Simulation Cockpit setup)      |
  |     manager.select_model_library("ihp_sg13g2", "models.lib")|
  |     manager.set_active_corner("ihp_sg13g2", "mos_tt")     |
  |                                                           |
  |  4. CREATE PROJECT (like Library Manager)                 |
  |     manager.generate_cds_lib("my_design", "./projects")   |
  |     # Creates: cds.lib, project.json                      |
  |                                                           |
  |  5. PLACE DEVICES (like schematic editor)                 |
  |     device = manager.get_device_cdf("ihp_sg13g2", "nmos") |
  |     # Returns: CDF with params, model binding, symbol     |
  |                                                           |
  |  6. RUN SIMULATION (Simulation Cockpit)                    |
  |     header = manager.generate_netlist_header()            |
  |     # Produces: .LIB includes with selected corner        |
  +-----------------------------------------------------------+
    """)


if __name__ == "__main__":
    print()
    print("+" + "-" * 66 + "+")
    print("|   Lumen Circuit Studio - PDK System Demo               |")
    print("|   commercial custom IC platforms-style PDK Management                |")
    print("+" + "-" * 66 + "+")
    
    # Run all demos
    demo_symbols()
    manager = demo_pdk_installation()
    demo_corners(manager)
    demo_cdf_devices(manager)
    demo_netlist(manager)
    demo_cds_lib(manager)
    demo_health_report(manager)
    demo_workflow()
    
    print()
    print("  Demo complete! Run this script to see the full system.")
    print("  Command: python demo_pdk_system.py")
    print()
