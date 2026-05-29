"""Canonical access layer for PDK registry instances."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

from lumen.core.pdk_unified import PDKRegistry


_registry_cache: Dict[str, PDKRegistry] = {}


def resolve_workspace(workspace: str = "") -> str:
    """Resolve a stable workspace path for PDK operations."""
    if workspace:
        return str(Path(workspace).expanduser().resolve())
    env_workspace = os.environ.get("LUMEN_WORKSPACE", "").strip()
    if env_workspace:
        return str(Path(env_workspace).expanduser().resolve())
    return str((Path.home() / "LumenWorkspace").resolve())


def get_registry(workspace: str = "") -> PDKRegistry:
    """Return a cached PDK registry bound to the resolved workspace."""
    key = resolve_workspace(workspace)
    reg = _registry_cache.get(key)
    if reg is None:
        reg = PDKRegistry(key)
        _registry_cache[key] = reg
    return reg


def clear_registry_cache(workspace: str = "") -> None:
    """Clear one cached registry or all of them."""
    if workspace:
        _registry_cache.pop(resolve_workspace(workspace), None)
        return
    _registry_cache.clear()
