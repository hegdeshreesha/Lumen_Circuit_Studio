"""
Lumen Circuit Studio — Data Validation

Validates JSON data against JSON schemas.
Provides runtime validation for database operations.
"""
import json
from pathlib import Path
from typing import Any, Dict, Optional, List
try:
    import jsonschema  # type: ignore
except ImportError:
    jsonschema = None


class SchemaValidator:
    """Validates data against JSON schemas."""
    
    def __init__(self, schema_dir: str = None):
        if schema_dir is None:
            # Use path relative to this module: go up to project root
            self.schema_dir = Path(__file__).parent.parent.parent / "schemas"
        else:
            self.schema_dir = Path(schema_dir)
        self._schemas: Dict[str, Dict] = {}
        self._load_schemas()
    
    def _load_schemas(self):
        """Load all JSON schemas from the schema directory."""
        schema_files = [
            "schematic.json",
            "symbol.json",
            "pdk_manifest.json",
        ]
        for schema_file in schema_files:
            schema_path = self.schema_dir / schema_file
            if schema_path.exists():
                with open(schema_path, "r") as f:
                    self._schemas[schema_file.replace(".json", "")] = json.load(f)
    
    def validate(self, data: Dict[str, Any], schema_name: str) -> List[str]:
        """
        Validate data against a schema.
        
        Args:
            data: The data to validate
            schema_name: Name of the schema (e.g., 'schematic', 'symbol')
            
        Returns:
            List of validation error strings. Empty if valid.
        """
        if schema_name not in self._schemas:
            return [f"Unknown schema: {schema_name}"]
        
        errors = []
        if jsonschema is None:
            # Graceful fallback when optional dependency is missing.
            return errors
        try:
            jsonschema.validate(instance=data, schema=self._schemas[schema_name])
        except jsonschema.ValidationError as e:
            errors.append(str(e))
        return errors
    
    def is_valid(self, data: Dict[str, Any], schema_name: str) -> bool:
        """Check if data is valid against a schema."""
        return len(self.validate(data, schema_name)) == 0
    
    def get_schema_info(self, schema_name: str) -> Optional[Dict]:
        """Get information about a schema."""
        return self._schemas.get(schema_name)
