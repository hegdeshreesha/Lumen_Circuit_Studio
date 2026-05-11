"""
Lumen Circuit Studio — PDK Integration Package

Provides a unified interface for all PDK operations:
- Symbol generation for SkyWater, IHP, and GF180MCU
- PDK library management (Cadence .lib style)
- SPICE model file parsing (.lib format with corners)
- Symbol catalog generation from PDK model files
- Project library binding (cds.lib equivalent)

Usage:
    from lumen.pdk import get_pdk_manager, generate_all_symbols
    
    manager = get_pdk_manager()
    manager.set_active_pdk("sky130")
    devices = manager.get_available_devices()
    corners = manager.get_available_corners()
    
    # Or just generate all symbols
    generate_all_symbols()
"""
import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Any

from lumen.core import skywater_symbols, ihp_symbols, gf180mcu_symbols
from lumen.core.pdk_library_manager import PDKLibraryManager, create_manager
from lumen.core.pdk_unified import PDKRegistry


# ── Symbol Generation ───────────────────────────────────────────

def generate_skywater_symbols(output_dir: str = "") -> Dict[str, Dict[str, Any]]:
    """Generate all SkyWater primitive symbols."""
    symbols = skywater_symbols.generate_all_skywater_primitives()
    if output_dir:
        _save_symbols(symbols, output_dir, "sky130")
    return symbols


def generate_ihp_symbols(output_dir: str = "") -> Dict[str, Dict[str, Any]]:
    """Generate all IHP SG13G2 primitive symbols."""
    symbols = ihp_symbols.generate_all_ihp_primitives()
    if output_dir:
        _save_symbols(symbols, output_dir, "ihp_sg13g2")
    return symbols


def generate_gf180mcu_symbols(output_dir: str = "") -> Dict[str, Dict[str, Any]]:
    """Generate all GF180MCU primitive symbols."""
    symbols = gf180mcu_symbols.generate_all_gf180mcu_primitives()
    if output_dir:
        _save_symbols(symbols, output_dir, "gf180mcu")
    return symbols


def _save_symbols(symbols: Dict, output_dir: str, pdk_name: str):
    """Save generated symbols to files."""
    base_dir = Path(output_dir) if output_dir else Path.cwd() / "symbols" / pdk_name
    base_dir.mkdir(parents=True, exist_ok=True)
    for name, symbol in symbols.items():
        filename = base_dir / f"{name}.symbol.json"
        with open(filename, 'w') as f:
            json.dump(symbol, f, indent=2)


def generate_all_symbols(output_root: str = "lumen/generated_symbols") -> Dict[str, int]:
    """Generate all PDK symbols and return counts."""
    counts = {}
    
    symbols = generate_skywater_symbols(str(Path(output_root) / "sky130"))
    counts["sky130"] = len(symbols)
    
    symbols = generate_ihp_symbols(str(Path(output_root) / "ihp_sg13g2"))
    counts["ihp_sg13g2"] = len(symbols)
    
    symbols = generate_gf180mcu_symbols(str(Path(output_root) / "gf180mcu"))
    counts["gf180mcu"] = len(symbols)
    
    return counts


# ── PDK Manager ─────────────────────────────────────────────────

_pdk_manager_instance = None


def get_pdk_manager(workspace: str = "") -> PDKLibraryManager:
    """
    Get or create the global PDK library manager instance.
    
    This manager supports:
    - Registering local PDK installations
    - .lib file format parsing (Cadence-compatible)
    - Process corner management
    - Device catalog generation
    - Symbol-to-model mapping
    - Project library binding (cds.lib output)
    """
    global _pdk_manager_instance
    if _pdk_manager_instance is None or workspace:
        _pdk_manager_instance = PDKLibraryManager(workspace)
    return _pdk_manager_instance


def get_legacy_registry(workspace: str = "") -> PDKRegistry:
    """
    Get the legacy PDK registry (maintains backward compatibility).
    Uses the existing pdk_unified.py PDKRegistry.
    """
    if not workspace:
        workspace = os.path.join(os.path.expanduser("~"), "LumenWorkspace")
    return PDKRegistry(workspace)


def register_local_pdk(name: str, path: str, 
                       display_name: str = "") -> bool:
    """
    Register a locally-downloaded PDK.
    
    This is the primary way to use PDKs. Point to a local directory
    containing the PDK files (.lib models, symbols, etc.)
    
    Args:
        name: PDK identifier (e.g., 'sky130', 'ihp_sg13g2', 'gf180mcu')
        path: Path to the PDK root directory
        display_name: Optional human-readable name
    
    Returns:
        True if registered successfully
    """
    manager = get_pdk_manager()
    return manager.install_manager.register_local_pdk(name, path, display_name)


def create_project(project_name: str, project_dir: str, 
                   pdk_name: str) -> str:
    """
    Create a new project bound to a PDK.
    Generates library definition files (cds.lib style).
    
    Args:
        project_name: Name of the project
        project_dir: Directory to create the project
        pdk_name: PDK to bind
    
    Returns:
        Path to the generated library definition file
    """
    manager = get_pdk_manager()
    return manager.create_project_libraries(project_name, project_dir, pdk_name)


def get_available_pdks() -> Dict[str, Dict]:
    """Get all installed/registered PDKs with details."""
    manager = get_pdk_manager()
    return manager.install_manager.get_installed_pdks()


def get_pdk_health(name: str) -> Dict[str, Any]:
    """Get a health report for a PDK installation."""
    manager = get_pdk_manager()
    return manager.get_health_report(name)


# ── Backward Compatibility ─────────────────────────────────────

def generate_sky130_nmos() -> Dict[str, Any]:
    """Generate NMOS symbol (backward compatible)."""
    gen = skywater_symbols.SymbolGenerator()
    return gen.generate_nmos()


def generate_sky130_pmos() -> Dict[str, Any]:
    """Generate PMOS symbol (backward compatible)."""
    gen = skywater_symbols.SymbolGenerator()
    return gen.generate_pmos()


__all__ = [
    # Main API
    'get_pdk_manager',
    'get_legacy_registry',
    'register_local_pdk',
    'create_project',
    'get_available_pdks',
    'get_pdk_health',
    
    # Symbol generation
    'generate_skywater_symbols',
    'generate_ihp_symbols',
    'generate_gf180mcu_symbols',
    'generate_all_symbols',
    
    # Backward compatibility
    'generate_sky130_nmos',
    'generate_sky130_pmos',
]