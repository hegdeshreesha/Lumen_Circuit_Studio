"""
Lumen Circuit Studio — Plugin Architecture

Modular plugin system supporting:
- Runtime discovery and loading
- Manifest-driven registration
- API surface for database, UI, and simulator hooks
- Hot-reload for development

Plugin manifest schema (plugin.yaml):
    name: my_plugin
    version: "1.0.0"
    author: "..."
    description: "..."
    entry_point: "my_plugin.main:register"
    hooks:
      - editor
      - pdk_handler
      - simulator_backend
      - ai_module
      - menu_item
      - dock_widget
"""
import os
import sys
import json
import importlib
import importlib.util
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class PluginManifest:
    name: str
    version: str
    author: str = ""
    description: str = ""
    entry_point: str = ""
    hooks: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    path: str = ""
    enabled: bool = True


class PluginAPI:
    """
    Public API surface exposed to plugins.
    Plugins receive an instance of this class at registration time.
    """
    def __init__(self, db, main_window=None):
        self._db = db
        self._main_window = main_window
        self._menu_items: list[tuple[str, Callable]] = []
        self._dock_widgets: list[tuple[str, object]] = []
        self._commands: list[tuple[str, Callable, str]] = []

    @property
    def db(self):
        return self._db

    @property
    def main_window(self):
        return self._main_window

    def register_menu(self, path: str, callback: Callable, shortcut: str = ""):
        """Register a menu item at path like 'File/Export/PDF'."""
        self._menu_items.append((path, callback, shortcut))

    def register_dock_widget(self, title: str, widget_factory: Callable):
        """Register a dock widget factory."""
        self._dock_widgets.append((title, widget_factory))

    def register_command(self, cmd_id: str, callback: Callable, description: str = ""):
        """Register a command that can be invoked via command palette or bindkey."""
        self._commands.append((cmd_id, callback, description))

    def open_cellview(self, library: str, cell: str, view: str):
        """Request the main window to open a cellview."""
        if self._main_window and hasattr(self._main_window, 'open_cellview'):
            self._main_window.open_cellview(library, cell, view)

    def get_menu_items(self) -> list:
        return list(self._menu_items)

    def get_dock_widgets(self) -> list:
        return list(self._dock_widgets)

    def get_commands(self) -> list:
        return list(self._commands)


class PluginManager:
    """Discovers, loads, and manages plugins."""

    def __init__(self, plugin_dirs: Optional[list[str]] = None):
        self._plugins: dict[str, PluginManifest] = {}
        self._loaded: dict[str, object] = {}
        self._plugin_dirs: list[Path] = []

        default_dirs = [
            Path.home() / ".lumen" / "plugins",
            Path(__file__).parent.parent / "plugins",
        ]
        for d in default_dirs:
            d.mkdir(parents=True, exist_ok=True)
            self._plugin_dirs.append(d)

        if plugin_dirs:
            for p in plugin_dirs:
                self._plugin_dirs.append(Path(p))

    def discover(self) -> list[PluginManifest]:
        """Scan plugin directories for manifests."""
        found = []
        for directory in self._plugin_dirs:
            if not directory.exists():
                continue
            for entry in directory.iterdir():
                if entry.is_dir():
                    manifest = self._load_manifest(entry)
                    if manifest:
                        found.append(manifest)
        return found

    def _load_manifest(self, directory: Path) -> Optional[PluginManifest]:
        """Load plugin.yaml or plugin.json from a directory."""
        for filename in ("plugin.yaml", "plugin.json"):
            manifest_path = directory / filename
            if manifest_path.exists():
                try:
                    if filename.endswith(".yaml"):
                        import yaml
                        with open(manifest_path, "r") as f:
                            data = yaml.safe_load(f)
                    else:
                        with open(manifest_path, "r") as f:
                            data = json.load(f)
                    return PluginManifest(
                        name=data.get("name", directory.name),
                        version=data.get("version", "0.0.0"),
                        author=data.get("author", ""),
                        description=data.get("description", ""),
                        entry_point=data.get("entry_point", ""),
                        hooks=data.get("hooks", []),
                        dependencies=data.get("dependencies", []),
                        path=str(directory),
                        enabled=data.get("enabled", True),
                    )
                except Exception:
                    pass
        return None

    def load(self, manifest: PluginManifest, api: PluginAPI) -> bool:
        """Load and register a plugin."""
        if manifest.name in self._loaded:
            return True
        if not manifest.enabled:
            return False

        # Add plugin directory to path
        plugin_path = Path(manifest.path)
        if str(plugin_path) not in sys.path:
            sys.path.insert(0, str(plugin_path))

        try:
            if manifest.entry_point:
                module_name, func_name = manifest.entry_point.split(":")
                module = importlib.import_module(module_name)
                register_func = getattr(module, func_name)
                register_func(api)

            self._plugins[manifest.name] = manifest
            self._loaded[manifest.name] = api
            return True
        except Exception as e:
            print(f"[PluginManager] Failed to load {manifest.name}: {e}")
            return False

    def get_loaded(self) -> list[str]:
        return list(self._loaded.keys())

    def unload(self, name: str):
        if name in self._loaded:
            del self._loaded[name]
        if name in self._plugins:
            del self._plugins[name]

    def reload(self, name: str, api: PluginAPI) -> bool:
        self.unload(name)
        manifest = self._plugins.get(name)
        if manifest:
            return self.load(manifest, api)
        return False
