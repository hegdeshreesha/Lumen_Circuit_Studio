"""Config-view style hierarchy binding for schematic netlisting."""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path


@dataclass
class ViewBinding:
    library: str
    cell: str
    view: str = "schematic"


@dataclass
class ConfigView:
    name: str
    top_library: str
    top_cell: str
    default_view: str = "schematic"
    bindings: list[ViewBinding] = field(default_factory=list)

    def resolve(self, library: str, cell: str) -> str:
        for b in self.bindings:
            if b.library == library and b.cell == cell:
                return b.view
        return self.default_view


class ConfigViewManager:
    """Persist and resolve config-views in workspace."""

    FILE_NAME = "config_views.json"

    def __init__(self, workspace: str):
        self.workspace = Path(workspace)
        self.root = self.workspace / "runs"
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / self.FILE_NAME
        self._db = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"configs": []}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                raw.setdefault("configs", [])
                return raw
        except Exception:
            pass
        return {"configs": []}

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._db, f, indent=2)

    def upsert(self, cfg: ConfigView):
        rows = self._db.get("configs", [])
        rows = [r for r in rows if r.get("name") != cfg.name]
        payload = asdict(cfg)
        payload["bindings"] = [asdict(b) for b in cfg.bindings]
        rows.append(payload)
        self._db["configs"] = rows
        self._save()

    def get(self, name: str) -> ConfigView | None:
        for row in self._db.get("configs", []):
            if row.get("name") != name:
                continue
            bindings = [ViewBinding(**b) for b in row.get("bindings", [])]
            return ConfigView(
                name=row.get("name", ""),
                top_library=row.get("top_library", ""),
                top_cell=row.get("top_cell", ""),
                default_view=row.get("default_view", "schematic"),
                bindings=bindings,
            )
        return None

