"""
LumenStudio - PDK Model Parser

Parses SPICE model libraries (.lib).
Extracts device definitions, corners, and model parameters.
"""
import os
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

from lumen.pdk.registry import PDKDevice, PDKCorner, DeviceCategory, PDKParameter


@dataclass
class ModelDefinition:
    """A parsed SPICE model definition."""
    name: str
    model_type: str
    parameters: Dict[str, str]
    description: str = ""


class ModelParser:
    """
    Parses SPICE model library files.
    
    Handles:
    - .MODEL statements (primitive devices)
    - .SUBCKT definitions (subcircuits)
    - .LIB sections (corners)
    - .INCLUDE references
    """
    
    MODEL_TYPE_MAP = {
        "NMOS": DeviceCategory.MOSFET,
        "PMOS": DeviceCategory.MOSFET,
        "NJF": DeviceCategory.MOSFET,
        "PJF": DeviceCategory.MOSFET,
        "NPN": DeviceCategory.BJT,
        "PNP": DeviceCategory.BJT,
        "D": DeviceCategory.DIODE,
        "DIO": DeviceCategory.DIODE,
        "RES": DeviceCategory.RESISTOR,
        "CAP": DeviceCategory.CAPACITOR,
        "IND": DeviceCategory.INDUCTOR,
    }
    
    PREFIX_MAP = {
        DeviceCategory.MOSFET: "M",
        DeviceCategory.BJT: "Q",
        DeviceCategory.DIODE: "D",
        DeviceCategory.RESISTOR: "R",
        DeviceCategory.CAPACITOR: "C",
        DeviceCategory.INDUCTOR: "L",
    }
    
    def __init__(self):
        self._models: List[ModelDefinition] = []
        self._subckts: Dict[str, Dict] = {}
        self._corners: List[PDKCorner] = []
    
    def parse_file(self, filepath: str) -> Tuple[List[ModelDefinition], List[PDKCorner]]:
        """
        Parse a SPICE model file.
        
        Returns:
            Tuple of (model definitions, corner definitions)
        """
        if not os.path.isfile(filepath):
            return [], []
        
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            return [], []
        
        # Remove comments
        content = self._strip_comments(content)
        
        self._models = []
        self._subckts = {}
        self._corners = []
        
        lines = content.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue
            
            line_upper = line.upper()
            
            if line_upper.startswith(".SUBCKT"):
                subckt_lines, i = self._extract_block(lines, i)
                self._parse_subckt(subckt_lines)
            elif line_upper.startswith(".LIB"):
                corner = self._parse_lib_section(line)
                if corner:
                    self._corners.append(corner)
                i += 1
            elif line_upper.startswith(".MODEL"):
                model = self._parse_model(line)
                if model:
                    self._models.append(model)
                i += 1
            elif line_upper.startswith(".ENDS"):
                i += 1
            else:
                i += 1
        
        return self._models, self._corners
    
    def _strip_comments(self, content: str) -> str:
        """Remove SPICE comments from content."""
        lines = content.split("\n")
        cleaned = []
        
        for line in lines:
            stripped = line.strip()
            # Skip full-line comments
            if stripped.startswith("*") and not stripped.startswith(".MODEL"):
                continue
            # Remove trailing comments
            if ";" in line:
                line = line.split(";")[0]
            cleaned.append(line)
        
        return "\n".join(cleaned)
    
    def _extract_block(self, lines: List[str], start: int) -> Tuple[List[str], int]:
        """Extract a block until .ENDS."""
        block = [lines[start]]
        i = start + 1
        depth = 1
        
        while i < len(lines) and depth > 0:
            line = lines[i]
            line_upper = line.strip().upper()
            
            if line_upper.startswith(".SUBCKT"):
                depth += 1
            elif line_upper.startswith(".ENDS"):
                depth -= 1
            
            if depth > 0:
                block.append(line)
            i += 1
        
        return block, i
    
    def _parse_model(self, line: str) -> Optional[ModelDefinition]:
        """
        Parse a .MODEL statement.
        
        Format: .MODEL model_name type (param1=val1 param2=val2 ...)
        """
        match = re.match(
            r'\.MODEL\s+(\S+)\s+(\S+)(?:\s*\(([^)]*)\))?',
            line, re.IGNORECASE
        )
        if not match:
            return None
        
        model_name = match.group(1)
        model_type = match.group(2).upper()
        params_str = match.group(3) or ""
        
        params = self._extract_params(params_str)
        
        return ModelDefinition(
            name=model_name,
            model_type=model_type,
            parameters=params,
            description=f"{model_type} model",
        )
    
    def _parse_subckt(self, lines: List[str]):
        """Parse a .SUBCKT definition."""
        first = lines[0].strip()
        match = re.match(r'\.SUBCKT\s+(\S+)\s+(.*)', first, re.IGNORECASE)
        if not match:
            return
        
        sub_name = match.group(1)
        rest = match.group(2).strip()
        
        # Extract pins
        pin_names = rest.split()[:20]  # Limit to 20 pins
        
        # Extract parameters if present
        params = {}
        if "PARAMS:" in rest.upper():
            parts = rest.upper().split("PARAMS:")
            param_str = parts[1] if len(parts) > 1 else ""
            params = self._extract_params(param_str)
        
        self._subckts[sub_name] = {
            "pins": pin_names,
            "params": params,
        }
    
    def _parse_lib_section(self, line: str) -> Optional[PDKCorner]:
        """Parse a .LIB section to extract corner info."""
        match = re.match(r'\.LIB\s+"?([^"\s]+)"?\s+(\w+)', line, re.IGNORECASE)
        if not match:
            return None
        
        # lib_path = match.group(1)
        corner_name = match.group(2)
        
        return PDKCorner(
            name=corner_name,
            description=f"Corner from model library",
            temperature=25.0,
        )
    
    def _extract_params(self, params_str: str) -> Dict[str, str]:
        """Extract parameter name=value pairs."""
        params = {}
        if not params_str:
            return params
        
        # Match name=value patterns
        pattern = r'(\w+)\s*=\s*([^\s)]+)'
        for match in re.finditer(pattern, params_str):
            params[match.group(1)] = match.group(2).strip()
        
        return params
    
    def create_pdk_devices(self) -> List[PDKDevice]:
        """Create PDKDevice objects from parsed models."""
        devices = []
        
        # Convert models to devices
        for model in self._models:
            category = self.MODEL_TYPE_MAP.get(
                model.model_type, DeviceCategory.OTHER
            )
            prefix = self.PREFIX_MAP.get(category, "X")
            
            # Create parameters
            parameters = []
            for name, value in model.parameters.items():
                parameters.append(PDKParameter(name, value))
            
            device = PDKDevice(
                name=model.name,
                category=category,
                prefix=prefix,
                model=model.name,
                description=model.description,
                parameters=parameters,
            )
            devices.append(device)
        
        # Convert subcircuits to devices
        for name, subckt in self._subckts.items():
            parameters = []
            for param_name, default in subckt.get("params", {}).items():
                parameters.append(PDKParameter(param_name, str(default)))
            
            device = PDKDevice(
                name=name,
                category=DeviceCategory.OTHER,
                prefix="X",
                model=name,
                description=f"Subcircuit: {name}",
                parameters=parameters,
            )
            devices.append(device)
        
        return devices


def load_model_library(filepath: str) -> Tuple[List[PDKDevice], List[PDKCorner]]:
    """
    Load models from a SPICE library file.
    
    Args:
        filepath: Path to .lib file
        
    Returns:
        Tuple of (devices, corners)
    """
    parser = ModelParser()
    models, corners = parser.parse_file(filepath)
    
    # Create PDK devices from models
    devices = parser.create_pdk_devices()
    
    return devices, corners


def scan_pdk_models(pdk_path: str) -> Dict[str, List[PDKDevice]]:
    """
    Scan a PDK directory for all model files.
    
    Args:
        pdk_path: Path to PDK root directory
        
    Returns:
        Dict mapping file paths to device lists
    """
    results = {}
    path = Path(pdk_path)
    
    # Look for model files in common locations
    patterns = [
        "*.lib",
        "models/*.lib",
        "libs.tech/ngspice/models/*.lib",
        "spice/*.lib",
    ]
    
    for pattern in patterns:
        for filepath in path.glob(pattern):
            try:
                devices, _ = load_model_library(str(filepath))
                if devices:
                    results[str(filepath)] = devices
            except Exception:
                continue
    
    return results
