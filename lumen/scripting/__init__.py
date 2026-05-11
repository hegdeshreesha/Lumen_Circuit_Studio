"""
LumenStudio Scripting System

Every GUI action generates a command that is recorded and can be replayed.
Provides Python API for all operations.
"""
from lumen.scripting.interpreter import ScriptInterpreter, execute_command
from lumen.scripting.recorder import ActionRecorder, get_recorder
from lumen.scripting.api import (
    # Library operations
    create_library, delete_library, rename_library, get_libraries,
    # Cell operations
    create_cell, delete_cell, get_cells,
    # View operations
    save_view, load_view, get_views,
    # PDK operations
    set_pdk, get_pdk_devices, get_active_pdk,
    # Schematic operations
    place_component, draw_wire, add_net_label,
    # Simulation operations
    run_simulation, get_waveforms,
)

__all__ = [
    "ScriptInterpreter",
    "execute_command",
    "ActionRecorder",
    "get_recorder",
    # API functions
    "create_library",
    "set_pdk",
    "place_component",
    "run_simulation",
]