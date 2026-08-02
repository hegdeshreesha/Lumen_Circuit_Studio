"""
Lumen Circuit Studio — industry-style PDK & Library Manager

Implements a industry-compatible PDK and library management system:
- PDK installation management (local download, path referencing)
- .lib format model file support (Liberty .lib style)
- Library path configuration (cds.lib equivalent)
- Technology library binding per design
- Corner-aware simulation library management
- PDK health monitoring

Inspired by industry-standard's approach:
- cds.lib → library_definitions.json
- .lib → .lib model files (corner-based model files)
- techfile → pdk_manifest.json with technology parameters
"""
import json
import os
import re
import shutil
import hashlib
import urllib.request
import urllib.error
import subprocess
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
from datetime import datetime


# ── Corner Library (.lib) Format ────────────────────────────────

@dataclass
class LibCorner:
    """A process corner defined in a .lib file (industry-style)."""
    name: str
    description: str = ""
    temperature: float = 25.0
    voltage: float = 1.8
    devices: List[str] = field(default_factory=list)
    model_files: List[str] = field(default_factory=list)
    includes: List[str] = field(default_factory=list)
    is_default: bool = False


@dataclass
class LibFile:
    """
    A .lib format library file (industry-compatible).
    
    Liberty .lib format:
    ```
    library(library_name) {
        delay_model : "cmos";
        ...
        cell(cell_name) {
            ...
        }
    }
    ```
    
    For SPICE model .lib files:
    ```
    .LIB corner_name
    .MODEL ...
    .ENDS
    ```
    """
    name: str
    path: str = ""
    format_type: str = "spice"  # spice, veriloga, cdl, simulator
    corners: List[LibCorner] = field(default_factory=list)
    devices: List[Dict] = field(default_factory=list)
    checksum: str = ""
    
    @classmethod
    def parse_spice_lib(cls, filepath: str) -> 'LibFile':
        """
        Parse a SPICE .lib file to extract corners and model definitions.
        
        Typical .lib structure:
        .LIB typ
        .MODEL nmos ...
        .ENDS typ
        .LIB ff
        .MODEL nmos_ff ...
        .ENDS ff
        """
        lib = cls(name=Path(filepath).stem, path=filepath)
        
        if not os.path.isfile(filepath):
            return lib
        
        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            lib.checksum = hashlib.md5(content.encode()).hexdigest()
        except:
            return lib
        
        # Remove comments
        lines = []
        for line in content.split('\n'):
            stripped = line.strip()
            if stripped and not stripped.startswith('*') and not stripped.startswith('//'):
                lines.append(line)
        clean_content = '\n'.join(lines)
        
        # Extract .LIB sections (corners)
        current_corner = None
        corner_devices = []
        corner_includes = []
        
        for line in clean_content.split('\n'):
            upper = line.strip().upper()
            
            if upper.startswith('.LIB '):
                # Save previous corner
                if current_corner:
                    lib.corners.append(LibCorner(
                        name=current_corner,
                        devices=list(corner_devices),
                        includes=list(corner_includes)
                    ))
                # Start new corner
                match = re.match(r'\.LIB\s+"?([^"\s]+)"?\s+(\w+)', line)
                if match:
                    current_corner = match.group(2)
                else:
                    match = re.match(r'\.LIB\s+(\w+)', line)
                    if match:
                        current_corner = match.group(1)
                corner_devices = []
                corner_includes = []
            
            elif upper.startswith('.MODEL '):
                match = re.match(r'\.MODEL\s+(\S+)', line)
                if match:
                    corner_devices.append(match.group(1))
            
            elif upper.startswith('.INCLUDE ') or upper.startswith('.INC '):
                match = re.match(r'\.(?:INC|INCLUDE)\s+"?([^"\s]+)"?', line)
                if match:
                    corner_includes.append(match.group(1))
            
            elif upper.startswith('.ENDS') and current_corner:
                pass  # End of corner section
        
        # Save last corner
        if current_corner and current_corner not in [c.name for c in lib.corners]:
            lib.corners.append(LibCorner(
                name=current_corner,
                model_files=list(corner_devices) if hasattr(LibCorner, 'model_files') else [],
                includes=list(corner_includes)
            ))
        
        # If no corners found, try to parse as regular model file
        if not lib.corners:
            models = re.findall(r'\.MODEL\s+(\S+)\s+(\S+)', clean_content, re.IGNORECASE)
            for model_name, model_type in models:
                lib.devices.append({
                    "name": model_name,
                    "type": model_type,
                    "model": model_name
                })
        
        return lib
    
    def to_json(self) -> Dict:
        """Serialize to JSON-compatible dict."""
        return {
            "name": self.name,
            "path": self.path,
            "format": self.format_type,
            "corners": [asdict(c) for c in self.corners],
            "devices": self.devices,
            "checksum": self.checksum
        }


