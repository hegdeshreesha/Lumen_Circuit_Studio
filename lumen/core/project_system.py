"""Project/workspace management for Lumen Circuit Studio."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


PROJECT_META_FILENAME = ".lumen_project.json"


@dataclass
class ProjectInfo:
    """Minimal project metadata persisted in global state."""
    name: str
    path: str
    created: float
    modified: float
    last_opened: float


class ProjectSystem:
    """Owns project metadata, recents, and autosave/recovery payloads."""

    def __init__(self, state_path: str = ""):
        default_state = Path.home() / ".lumen" / "project_state.json"
        self.state_path = Path(state_path).expanduser() if state_path else default_state
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load_state()

    def default_workspace(self) -> str:
        """Fallback workspace when no explicit project is selected."""
        return str((Path.home() / "LumenWorkspace").resolve())

    def default_projects_root(self) -> str:
        return str((Path.home() / "LumenProjects").resolve())

    def get_current_project(self) -> ProjectInfo | None:
        raw = self._state.get("current_project")
        if not isinstance(raw, dict):
            return None
        try:
            return ProjectInfo(**raw)
        except TypeError:
            return None

    def get_current_workspace(self) -> str:
        project = self.get_current_project()
        if project and project.path:
            return str(Path(project.path).expanduser().resolve())
        return self.default_workspace()

    def list_recent_projects(self, limit: int = 10) -> list[ProjectInfo]:
        rows = self._state.get("recent_projects", [])
        items: list[ProjectInfo] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                item = ProjectInfo(**row)
            except TypeError:
                continue
            if Path(item.path).exists():
                items.append(item)
        items.sort(key=lambda p: p.last_opened, reverse=True)
        return items[: max(1, limit)]

    def create_project(self, name: str, parent_dir: str = "") -> ProjectInfo:
        """Create a project directory with a usable workspace skeleton."""
        cleaned = (name or "").strip()
        if not cleaned:
            raise ValueError("Project name is required.")

        root = Path(parent_dir).expanduser() if parent_dir else Path(self.default_projects_root())
        root.mkdir(parents=True, exist_ok=True)
        project_dir = (root / cleaned).resolve()
        project_dir.mkdir(parents=True, exist_ok=True)

        self._ensure_workspace_layout(project_dir)
        now = time.time()
        info = ProjectInfo(
            name=cleaned,
            path=str(project_dir),
            created=now,
            modified=now,
            last_opened=now,
        )
        self._write_project_metadata(info)
        self._set_current(info)
        return info

    def open_project(self, project_path: str) -> ProjectInfo:
        """Open an existing project path, creating metadata if needed."""
        if not project_path:
            raise ValueError("Project path is required.")
        project_dir = Path(project_path).expanduser().resolve()
        if not project_dir.exists() or not project_dir.is_dir():
            raise ValueError("Selected project folder does not exist.")

        self._ensure_workspace_layout(project_dir)
        info = self._read_project_metadata(project_dir)
        now = time.time()
        if info is None:
            info = ProjectInfo(
                name=project_dir.name,
                path=str(project_dir),
                created=now,
                modified=now,
                last_opened=now,
            )
        else:
            info.last_opened = now
            info.modified = now

        self._write_project_metadata(info)
        self._set_current(info)
        return info

    def save_autosave(self, payload: dict[str, Any], project_path: str = "") -> str:
        autosave_path = self.autosave_path(project_path)
        autosave_path.parent.mkdir(parents=True, exist_ok=True)
        data = dict(payload)
        data["timestamp"] = time.time()
        with open(autosave_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return str(autosave_path)

    def load_autosave(self, project_path: str = "") -> dict[str, Any] | None:
        autosave_path = self.autosave_path(project_path)
        if not autosave_path.exists():
            return None
        try:
            with open(autosave_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def clear_autosave(self, project_path: str = "") -> None:
        autosave_path = self.autosave_path(project_path)
        if autosave_path.exists():
            try:
                autosave_path.unlink()
            except OSError:
                pass

    def has_recovery_data(self, project_path: str = "") -> bool:
        data = self.load_autosave(project_path)
        return isinstance(data, dict) and bool(data.get("dirty", False))

    def autosave_path(self, project_path: str = "") -> Path:
        workspace = Path(project_path).expanduser().resolve() if project_path else Path(self.get_current_workspace())
        return workspace / ".lumen" / "autosave_session.json"

    def _ensure_workspace_layout(self, workspace: Path) -> None:
        for rel in ("runs", "logs", "scratch", "exports", ".lumen"):
            (workspace / rel).mkdir(parents=True, exist_ok=True)

    def _project_meta_path(self, project_dir: Path) -> Path:
        return project_dir / PROJECT_META_FILENAME

    def _read_project_metadata(self, project_dir: Path) -> ProjectInfo | None:
        meta_path = self._project_meta_path(project_dir)
        if not meta_path.exists():
            return None
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                row = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(row, dict):
            return None
        try:
            return ProjectInfo(**row)
        except TypeError:
            return None

    def _write_project_metadata(self, info: ProjectInfo) -> None:
        meta_path = self._project_meta_path(Path(info.path))
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(asdict(info), f, indent=2)

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"current_project": None, "recent_projects": []}
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                raw.setdefault("current_project", None)
                raw.setdefault("recent_projects", [])
                return raw
        except (OSError, json.JSONDecodeError):
            pass
        return {"current_project": None, "recent_projects": []}

    def _save_state(self) -> None:
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(self._state, f, indent=2)

    def _set_current(self, info: ProjectInfo) -> None:
        self._state["current_project"] = asdict(info)
        recents = [row for row in self._state.get("recent_projects", []) if isinstance(row, dict)]
        recents = [row for row in recents if Path(str(row.get("path", ""))).resolve() != Path(info.path).resolve()]
        recents.insert(0, asdict(info))
        self._state["recent_projects"] = recents[:20]
        self._save_state()

