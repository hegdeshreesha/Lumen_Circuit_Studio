"""Simulation Cockpit model/corner setup helpers."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
import math


@dataclass
class ModelDirective:
    """A resolved simulator model directive."""

    kind: str
    path: str
    section: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelDirective":
        return cls(
            kind=str(data.get("kind") or data.get("type") or "lib").lower(),
            path=str(data.get("path") or ""),
            section=str(data.get("section") or ""),
        )

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    def spice_line(self) -> str:
        kind = self.kind.lower()
        path = self.path
        if kind == "include":
            return f'.INCLUDE "{path}"'
        if kind == "gsdi":
            return f'.GSDI "{path}"'
        if self.section:
            return f'.LIB "{path}" {self.section}'
        return f'.LIB "{path}"'


@dataclass
class ModelEntry:
    """A model discovered in a model file."""

    name: str
    kind: str
    path: str
    section: str = ""
    device_type: str = ""
    pins: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DeviceModelBinding:
    """Simulation setup binding from a schematic instance to a model name."""

    instance: str
    model: str
    device: str = ""
    corner: str = ""
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeviceModelBinding":
        return cls(
            instance=str(data.get("instance") or ""),
            model=str(data.get("model") or ""),
            device=str(data.get("device") or ""),
            corner=str(data.get("corner") or ""),
            enabled=bool(data.get("enabled", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DeviceParameterSpec:
    """Normalized editable device parameter metadata."""

    name: str
    default: str = ""
    description: str = ""
    param_type: str = "string"
    display: str = ""
    unit: str = ""
    numeric: bool = False
    choices: list[str] = field(default_factory=list)
    min_value: float | None = None
    max_value: float | None = None
    read_only: bool = False
    callback: str = ""
    source: str = "symbol"

    def to_symbol_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "default": self.default,
            "description": self.description,
        }
        if self.display and self.display != self.name:
            data["display"] = self.display
        if self.unit:
            data["unit"] = self.unit
        if self.param_type:
            data["type"] = self.param_type
        if self.numeric:
            data["numeric"] = True
        if self.choices:
            data["enum"] = list(self.choices)
        if self.min_value is not None:
            data["min"] = self.min_value
        if self.max_value is not None:
            data["max"] = self.max_value
        if self.read_only:
            data["read_only"] = True
        if self.callback:
            data["callback"] = self.callback
        return data


def normalize_device_parameter_specs(symbol_data: dict[str, Any]) -> list[DeviceParameterSpec]:
    """Normalize symbol/CDF-style parameter records for editing and validation."""
    specs: list[DeviceParameterSpec] = []
    seen: set[str] = set()
    raw_params = symbol_data.get("parameters", []) if isinstance(symbol_data, dict) else []
    if isinstance(raw_params, dict):
        raw_params = [{"name": key, "default": value} for key, value in raw_params.items()]
    for raw in raw_params or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("param") or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        default = raw.get("default", raw.get("defValue", ""))
        choices = raw.get("enum", raw.get("choices", []))
        specs.append(DeviceParameterSpec(
            name=name,
            default=str(default if default is not None else ""),
            description=str(raw.get("description") or raw.get("desc") or ""),
            param_type=str(raw.get("type") or raw.get("param_type") or "string"),
            display=str(raw.get("display") or raw.get("display_name") or name),
            unit=str(raw.get("unit") or ""),
            numeric=bool(raw.get("numeric", raw.get("parseAsNumber", False))),
            choices=[str(item) for item in choices] if isinstance(choices, list) else [],
            min_value=raw.get("min", raw.get("min_value")),
            max_value=raw.get("max", raw.get("max_value")),
            read_only=bool(raw.get("read_only", raw.get("readOnly", raw.get("readonly", False)))),
            callback=str(raw.get("callback") or ""),
            source=str(raw.get("source") or "symbol"),
        ))
    return specs


def symbol_data_with_parameter_specs(symbol_data: dict[str, Any]) -> dict[str, Any]:
    """Return symbol data with normalized parameter dictionaries."""
    data = dict(symbol_data or {})
    data["parameters"] = [
        spec.to_symbol_dict()
        for spec in normalize_device_parameter_specs(data)
    ]
    return data


def apply_device_parameter_callbacks(
    symbol_data: dict[str, Any],
    params: dict[str, Any],
    changed: str = "",
) -> dict[str, str]:
    """Apply trusted, data-only CDF-style parameter callbacks."""
    updated = {str(key): str(value) for key, value in (params or {}).items()}
    specs = normalize_device_parameter_specs(symbol_data)
    spec_names = {spec.name for spec in specs}

    for spec in specs:
        callback = spec.callback.strip()
        if not callback:
            continue
        if callback.startswith("copy:"):
            source = callback.split(":", 1)[1].strip()
            if source in updated:
                updated[spec.name] = updated[source]

    if changed.lower() in {"w", "l", "ng", "nf", "m"} or not changed:
        if "ng" in updated and "nf" in spec_names and not updated.get("nf"):
            updated["nf"] = updated["ng"]
        if "nf" in updated and "ng" in spec_names and not updated.get("ng"):
            updated["ng"] = updated["nf"]
        if "m" in spec_names and not updated.get("m"):
            updated["m"] = "1"

    return updated


@dataclass
class CornerSetup:
    """A process/voltage/temperature corner and its model directives."""

    name: str
    temp: str = "25"
    vdd: str = "1.8"
    process: str = "tt"
    enabled: bool = True
    model_directives: list[ModelDirective] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CornerSetup":
        directives = [
            ModelDirective.from_dict(item)
            for item in data.get("model_directives", []) or []
            if isinstance(item, dict)
        ]
        return cls(
            name=str(data.get("name") or "corner"),
            temp=str(data.get("temp") or data.get("temperature") or "25"),
            vdd=str(data.get("vdd") or data.get("voltage") or "1.8"),
            process=str(data.get("process") or "tt"),
            enabled=bool(data.get("enabled", True)),
            model_directives=directives,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "temp": self.temp,
            "vdd": self.vdd,
            "process": self.process,
            "enabled": self.enabled,
            "model_directives": [d.to_dict() for d in self.model_directives],
        }


@dataclass
class PDKModelManifest:
    """A simulator-ready PDK model/corner setup."""

    pdk_name: str
    display_name: str = ""
    simulator: str = "GSPICE"
    model_directives: list[ModelDirective] = field(default_factory=list)
    corners: list[CornerSetup] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pdk_name": self.pdk_name,
            "display_name": self.display_name,
            "simulator": self.simulator,
            "model_directives": [directive.to_dict() for directive in self.model_directives],
            "corners": [corner.to_dict() for corner in self.corners],
        }


def build_pdk_model_manifest(pdk: Any, simulator: str = "GSPICE") -> PDKModelManifest:
    """Build a compact ADE-style model setup from discovered PDK metadata."""
    if not pdk:
        return PDKModelManifest("", simulator=simulator)
    pdk_name = str(getattr(pdk, "name", "") or "")
    model_files = _select_pdk_model_files(getattr(pdk, "model_files", []) or [], simulator)
    if pdk_name == "ihp_sg13g2":
        return _build_ihp_model_manifest(pdk, model_files, simulator)

    shared = [
        directive for directive in (
            _model_directive_for_pdk_file(model_file, "")
            for model_file in model_files
        )
        if directive
    ]
    corners = _generic_pdk_corners(pdk, model_files, shared)
    return PDKModelManifest(
        pdk_name=pdk_name,
        display_name=str(getattr(pdk, "display_name", "") or pdk_name),
        simulator=simulator,
        model_directives=shared,
        corners=corners,
    )


def _select_pdk_model_files(model_files: list[Any], simulator: str) -> list[Any]:
    files = list(model_files or [])
    if not files:
        return []
    sim = str(simulator or "").lower()
    if sim in {"gspice", "ngspice"}:
        preferred = [
            model_file for model_file in files
            if "ngspice" in str(getattr(model_file, "path", "")).replace("\\", "/").lower()
        ]
        if preferred:
            return preferred
    return files


def _model_directive_for_pdk_file(model_file: Any, section: str = "") -> ModelDirective | None:
    path = str(getattr(model_file, "path", "") or "")
    if not path:
        return None
    suffix = os.path.splitext(path)[1].lower()
    if suffix == ".lib":
        return ModelDirective("lib", path, section)
    if suffix == ".gsdi":
        return ModelDirective("gsdi", path, "")
    return ModelDirective("include", path, "")


def _generic_pdk_corners(pdk: Any, model_files: list[Any], shared: list[ModelDirective]) -> list[CornerSetup]:
    raw_corners = list(getattr(pdk, "corners", []) or [])
    if not raw_corners:
        sections = []
        for model_file in model_files:
            sections.extend(str(item) for item in getattr(model_file, "corners", []) or [])
        raw_corners = [type("Corner", (), {"name": section, "temperature": 25.0, "voltage": 1.8, "lib_section": section}) for section in sorted(set(sections))]
    corners: list[CornerSetup] = []
    for raw in raw_corners:
        section_hint = str(getattr(raw, "lib_section", "") or getattr(raw, "name", "") or "")
        process = _process_from_corner_name(section_hint)
        directives = _directives_for_corner(model_files, process, section_hint)
        corners.append(CornerSetup(
            name=str(getattr(raw, "name", "") or process or "corner"),
            temp=str(getattr(raw, "temperature", 25.0)),
            vdd=str(getattr(raw, "voltage", getattr(pdk, "supply_voltage", 1.8))),
            process=process or section_hint or "tt",
            model_directives=directives or list(shared),
        ))
    return corners


def _directives_for_corner(model_files: list[Any], process: str, section_hint: str = "") -> list[ModelDirective]:
    directives: list[ModelDirective] = []
    for model_file in model_files:
        sections = [str(item) for item in getattr(model_file, "corners", []) or []]
        section = _match_pdk_section(sections, section_hint or process)
        directive = _model_directive_for_pdk_file(model_file, section)
        if directive:
            directives.append(directive)
    return directives


def _match_pdk_section(sections: list[str], process: str) -> str:
    if not sections:
        return ""
    proc = str(process or "").strip().lower()
    aliases = {
        "typ": "tt",
        "typical": "tt",
        "fast": "ff",
        "slow": "ss",
    }
    proc = aliases.get(proc, proc)
    for section in sections:
        if section.lower() == proc:
            return section
    for section in sections:
        low = section.lower()
        if low.endswith(f"_{proc}") or low.endswith(f"-{proc}") or proc in low.split("_"):
            return section
    return sections[0]


def _process_from_corner_name(name: str) -> str:
    text = str(name or "").lower()
    for process in ("tt", "ff", "ss", "sf", "fs"):
        if re.search(rf"(^|[_\-\s]){process}($|[_\-\s])", text) or text.endswith(process):
            return process
    if "typ" in text:
        return "tt"
    if "fast" in text:
        return "ff"
    if "slow" in text:
        return "ss"
    return text or "tt"


def _build_ihp_model_manifest(pdk: Any, model_files: list[Any], simulator: str) -> PDKModelManifest:
    wanted = {
        "cornerMOSlv.lib", "cornerMOShv.lib", "cornerRES.lib",
        "cornerCAP.lib", "cornerDIO.lib", "cornerHBT.lib",
    }
    wrappers = []
    seen = set()
    for model_file in sorted(model_files, key=lambda item: str(getattr(item, "path", "")).lower()):
        filename = os.path.basename(str(getattr(model_file, "path", "") or ""))
        if filename in wanted and filename not in seen:
            wrappers.append(model_file)
            seen.add(filename)
    corners = [
        ("TT_25C", "25", "1.2", "tt"),
        ("FF_m40C", "-40", "1.32", "ff"),
        ("SS_125C", "125", "1.08", "ss"),
    ]
    corner_setups = [
        CornerSetup(name, temp, vdd, process, model_directives=[
            ModelDirective("lib", str(getattr(model_file, "path", "") or ""), _ihp_section_for_file(os.path.basename(str(getattr(model_file, "path", "") or "")), process))
            for model_file in wrappers
        ])
        for name, temp, vdd, process in corners
    ]
    shared = corner_setups[0].model_directives if corner_setups else []
    return PDKModelManifest(
        pdk_name=str(getattr(pdk, "name", "") or "ihp_sg13g2"),
        display_name=str(getattr(pdk, "display_name", "") or "IHP SG13G2"),
        simulator=simulator,
        model_directives=list(shared),
        corners=corner_setups,
    )


def _ihp_section_for_file(filename: str, process: str) -> str:
    proc = (process or "tt").lower()
    if proc in {"typ", "typical"}:
        proc = "tt"
    if filename in {"cornerMOSlv.lib", "cornerMOShv.lib"}:
        return f"mos_{proc if proc in {'tt', 'ss', 'ff', 'sf', 'fs'} else 'tt'}"
    if filename == "cornerDIO.lib":
        return f"dio_{proc if proc in {'tt', 'ss', 'ff'} else 'tt'}"
    if filename == "cornerRES.lib":
        return "res_typ" if proc == "tt" else "res_bcs"
    if filename == "cornerCAP.lib":
        return "cap_typ" if proc == "tt" else "cap_bcs"
    if filename == "cornerHBT.lib":
        return "hbt_typ" if proc == "tt" else "hbt_bcs"
    return proc


@dataclass
class RunMatrixJob:
    run_name: str
    corner: str
    sweep_label: str
    variables: dict[str, str]


@dataclass
class SpecLimit:
    """A simple waveform/result pass-fail spec."""

    name: str
    expression: str
    metric: str = "final"
    min_value: str = ""
    max_value: str = ""
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SpecLimit":
        return cls(
            name=str(data.get("name") or "spec"),
            expression=str(data.get("expression") or ""),
            metric=str(data.get("metric") or "final").lower(),
            min_value=str(data.get("min") or data.get("min_value") or ""),
            max_value=str(data.get("max") or data.get("max_value") or ""),
            enabled=bool(data.get("enabled", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def directives_to_netlist_entries(directives: list[ModelDirective]) -> tuple[list[dict], list[dict]]:
    includes: list[dict] = []
    libs: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for directive in directives:
        kind = directive.kind.lower()
        path = str(directive.path or "").strip()
        section = str(directive.section or "").strip()
        if not path:
            continue
        key = (kind, path, section)
        if key in seen:
            continue
        seen.add(key)
        if kind == "include" or path.lower().endswith(".gsdi"):
            includes.append({"path": path})
        elif kind == "gsdi":
            includes.append({"path": path})
        else:
            libs.append({"path": path, "section": section})
    return includes, libs


def validate_model_directives(directives: list[ModelDirective]) -> list[str]:
    errors: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for directive in directives:
        kind = directive.kind.lower()
        path = str(directive.path or "").strip()
        section = str(directive.section or "").strip()
        if kind not in {"lib", "include", "gsdi"}:
            errors.append(f"Unsupported model directive type: {directive.kind}")
        if not path:
            errors.append("Model directive has an empty path.")
            continue
        if not Path(path).expanduser().exists():
            errors.append(f"Model file does not exist: {path}")
        key = (kind, path, section)
        if key in seen:
            errors.append(f"Duplicate model directive: {directive.spice_line()}")
        seen.add(key)
        if kind == "lib" and section and Path(path).suffix.lower() == ".lib":
            sections = extract_lib_sections(path)
            if sections and section not in sections:
                errors.append(f"Section '{section}' not found in {path}")
    return errors


def extract_lib_sections(path: str | os.PathLike[str]) -> list[str]:
    sections: list[str] = []
    p = Path(path)
    if p.suffix.lower() != ".lib" or not p.exists():
        return sections
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                match = re.match(r'\s*\.LIB\s+"?([^"\s]+)"?', line, re.IGNORECASE)
                if match:
                    section = match.group(1)
                    if section not in sections:
                        sections.append(section)
    except OSError:
        return []
    return sections


def parse_model_entries(directives: list[ModelDirective]) -> list[ModelEntry]:
    """Parse .MODEL and .SUBCKT names from model files referenced by directives."""
    entries: list[ModelEntry] = []
    seen: set[tuple[str, str, str, str]] = set()
    for directive in directives:
        path = str(directive.path or "").strip()
        if not path or directive.kind.lower() == "gsdi":
            continue
        p = Path(path).expanduser()
        if not p.exists() or not p.is_file():
            continue
        wanted_section = str(directive.section or "").strip()
        current_section = ""
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as handle:
                for raw in handle:
                    line = raw.strip()
                    if not line or line.startswith("*"):
                        continue
                    lib_match = re.match(r'\.LIB\s+"?([^"\s]+)"?', line, re.IGNORECASE)
                    if lib_match:
                        current_section = lib_match.group(1)
                        continue
                    if re.match(r"\.ENDL\b", line, re.IGNORECASE):
                        current_section = ""
                        continue
                    if wanted_section and current_section and current_section != wanted_section:
                        continue
                    model_match = re.match(r"\.MODEL\s+([^\s]+)\s+([^\s(]+)", line, re.IGNORECASE)
                    if model_match:
                        entry = ModelEntry(
                            name=model_match.group(1),
                            kind="model",
                            path=str(p),
                            section=current_section or wanted_section,
                            device_type=model_match.group(2),
                        )
                    else:
                        subckt_match = re.match(r"\.SUBCKT\s+([^\s]+)(.*)", line, re.IGNORECASE)
                        if not subckt_match:
                            continue
                        pins = [token for token in subckt_match.group(2).split() if "=" not in token]
                        entry = ModelEntry(
                            name=subckt_match.group(1),
                            kind="subckt",
                            path=str(p),
                            section=current_section or wanted_section,
                            pins=pins,
                        )
                    key = (entry.name.lower(), entry.kind, entry.path, entry.section)
                    if key not in seen:
                        seen.add(key)
                        entries.append(entry)
        except OSError:
            continue
    return entries


def validate_model_bindings(
    bindings: list[DeviceModelBinding],
    entries: list[ModelEntry],
    instance_names: set[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    model_names = {entry.name.lower() for entry in entries}
    for binding in bindings:
        if not binding.enabled:
            continue
        instance = str(binding.instance or "").strip()
        model = str(binding.model or "").strip()
        if not instance:
            errors.append("Model binding has an empty instance.")
        elif instance_names is not None and instance not in instance_names:
            errors.append(f"Model binding references unknown instance: {instance}")
        if not model:
            errors.append(f"Model binding for {instance or 'instance'} has an empty model.")
        elif model_names and model.lower() not in model_names:
            errors.append(f"Model '{model}' is not present in the loaded model catalog.")
    return errors


def expand_run_matrix(
    analyses: list[str],
    corners: list[CornerSetup],
    sweep_points: list[tuple[str, dict[str, str]]],
    corner_mode: str,
) -> list[RunMatrixJob]:
    enabled_corners = [corner for corner in corners if corner.enabled]
    use_corners = corner_mode.lower() in {"all corners", "selected", "all"}
    if not use_corners:
        enabled_corners = [enabled_corners[0]] if enabled_corners else [
            CornerSetup("Single", enabled=True)
        ]
    if not sweep_points:
        sweep_points = [("", {})]
    jobs: list[RunMatrixJob] = []
    for analysis in analyses or ["Run"]:
        for corner in enabled_corners:
            for sweep_label, variables in sweep_points:
                parts = []
                if use_corners:
                    parts.append(corner.name)
                if len(analyses) > 1:
                    parts.append(analysis)
                if sweep_label:
                    parts.append(sweep_label)
                jobs.append(
                    RunMatrixJob(
                        run_name=" | ".join(parts) or "Single",
                        corner=corner.name,
                        sweep_label=sweep_label,
                        variables=dict(variables),
                    )
                )
    return jobs


def evaluate_specs(specs: list[SpecLimit], waveforms: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for spec in specs:
        if not spec.enabled:
            continue
        values = _find_waveform(spec.expression, waveforms)
        value = _metric_value(values, spec.metric)
        passed = value is not None
        min_val = _optional_float(spec.min_value)
        max_val = _optional_float(spec.max_value)
        if passed and min_val is not None:
            passed = value >= min_val
        if passed and max_val is not None:
            passed = value <= max_val
        results.append({
            "name": spec.name,
            "expression": spec.expression,
            "metric": spec.metric,
            "value": value,
            "min": min_val,
            "max": max_val,
            "passed": bool(passed),
        })
    return results


def _optional_float(raw: str) -> float | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _find_waveform(expression: str, waveforms: dict[str, Any]) -> Any:
    expr = str(expression or "").strip()
    if expr in waveforms:
        return waveforms[expr]
    lower = expr.lower()
    for key, values in waveforms.items():
        if str(key).lower() == lower:
            return values
    if lower.startswith("v(") and lower.endswith(")"):
        node = lower[2:-1].strip()
        candidates = {f"v({node})", f"v:{node}", node}
        for key, values in waveforms.items():
            if str(key).lower() in candidates:
                return values
    return None


def _metric_value(values: Any, metric: str) -> float | None:
    if values is None:
        return None
    if isinstance(values, (list, tuple)):
        nums = []
        for value in values:
            try:
                num = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(num):
                nums.append(num)
        if not nums:
            return None
    else:
        try:
            num = float(values)
        except (TypeError, ValueError):
            return None
        return num if math.isfinite(num) else None
    metric = str(metric or "final").lower()
    if metric == "min":
        return min(nums)
    if metric == "max":
        return max(nums)
    if metric == "mean":
        return sum(nums) / len(nums)
    if metric in {"pp", "p2p", "peak-to-peak"}:
        return max(nums) - min(nums)
    return nums[-1]