# ── Library Definition (cds.lib equivalent) ────────────────────

@dataclass
class LibraryDefinition:
    """
    A library definition equivalent to industry-standard's cds.lib entries.
    
    cds.lib-style format:
    ```
    DEFINE my_lib /path/to/library
    SOFTINCLUDE /path/to/other/libs
    ```
    
    Lumen equivalent with enhanced metadata.
    """
    name: str
    path: str
    library_type: str = "pdk"  # pdk, reference, design, ip
    description: str = ""
    pdk_name: str = ""  # Associated PDK name
    technology: str = ""
    enabled: bool = True
    priority: int = 50  # Lower = higher priority
    tags: List[str] = field(default_factory=list)
    
    @classmethod
    def from_cds_lib_line(cls, line: str) -> Optional['LibraryDefinition']:
        """Parse a single line from CDS.lib format."""
        line = line.strip()
        if not line or line.startswith('#'):
            return None
        if line.upper().startswith('DEFINE '):
            parts = line[7:].strip().split()
            if len(parts) >= 2:
                return cls(name=parts[0], path=parts[1])
        return None
    
    def to_cds_lib_line(self) -> str:
        """Export to CDS.lib format line."""
        return f"DEFINE {self.name} {self.path}"


@dataclass 
class LibraryDefinitions:
    """
    Collection of library definitions (cds.lib equivalent).
    Manages all libraries available to a design project.
    """
    project_name: str = ""
    definitions: List[LibraryDefinition] = field(default_factory=list)
    
    def save_cds_lib(self, filepath: str):
        """Save to CDS.lib format file."""
        lines = [
            f"# Lumen Circuit Studio Library Definitions",
            f"# Generated: {datetime.now().isoformat()}",
            f"# Project: {self.project_name}",
            f"",
        ]
        for lib in self.definitions:
            if lib.enabled:
                lines.append(lib.to_cds_lib_line())
        lines.append("")
        
        with open(filepath, 'w') as f:
            f.write('\n'.join(lines))
    
    def load_cds_lib(self, filepath: str):
        """Load from CDS.lib format file."""
        if not os.path.isfile(filepath):
            return
        with open(filepath, 'r') as f:
            for line in f:
                lib = LibraryDefinition.from_cds_lib_line(line)
                if lib:
                    self.definitions.append(lib)
    
    def find_library(self, name: str) -> Optional[LibraryDefinition]:
        """Find a library by name."""
        for lib in self.definitions:
            if lib.name == name:
                return lib
        return None
    
    def to_json(self) -> Dict:
        """Serialize to JSON."""
        return {
            "project": self.project_name,
            "libraries": [asdict(l) for l in self.definitions]
        }


# ── PDK Installation Manager ───────────────────────────────────

