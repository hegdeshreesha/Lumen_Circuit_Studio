"""Persistent simulation results and comparison helpers."""
from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


@dataclass
class RunManifest:
    run_id: str
    simulator: str
    design: str
    corner: str
    analysis: str
    seed: int
    deck_hash: str
    model_hash: str
    elapsed_time: float
    success: bool


class ResultsStore:
    """Workspace-scoped results ledger."""

    FILE_NAME = "results_db.json"

    def __init__(self, workspace: str):
        self.workspace = Path(workspace)
        self.root = self.workspace / "runs"
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / self.FILE_NAME
        self._db = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"runs": [], "manifests": []}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("runs", [])
                data.setdefault("manifests", [])
                return data
        except Exception:
            pass
        return {"runs": [], "manifests": []}

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._db, f, indent=2)

    def record(self, run: dict[str, Any], manifest: RunManifest) -> None:
        self._db["runs"].append(run)
        self._db["manifests"].append(asdict(manifest))
        self._save()

    def manifests(self) -> list[dict[str, Any]]:
        return list(self._db.get("manifests", []))

    def compare(self, run_id_a: str, run_id_b: str) -> dict[str, Any]:
        rows = self._db.get("runs", [])
        a = next((r for r in rows if str(r.get("run_id")) == run_id_a), None)
        b = next((r for r in rows if str(r.get("run_id")) == run_id_b), None)
        if a is None or b is None:
            return {"ok": False, "error": "Run id not found."}
        result = {
            "ok": True,
            "run_a": run_id_a,
            "run_b": run_id_b,
            "success_changed": bool(a.get("success")) != bool(b.get("success")),
            "elapsed_delta": float(b.get("elapsed_time", 0.0)) - float(a.get("elapsed_time", 0.0)),
            "waveform_signals_a": sorted((a.get("waveforms") or {}).keys()),
            "waveform_signals_b": sorted((b.get("waveforms") or {}).keys()),
        }
        return result


def hash_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def hash_files(paths: list[str]) -> str:
    h = hashlib.sha256()
    for raw in sorted(set(paths)):
        p = Path(raw)
        h.update(str(p).encode("utf-8"))
        if p.exists() and p.is_file():
            try:
                with open(p, "rb") as f:
                    h.update(f.read())
            except OSError:
                continue
    return h.hexdigest()

