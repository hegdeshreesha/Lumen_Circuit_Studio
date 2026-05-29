"""Validation helpers for system/file-backed components."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ImportValidationResult:
    ok: bool
    resolved_path: str = ""
    errors: list[str] = field(default_factory=list)


def resolve_component_file(file_value: str, workspace: str) -> Path:
    """Resolve a component file relative to the project workspace."""
    candidate = Path(str(file_value).strip()).expanduser()
    if candidate.is_absolute():
        return candidate
    return (Path(workspace).resolve() / candidate).resolve()


def validate_component_file(file_value: str, workspace: str, allowed_suffixes: tuple[str, ...]) -> ImportValidationResult:
    if not file_value:
        return ImportValidationResult(ok=False, errors=["Missing required file path parameter."])
    path = resolve_component_file(file_value, workspace)
    errors: list[str] = []
    if allowed_suffixes and path.suffix.lower() not in tuple(s.lower() for s in allowed_suffixes):
        errors.append(
            f"File '{path}' has unsupported extension '{path.suffix}'. "
            f"Expected one of: {', '.join(allowed_suffixes)}."
        )
    if not path.exists():
        errors.append(f"Referenced file does not exist: {path}")
    elif not path.is_file():
        errors.append(f"Referenced path is not a file: {path}")
    return ImportValidationResult(ok=not errors, resolved_path=str(path), errors=errors)


def validate_system_component(spice_model: str, params: dict, workspace: str) -> ImportValidationResult | None:
    """Validate import-backed models and return a resolved file path when relevant."""
    model = (spice_model or "").upper()
    if model == "SPFILE":
        return validate_component_file(
            str(params.get("File", "")).strip(),
            workspace,
            (".s1p", ".s2p", ".s3p", ".s4p", ".s5p", ".s6p", ".s7p", ".s8p", ".s9p", ".s10p", ".s11p", ".s12p", ".s13p", ".s14p", ".s15p", ".s16p"),
        )
    if model in ("SPICE_NETLIST",):
        return validate_component_file(
            str(params.get("File", "")).strip(),
            workspace,
            (".sp", ".cir", ".spi", ".net", ".spice"),
        )
    if model in ("SUB_FILE",):
        return validate_component_file(
            str(params.get("File", "")).strip(),
            workspace,
            (".sch", ".json", ".lumen.json"),
        )
    if model in ("VHDL_FILE",):
        return validate_component_file(
            str(params.get("File", "")).strip(),
            workspace,
            (".vhd", ".vhdl"),
        )
    if model in ("VERILOG_FILE",):
        return validate_component_file(
            str(params.get("File", "")).strip(),
            workspace,
            (".v", ".sv"),
        )
    return None