class PDKInstallManager:
    """
    Manages PDK installations with local path referencing.
    Supports:
    - Local PDK directory referencing
    - Git-based PDK cloning
    - .lib file discovery and registration
    - Environment variable configuration (PDK_ROOT, etc.)
    """
    
    # Known PDK sources for download/reference
    KNOWN_PDKS = {
        "sky130": {
            "display_name": "SkyWater SKY130",
            "foundry": "SkyWater Technology",
            "node": "130nm",
            "url": "https://github.com/google/skywater-pdk",
            "libs_pattern": "**/*.lib",
            "models_subdir": "models",
            "default_voltage": 1.8,
            "corners": ["tt", "ff", "ss", "sf", "fs"],
        },
        "ihp_sg13g2": {
            "display_name": "IHP SG13G2",
            "foundry": "IHP Microelectronics",
            "node": "130nm",
            "url": "https://github.com/IHP-GmbH/IHP-Open-PDK",
            "libs_pattern": "**/*.lib",
            "models_subdir": "libs.tech/ngspice",
            "default_voltage": 1.2,
            "corners": ["typ", "fast", "slow"],
        },
        "gf180mcu": {
            "display_name": "GlobalFoundries GF180MCU",
            "foundry": "GlobalFoundries",
            "node": "180nm",
            "url": "https://github.com/google/gf180mcu-pdk",
            "libs_pattern": "**/*.lib",
            "models_subdir": "models",
            "default_voltage": 3.3,
            "corners": ["typical", "ff", "ss"],
        },
    }
    
    def __init__(self, workspace_dir: str = ""):
        self.workspace = Path(workspace_dir or os.path.join(
            os.path.expanduser("~"), ".lumen", "pdk"))
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._installed: Dict[str, Dict] = {}
        self._config_path = self.workspace / "pdk_install_config.json"
        self._load_config()
    
    def _load_config(self):
        """Load PDK installation configuration."""
        if self._config_path.exists():
            try:
                with open(self._config_path, 'r') as f:
                    self._installed = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._installed = {}
    
    def _save_config(self):
        """Save PDK installation configuration."""
        with open(self._config_path, 'w') as f:
            json.dump(self._installed, f, indent=2)
    
    def get_installed_pdks(self) -> Dict[str, Dict]:
        """Get all installed PDKs."""
        # Verify installations still exist
        verified = {}
        for name, info in self._installed.items():
            if os.path.isdir(info.get("path", "")):
                verified[name] = info
        return verified
    
    def is_installed(self, pdk_name: str) -> bool:
        """Check if a PDK is installed."""
        info = self._installed.get(pdk_name)
        if info and os.path.isdir(info.get("path", "")):
            return True
        return False
    
    def get_pdk_path(self, pdk_name: str) -> Optional[str]:
        """Get the installation path of a PDK."""
        info = self._installed.get(pdk_name)
        if info:
            return info.get("path")
        return None
    
    def register_local_pdk(self, name: str, path: str, 
                          display_name: str = "") -> bool:
        """
        Register a locally-downloaded PDK.
        
        This is the primary way to add PDKs - point to a local directory
        that contains the PDK files (.lib models, symbols, etc.)
        
        Args:
            name: PDK internal name (e.g., 'sky130')
            path: Local filesystem path to PDK root
            display_name: Human-readable name (auto-detected if empty)
        """
        p = Path(path)
        if not p.exists():
            print(f"Error: Path does not exist: {path}")
            return False
        if not p.is_dir():
            print(f"Error: Path is not a directory: {path}")
            return False
        
        # Auto-detect display name
        if not display_name:
            info = self.KNOWN_PDKS.get(name, {})
            display_name = info.get("display_name", name)
        
        # Scan for .lib files
        lib_files = []
        for lib_path in p.rglob("*.lib"):
            try:
                lib = LibFile.parse_spice_lib(str(lib_path))
                if lib.corners or lib.devices:
                    lib_files.append({
                        "path": str(lib_path),
                        "relative_path": str(lib_path.relative_to(p)),
                        "corners": [c.name for c in lib.corners],
                        "devices": lib.devices
                    })
            except:
                pass
        
        install_info = {
            "name": name,
            "display_name": display_name,
            "path": str(p.absolute()),
            "lib_files": lib_files,
            "installed_at": datetime.now().isoformat(),
            "foundry": self.KNOWN_PDKS.get(name, {}).get("foundry", ""),
            "node": self.KNOWN_PDKS.get(name, {}).get("node", ""),
        }
        
        self._installed[name] = install_info
        self._save_config()
        return True
    
    def clone_pdk(self, name: str, url: str = "", 
                  branch: str = "main") -> bool:
        """
        Clone a PDK repository from a URL.
        
        This provides automated PDK download similar to industry-standard's
        library manager where you can download PDKs from various sources.
        
        Args:
            name: PDK name (must be in KNOWN_PDKS or provide URL)
            url: Git repository URL (auto-detected if empty)
            branch: Git branch to clone
        """
        if not url:
            info = self.KNOWN_PDKS.get(name)
            if not info:
                print(f"Error: Unknown PDK '{name}'. Provide a URL.")
                return False
            url = info["url"]
        
        target_dir = self.workspace / name
        if target_dir.exists():
            print(f"PDK '{name}' already exists at {target_dir}")
            return self.register_local_pdk(name, str(target_dir))
        
        try:
            print(f"Cloning {name} from {url}...")
            result = subprocess.run(
                ["git", "clone", "-b", branch, "--depth", "1", url, str(target_dir)],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode != 0:
                print(f"Git clone failed: {result.stderr}")
                return False
        except Exception as e:
            print(f"Clone failed: {e}")
            return False
        
        return self.register_local_pdk(name, str(target_dir))
    
    def remove_pdk(self, name: str, remove_files: bool = False) -> bool:
        """Remove a PDK from the registry."""
        if name not in self._installed:
            return False
        
        if remove_files:
            path = self._installed[name].get("path")
            if path and os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
        
        del self._installed[name]
        self._save_config()
        return True
    
    def discover_lib_files(self, pdk_name: str) -> List[Dict]:
        """Discover all .lib files in an installed PDK."""
        info = self._installed.get(pdk_name)
        if not info:
            return []
        return info.get("lib_files", [])
    
    def get_available_corners(self, pdk_name: str) -> List[str]:
        """Get all available process corners from .lib files."""
        corners = set()
        for lib_info in self.discover_lib_files(pdk_name):
            corners.update(lib_info.get("corners", []))
        return sorted(corners)


# ── Technology Library (techfile equivalent) ────────────────────

@dataclass
class TechnologyLibrary:
    """
    Technology library equivalent to industry-standard's techfile.
    Contains layer definitions, design rules, and device parameters.
    """
    name: str
    pdk_name: str
    layers: List[Dict] = field(default_factory=list)
    design_rules: Dict = field(default_factory=dict)
    devices: List[Dict] = field(default_factory=list)
    display_settings: Dict = field(default_factory=dict)
    
    def to_json(self) -> Dict:
        return {
            "name": self.name,
            "pdk": self.pdk_name,
            "layers": self.layers,
            "design_rules": self.design_rules,
            "devices": self.devices,
            "display": self.display_settings
        }


# ── Unified PDK Library Manager (Main API) ─────────────────────

class PDKLibraryManager:
    """
    Main PDK library management API.
    Combines PDK installation, library definitions, and technology management.
    
    Usage:
        manager = PDKLibraryManager()
        
        # Register a locally-downloaded PDK
        manager.install_manager.register_local_pdk("sky130", "/path/to/skywater-pdk")
        
        # Set active PDK for a project
        manager.set_active_pdk("sky130")
        
        # Get available devices
        devices = manager.get_available_devices()
        
        # Generate symbol catalog
        symbols = manager.generate_symbol_catalog()
        
        # Get available corners
        corners = manager.get_available_corners()
        
        # Save library definitions (cds.lib style)
        library_defs.save_cds_lib("cds.lib")
    """
    
    def __init__(self, workspace_dir: str = ""):
        self.workspace = Path(workspace_dir or os.path.join(
            os.path.expanduser("~"), ".lumen"))
        self.workspace.mkdir(parents=True, exist_ok=True)
        
        self.install_manager = PDKInstallManager(
            str(self.workspace / "pdk"))
        self.library_definitions = LibraryDefinitions()
        self._active_pdk: str = ""
        self._active_libs: List[str] = []
        
        # Load configuration
        self._config_path = self.workspace / "library_manager.json"
        self._load_config()
    
    def _load_config(self):
        """Load configuration."""
        if self._config_path.exists():
            try:
                with open(self._config_path, 'r') as f:
                    data = json.load(f)
                self._active_pdk = data.get("active_pdk", "")
                self._active_libs = data.get("active_libs", [])
                libs_data = data.get("library_definitions", [])
                for lib_data in libs_data:
                    self.library_definitions.definitions.append(
                        LibraryDefinition(**lib_data))
            except (json.JSONDecodeError, OSError, TypeError):
                pass
    
    def _save_config(self):
        """Save configuration."""
        data = {
            "active_pdk": self._active_pdk,
            "active_libs": self._active_libs,
            "library_definitions": [
                asdict(l) for l in self.library_definitions.definitions
            ],
        }
        with open(self._config_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    def set_active_pdk(self, pdk_name: str) -> bool:
        """Set the active PDK for the current project."""
        if self.install_manager.is_installed(pdk_name):
            self._active_pdk = pdk_name
            self._save_config()
            return True
        return False
    
    def get_active_pdk(self) -> Optional[str]:
        """Get the active PDK name."""
        return self._active_pdk if self._active_pdk else None
    
    def get_active_pdk_info(self) -> Optional[Dict]:
        """Get detailed info about active PDK."""
        if not self._active_pdk:
            return None
        installed = self.install_manager.get_installed_pdks()
        return installed.get(self._active_pdk)
    
    def get_available_devices(self, pdk_name: str = "") -> List[Dict]:
        """
        Get all available devices from a PDK's .lib files.
        Similar to industry-standard's library browser.
        """
        name = pdk_name or self._active_pdk
        if not name:
            return []
        
        devices = []
        for lib_info in self.install_manager.discover_lib_files(name):
            for dev in lib_info.get("devices", []):
                devices.append({
                    **dev,
                    "lib_file": lib_info.get("relative_path", ""),
                    "pdk": name,
                })
        return devices
    
    def get_available_corners(self, pdk_name: str = "") -> List[str]:
        """Get available process corners (from .lib sections)."""
        name = pdk_name or self._active_pdk
        if not name:
            return []
        return self.install_manager.get_available_corners(name)
    
    def get_lib_files_for_corner(self, pdk_name: str, 
                                  corner: str) -> List[str]:
        """Get .lib files that define a specific corner."""
        name = pdk_name or self._active_pdk
        if not name:
            return []
        
        matching = []
        for lib_info in self.install_manager.discover_lib_files(name):
            if corner in lib_info.get("corners", []):
                pdk_path = self.install_manager.get_pdk_path(name)
                if pdk_path:
                    full_path = os.path.join(pdk_path, 
                                            lib_info["relative_path"])
                    matching.append(full_path)
        return matching
    
    def generate_symbol_catalog(self, pdk_name: str = "") -> Dict[str, Any]:
        """
        Generate a symbol catalog from PDK model files.
        Maps SPICE models to their symbol names for schematic capture.
        """
        name = pdk_name or self._active_pdk
        if not name:
            return {}
        
        catalog = {}
        for lib_info in self.install_manager.discover_lib_files(name):
            for dev in lib_info.get("devices", []):
                model_name = dev.get("model", dev.get("name"))
                dev_type = dev.get("type", "").upper()
                
                # Map model type to symbol name
                if dev_type in ("NMOS", "NMOS1", "NMOS2", "NCH"):
                    symbol = "nmos"
                elif dev_type in ("PMOS", "PMOS1", "PMOS2", "PCH"):
                    symbol = "pmos"
                elif dev_type in ("NPN", "NPN1", "NPN2"):
                    symbol = "npn"
                elif dev_type in ("PNP",):
                    symbol = "pnp"
                elif dev_type in ("D", "DIO", "DIODE"):
                    symbol = "diode"
                elif dev_type in ("R", "RES", "RESISTOR"):
                    symbol = "resistor"
                elif dev_type in ("C", "CAP", "CAPACITOR"):
                    symbol = "capacitor"
                else:
                    symbol = "generic"
                
                catalog[model_name] = {
                    "symbol": symbol,
                    "type": dev_type,
                    "model": model_name,
                    "pdk": name,
                    "lib_file": lib_info.get("relative_path", ""),
                }
        
        return catalog
    
    def create_project_libraries(self, project_name: str, 
                                  project_dir: str,
                                  pdk_name: str = "") -> str:
        """
        Create library definitions for a project.
        Similar to industry-standard creating a new library with technology binding.
        
        Args:
            project_name: Name of the project/library
            project_dir: Directory to store project libraries
            pdk_name: PDK to bind to the project
        
        Returns:
            Path to the generated library definition file
        """
        pdk = pdk_name or self._active_pdk
        if not pdk:
            raise ValueError("No PDK specified or active")
        
        pdk_path = self.install_manager.get_pdk_path(pdk)
        if not pdk_path:
            raise ValueError(f"PDK '{pdk}' is not installed")
        
        project_root = Path(project_dir) / project_name
        project_root.mkdir(parents=True, exist_ok=True)
        
        # Create library definitions
        lib_defs = LibraryDefinitions(project_name=project_name)
        
        # Add PDK library
        pdk_info = self.install_manager.get_installed_pdks().get(pdk, {})
        lib_defs.definitions.append(LibraryDefinition(
            name=pdk,
            path=pdk_path,
            library_type="pdk",
            description=pdk_info.get("display_name", pdk),
            pdk_name=pdk,
        ))
        
        # Add design library
        design_path = str(project_root / "design")
        Path(design_path).mkdir(exist_ok=True)
        lib_defs.definitions.append(LibraryDefinition(
            name=project_name,
            path=design_path,
            library_type="design",
            description=f"{project_name} design library",
            pdk_name=pdk,
        ))
        
        # Save CDS.lib style file
        cds_lib_path = str(project_root / "cds.lib")
        lib_defs.save_cds_lib(cds_lib_path)
        
        # Save JSON format for Lumen
        json_path = str(project_root / "library_definitions.json")
        with open(json_path, 'w') as f:
            json.dump(lib_defs.to_json(), f, indent=2)
        
        return cds_lib_path
    
    def to_json(self) -> Dict:
        """Serialize manager state to JSON."""
        return {
            "active_pdk": self._active_pdk,
            "active_libs": self._active_libs,
            "installed_pdks": self.install_manager.get_installed_pdks(),
            "library_definitions": [
                asdict(l) for l in self.library_definitions.definitions
            ],
        }
    
    def get_health_report(self, pdk_name: str) -> Dict[str, Any]:
        """Generate a health report for a PDK installation."""
        name = pdk_name or self._active_pdk
        if not name:
            return {"error": "No PDK specified"}
        
        info = self.install_manager.get_installed_pdks().get(name)
        if not info:
            return {"error": f"PDK '{name}' not installed"}
        
        lib_files = info.get("lib_files", [])
        corners = set()
        device_count = 0
        
        for lib in lib_files:
            corners.update(lib.get("corners", []))
            device_count += len(lib.get("devices", []))
        
        return {
            "name": name,
            "display_name": info.get("display_name", name),
            "installed": True,
            "path": info.get("path", ""),
            "foundry": info.get("foundry", ""),
            "node": info.get("node", ""),
            "lib_files_count": len(lib_files),
            "device_count": device_count,
            "available_corners": sorted(corners),
            "installed_at": info.get("installed_at", ""),
        }


def create_manager(workspace: str = "") -> PDKLibraryManager:
    """Create and return a PDK library manager instance."""
    return PDKLibraryManager(workspace)


if __name__ == "__main__":
    # Demo / test
    print("Lumen PDK Library Manager")
    print("=" * 60)
    
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "install":
        name = sys.argv[2] if len(sys.argv) > 2 else ""
        path = sys.argv[3] if len(sys.argv) > 3 else ""
        
        manager = PDKLibraryManager()
        if path:
            success = manager.install_manager.register_local_pdk(name, path)
            if success:
                print(f"Registered PDK '{name}' at {path}")
                report = manager.get_health_report(name)
                print(f"  Devices: {report['device_count']}")
                print(f"  Corners: {report['available_corners']}")
                print(f"  .lib files: {report['lib_files_count']}")
            else:
                print(f"Failed to register PDK '{name}'")
        else:
            success = manager.install_manager.clone_pdk(name)
            if success:
                print(f"Cloned PDK '{name}'")
    
    elif len(sys.argv) > 1 and sys.argv[1] == "status":
        manager = PDKLibraryManager()
        installed = manager.install_manager.get_installed_pdks()
        if installed:
            print("Installed PDKs:")
            for name, info in installed.items():
                print(f"  {name}: {info.get('display_name', '')}")
                print(f"    Path: {info.get('path', '')}")
                print(f"    .lib files: {len(info.get('lib_files', []))}")
        else:
            print("No PDKs installed. Use 'install' command to add one.")