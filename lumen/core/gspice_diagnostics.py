"""
Lumen Circuit Studio — Explainable Simulation Diagnostic Engine

Parses simulator logs (GSPICE, Ngspice, Xyce) to identify root causes of
simulation failures (singular matrix, floating nodes, missing compact models,
convergence breakdowns) and maps them back to schematic nets/instances.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class DiagnosticIssue:
    severity: str  # "ERROR", "WARNING", "HINT"
    category: str  # "SINGULAR_MATRIX", "FLOATING_NODE", "MISSING_MODEL", "NON_CONVERGENCE", "SYNTAX_ERROR"
    title: str
    message: str
    affected_nodes: List[str] = field(default_factory=list)
    affected_instances: List[str] = field(default_factory=list)
    suggested_action: str = ""


@dataclass
class DiagnosticReport:
    simulator: str
    success: bool
    summary: str
    issues: List[DiagnosticIssue] = field(default_factory=list)

    def is_clean(self) -> bool:
        return len(self.issues) == 0


class GspiceDiagnosticParser:
    """Diagnostic parser for GSPICE, Ngspice, and Xyce log outputs."""

    def __init__(self):
        # Patterns for GSPICE & Spice log parsing
        self.singular_matrix_re = re.compile(
            r"(?:singular matrix|matrix is singular|singular|pivot|zero pivot)[^:\n]*[:\s]+(?:at node|node)?\s*([a-zA-Z0-9_\.\#\:\/]+)?",
            re.IGNORECASE,
        )
        self.floating_node_re = re.compile(
            r"(?:floating node|unconnected node|no DC path|node has no dc path to ground)[^:\n]*[:\s]+([a-zA-Z0-9_\.\#\:\/]+)?",
            re.IGNORECASE,
        )
        self.missing_model_re = re.compile(
            r"(?:model\s+([a-zA-Z0-9_]+)\s+not found|unknown model|unable to load osdi|osdi plugin missing|could not open library)",
            re.IGNORECASE,
        )
        self.timestep_small_re = re.compile(
            r"(?:timestep too small|time step too small|doAnalyses: TSTEP|iteration limit reached)",
            re.IGNORECASE,
        )

    def parse_log(self, simulator: str, log_text: str, stderr_text: str = "") -> DiagnosticReport:
        """Parse stdout and stderr logs to produce an explainable diagnostic report."""
        combined_text = f"{log_text}\n{stderr_text}"
        issues: List[DiagnosticIssue] = []

        # 1. Singular Matrix Check
        for line in combined_text.splitlines():
            if "singular" in line.lower() or "pivot" in line.lower():
                match = self.singular_matrix_re.search(line)
                node = match.group(1) if (match and match.group(1)) else ""
                affected = [node] if node else []
                issues.append(
                    DiagnosticIssue(
                        severity="ERROR",
                        category="SINGULAR_MATRIX",
                        title="Singular Matrix / Floating Node Detected",
                        message=line.strip(),
                        affected_nodes=affected,
                        suggested_action=(
                            f"Check node '{node}' for missing DC path to GND, "
                            "unconnected bulk terminals, or floating capacitor nodes."
                            if node else "Check for floating nodes or missing DC paths to ground."
                        ),
                    )
                )

            # 2. Missing Compact Model Check
            elif "model" in line.lower() and ("not found" in line.lower() or "unknown" in line.lower() or "osdi" in line.lower()):
                match = self.missing_model_re.search(line)
                model_name = match.group(1) if (match and match.lastindex) else ""
                issues.append(
                    DiagnosticIssue(
                        severity="ERROR",
                        category="MISSING_MODEL",
                        title="Missing PDK / Compact Model",
                        message=line.strip(),
                        affected_instances=[],
                        suggested_action=(
                            f"Verify PDK model includes for model '{model_name}'. "
                            "Ensure OpenVAF/OSDI plugins are compiled and available in the run directory."
                        ),
                    )
                )

            # 3. Non-convergence / Timestep Check
            elif "timestep" in line.lower() or "iteration limit" in line.lower():
                issues.append(
                    DiagnosticIssue(
                        severity="ERROR",
                        category="NON_CONVERGENCE",
                        title="Transient Non-Convergence",
                        message=line.strip(),
                        suggested_action=(
                            "Try adding UIC to transient analysis, relaxed reltol/abstol, "
                            "or enable pseudo-transient / gmin stepping in SimENV."
                        ),
                    )
                )

        success = not any(i.severity == "ERROR" for i in issues)
        summary = (
            "Simulation completed cleanly with no structural diagnostic issues."
            if success
            else f"Simulation failed with {len(issues)} diagnostic issue(s)."
        )

        return DiagnosticReport(
            simulator=simulator,
            success=success,
            summary=summary,
            issues=issues,
        )
