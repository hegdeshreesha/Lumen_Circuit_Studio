"""Batch entrypoint for run-plan execution."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lumen.core.database import LibraryDatabase
from lumen.core.ade_engine import ADESession
from lumen.core.run_plan import RunPlan, RunPlanExecutor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Lumen ADE plans in batch mode.")
    parser.add_argument("--workspace", required=True, help="Workspace path")
    parser.add_argument("--library", required=True, help="Top library")
    parser.add_argument("--cell", required=True, help="Top cell")
    parser.add_argument("--plan", required=True, help="Run-plan JSON path")
    parser.add_argument("--out", default="", help="Optional output summary JSON")
    args = parser.parse_args(argv)

    with open(args.plan, "r", encoding="utf-8") as f:
        raw = json.load(f)
    plan = RunPlan(
        name=raw.get("name", "batch_plan"),
        analyses=raw.get("analyses", []),
        corners=raw.get("corners", []),
        variables=raw.get("variables", {}),
        simulator=raw.get("simulator", "GSPICE"),
        timeout=int(raw.get("timeout", 300)),
        threads=int(raw.get("threads", 4)),
    )
    db = LibraryDatabase(args.workspace)
    session = ADESession(db, args.library, args.cell, "schematic")
    runs = RunPlanExecutor(session).run(plan)
    summary = {
        "plan": plan.name,
        "runs": len(runs),
        "passes": sum(1 for r in runs if r.success),
        "fails": sum(1 for r in runs if not r.success),
        "run_ids": [r.run_id for r in runs],
    }
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
    print(json.dumps(summary))
    return 0 if summary["fails"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

