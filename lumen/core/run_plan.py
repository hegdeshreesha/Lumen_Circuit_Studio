"""ADE-XL style run plan abstraction and batch execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lumen.core.ade_engine import ADESession


@dataclass
class RunPlan:
    name: str
    analyses: list[dict[str, Any]] = field(default_factory=list)
    corners: list[dict[str, Any]] = field(default_factory=list)
    variables: dict[str, str] = field(default_factory=dict)
    simulator: str = "GSPICE"
    timeout: int = 300
    threads: int = 4


class RunPlanExecutor:
    """Execute run plans against an ADE session."""

    def __init__(self, session: ADESession):
        self.session = session

    def apply(self, plan: RunPlan):
        self.session.state.analyses.clear()
        self.session.state.corners.clear()
        self.session.state.design_variables.clear()
        self.session.set_simulator(plan.simulator)
        self.session.set_timeout(plan.timeout)
        self.session.set_threads(plan.threads)
        for k, v in plan.variables.items():
            self.session.set_design_variable(str(k), str(v))
        from lumen.core.ade_engine import AnalysisType
        for analysis in plan.analyses:
            atype = analysis.get("type", "OP")
            params = dict(analysis.get("params", {}))
            self.session.add_analysis(AnalysisType[atype], **params)
        for c in plan.corners:
            self.session.add_corner(
                c.get("name", "corner"),
                float(c.get("temperature", 25.0)),
                float(c.get("voltage", 1.8)),
                c.get("process", "tt"),
            )
        self.session.set_corner_mode("all" if len(plan.corners) > 1 else "single")

    def run(self, plan: RunPlan):
        self.apply(plan)
        return self.session.run()

