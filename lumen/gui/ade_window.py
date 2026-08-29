"""
Lumen Circuit Studio - SimENV Window
Tabbed simulation environment supporting GSPICE, Ngspice, and Xyce analyses.
"""
import os
import re
import traceback
import json
import csv
import math
import concurrent.futures
from pathlib import Path

from lumen.qt.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QLineEdit, QLabel, QPushButton, QGroupBox, QFormLayout,
    QCheckBox, QSpinBox, QDoubleSpinBox, QTextEdit, QSplitter,
    QStatusBar, QToolBar, QMessageBox, QTreeWidget, QTreeWidgetItem,
    QDialog, QDialogButtonBox, QGridLayout, QScrollArea, QFrame,
    QFileDialog, QInputDialog, QProgressBar
)
from lumen.qt.QtWidgets import QAbstractItemView, QMenu
from lumen.qt.QtCore import Qt, QSize, QUrl, QObject, QThread, QTimer, Signal
from lumen.qt.QtGui import QAction, QFont, QColor, QIcon, QKeySequence, QDesktopServices

from lumen.core.database import LibraryDatabase
from lumen.core.ade_engine import ExpressionCalculator
from lumen.core.netlist import NetlistGenerator, NetlistDirectives
from lumen.core.simulation_setup import (
    DeviceModelBinding,
    ModelEntry,
    ModelDirective,
    SpecLimit,
    build_pdk_model_manifest,
    directives_to_netlist_entries,
    evaluate_specs,
    extract_lib_sections,
    parse_model_entries,
    validate_model_bindings,
    validate_model_directives,
)
from lumen.core.simulator import (
    SIMULATOR_INFO,
    SimulatorBridge,
    get_simulator_label,
    get_supported_analyses,
    normalize_simulator_name,
)
from lumen.core.simulator_compare import ReferenceComparisonRunner, format_reference_report
from lumen.core.simulator_runtime import ACTIVE_SIMULATORS, SimulatorRuntimeManager
from lumen.core.pss import (
    PSS_MODE_DRIVEN,
    PSS_MODE_OSCILLATOR,
    build_pss_statement,
    normalize_pss_mode,
    pss_validation_errors,
)
from lumen.core.pdk_service import get_registry
from lumen.core.pdk_unified import PDKLock
from lumen.gui.branding import apply_window_branding
from lumen.gui.simulator_manager_window import (
    SimulatorManagerWindow,
    ensure_simulator_available,
)


# All GSPICE-supported analyses
ANALYSES = {
    "DC Operating Point": {"cmd": ".OP", "category": "Standard", "params": []},
    "Transient": {"cmd": ".TRAN", "category": "Standard", "params": [
        ("Step", "", "Output/save interval; Auto scales from stop time and accuracy"),
        ("Stop", "10u", "Stop time"),
        ("Start", "0", "Start time"),
        ("MaxStep", "", "Optional internal timestep cap; Auto/blank lets GSPICE adapt"),
        ("UIC", False, "Use initial conditions")]},
    "AC Small-Signal": {"cmd": ".AC", "category": "Standard", "params": [
        ("BiasOP", True, "Run from the DC operating point, industry-style"),
        ("Sweep", "DEC", "DEC/OCT/LIN"), ("Points", "100", "Points per decade"),
        ("Fstart", "1", "Start freq (Hz)"), ("Fstop", "10G", "Stop freq (Hz)")]},
    "Noise": {"cmd": ".NOISE", "category": "Standard", "params": [
        ("Output", "", "Required output node, for example V(OUTNET)"), ("Source", "V1", "Input source"),
        ("Sweep", "DEC", "DEC/OCT/LIN"), ("Points", "50", "Points"),
        ("Fstart", "1", "Start freq"), ("Fstop", "1G", "Stop freq")]},
    "DC Sweep": {"cmd": ".DC", "category": "Standard", "params": [
        ("Source", "V1", "Sweep source"), ("Start", "0", "Start value"),
        ("Stop", "1.8", "Stop value"), ("Step", "10m", "Step size")]},
    "PSS (Periodic Steady-State)": {"cmd": ".PSS", "category": "RF Core", "params": [
        ("Mode", ["Driven (forced)", "Oscillator (autonomous)"], "Driven PSS for forced circuits; oscillator mode for autonomous oscillators"),
        ("Fund", "1G", "Driven fundamental or oscillator frequency estimate"),
        ("Harmonics", "7", "Number of harmonics"),
        ("Tstab", "", "Optional stabilization time before shooting"),
        ("TstabPeriods", "", "Optional stabilization periods before shooting"),
        ("Adaptive", False, "Enable GSPICE adaptive PSS controls"),
        ("Continuation", False, "Enable GSPICE continuation for harder oscillator starts"),
        ("UseIC", False, "Use .IC entries from the Convergence tab for PSS startup"),
        ("ContinuationSteps", "", "Optional continuation step count"),
        ("MaxPssIter", "", "Optional maximum PSS shooting iterations"),
        ("ResidualGoal", "", "Optional PSS residual goal")]},
    "Harmonic Balance": {"cmd": ".HB", "category": "RF Core", "params": [
        ("Freq", "1G", "Fundamental freq"), ("Harmonics", "7", "Num harmonics"),
        ("MaxIter", "100", "Max iterations")]},
    "S-Parameters": {"cmd": ".SP", "category": "RF Core", "params": [
        ("Sweep", "LIN", "LIN/DEC/OCT"), ("Points", "201", "Num points"),
        ("Fstart", "100M", "Start freq"), ("Fstop", "10G", "Stop freq"),
        ("Port1", "1", "Port 1"), ("Port2", "2", "Port 2")]},
    "PAC (Periodic AC)": {"cmd": ".PAC", "category": "RF Advanced", "params": [
        ("Fund", "1G", "Fund freq"), ("Sidebands", "5", "Num sidebands"),
        ("Fstart", "1k", "Start freq"), ("Fstop", "100M", "Stop freq")]},
    "PNOISE (Periodic Noise)": {"cmd": ".PNOISE", "category": "RF Advanced", "params": [
        ("Fund", "", "Optional carrier override; blank uses converged PSS frequency"),
        ("Output", "", "Required output node, for example V(OUTNET)"),
        ("Points", "50", "Points per decade"),
        ("Fstart", "1k", "Start offset"), ("Fstop", "100M", "Stop offset")]},
    "HBAC": {"cmd": ".HBAC", "category": "RF Advanced", "params": [
        ("Freq", "1G", "Fund freq"), ("Fstart", "1k", "Start"),
        ("Fstop", "100M", "Stop"), ("Points", "50", "Points")]},
    "HBNOISE": {"cmd": ".HBNOISE", "category": "RF Advanced", "params": [
        ("Freq", "1G", "Fund freq"), ("Output", "V(out)", "Output"),
        ("Fstart", "1k", "Start"), ("Fstop", "100M", "Stop")]},
    "HBSP": {"cmd": ".HBSP", "category": "RF Advanced", "params": [
        ("Freq", "1G", "Fund freq"), ("Fstart", "100M", "Start"),
        ("Fstop", "10G", "Stop"), ("Points", "201", "Points")]},
    "STB (Stability)": {"cmd": ".STB", "category": "Stability", "params": [
        ("Probe", "V(out)", "Probe element"), ("Sweep", "DEC", "Sweep type"),
        ("Points", "100", "Points"), ("Fstart", "1", "Start"), ("Fstop", "10G", "Stop")]},
    "HBSTB": {"cmd": ".HBSTB", "category": "Stability", "params": [
        ("Freq", "1G", "Fund"), ("Probe", "V(out)", "Probe"),
        ("Fstart", "1", "Start"), ("Fstop", "10G", "Stop")]},
    "PSSSTB": {"cmd": ".PSSSTB", "category": "Stability", "params": [
        ("Fund", "1G", "Fund freq"), ("Probe", "V(out)", "Probe"),
        ("Fstart", "1", "Start"), ("Fstop", "10G", "Stop")]},
}

GSPICE_ACCURACY_PRESETS = {
    "Low": {
        "RELTOL": "5e-3", "VNTOL": "10u", "ABSTOL": "1p",
        "TRTOL": "1", "LTE_RELTOL": "2e-2", "TRABSTOL": "10u", "ITL4": "40",
    },
    "Medium": {
        "RELTOL": "1e-3", "VNTOL": "1u", "ABSTOL": "1p",
        "TRTOL": "1", "LTE_RELTOL": "5e-3", "TRABSTOL": "1u", "ITL4": "60",
    },
    "High": {
        "RELTOL": "3e-4", "VNTOL": "300n", "ABSTOL": "100f",
        "TRTOL": "1", "LTE_RELTOL": "1e-3", "TRABSTOL": "300n", "ITL4": "80",
    },
    "Very High": {
        "RELTOL": "1e-4", "VNTOL": "100n", "ABSTOL": "10f",
        "TRTOL": "1", "LTE_RELTOL": "3e-4", "TRABSTOL": "100n", "ITL4": "120",
    },
}

GSPICE_TRANSIENT_TARGET_POINTS = {
    "Low": 5_000,
    "Medium": 10_000,
    "High": 20_000,
    "Very High": 50_000,
}

def gspice_transient_defaults(accuracy: str = "High", stop: str = "10u") -> dict:
    try:
        from lumen.core.simulator import SimulatorBridge
        stop_val = SimulatorBridge._parse_spice_number(stop)
    except Exception:
        stop_val = 10e-6
    target_pts = GSPICE_TRANSIENT_TARGET_POINTS.get(accuracy, 20_000)
    step_val = stop_val / max(1, target_pts)
    step_str = f"{step_val:.6g}"
    return {"step": step_str, "maxstep": ""}


class AnalysisSetupWidget(QWidget):
    """Tab for configuring a single analysis."""
    pick_output_requested = Signal(object)

    def __init__(self, analysis_name: str, parent=None):
        super().__init__(parent)
        self.analysis_name = analysis_name
        self.info = ANALYSES[analysis_name]
        self._fields: dict[str, QWidget] = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Header
        header = QLabel(f"{self.analysis_name}")
        header.setStyleSheet("font-size: 14px; font-weight: bold; color: #6b9ece; background: transparent;")
        layout.addWidget(header)

        cat = QLabel(f"Category: {self.info['category']}  |  SPICE: {self.info['cmd']}")
        cat.setStyleSheet("color: #808080; background: transparent; padding-bottom: 8px;")
        layout.addWidget(cat)

        # Parameters form
        if self.info["params"]:
            group = QGroupBox("Parameters")
            form = QFormLayout(group)
            for name, default, desc in self.info["params"]:
                if isinstance(default, bool):
                    widget = QCheckBox()
                    widget.setChecked(default)
                    widget.setToolTip(desc)
                elif isinstance(default, (list, tuple)):
                    widget = QComboBox()
                    widget.addItems([str(item) for item in default])
                    widget.setToolTip(desc)
                else:
                    widget = QLineEdit(str(default))
                    widget.setToolTip(desc)
                    widget.setPlaceholderText(desc)
                row_widget = widget
                if self.analysis_name in {"Noise", "PNOISE (Periodic Noise)"} and name == "Output":
                    row_widget = QWidget()
                    row_layout = QHBoxLayout(row_widget)
                    row_layout.setContentsMargins(0, 0, 0, 0)
                    row_layout.addWidget(widget, 1)
                    pick_btn = QPushButton("Pick")
                    pick_btn.setToolTip("Pick a voltage net from the schematic")
                    pick_btn.clicked.connect(lambda _checked=False, w=widget: self.pick_output_requested.emit(w))
                    row_layout.addWidget(pick_btn)
                form.addRow(f"{name}:", row_widget)
                self._fields[name] = widget
            layout.addWidget(group)
            if self.analysis_name == "PSS (Periodic Steady-State)":
                self._pss_frequency_label = QLabel("Frequency estimate:")
                self._pss_frequency_label.setStyleSheet("color:#8fa9b8;background:transparent;padding:4px 0;")
                layout.addWidget(self._pss_frequency_label)
                mode_widget = self._fields.get("Mode")
                if isinstance(mode_widget, QComboBox):
                    mode_widget.currentTextChanged.connect(self._update_pss_mode_labels)
                    self._update_pss_mode_labels(mode_widget.currentText())
        else:
            note = QLabel("No parameters — runs with default settings.")
            note.setStyleSheet("color: #808080; background: transparent; padding: 16px;")
            layout.addWidget(note)

        layout.addStretch()

    def get_spice_line(self) -> str:
        """Generate the SPICE analysis statement."""
        cmd = self.info["cmd"]
        if self.analysis_name == "PSS (Periodic Steady-State)":
            return build_pss_statement(self.get_values(), cmd)
        if self.analysis_name == "PNOISE (Periodic Noise)":
            values = self.get_values()
            output = str(values.get("Output", "") or "").strip()
            if not output.upper().startswith("V("):
                output = f"V({output})"
            points = str(values.get("Points", "50") or "50").strip()
            fstart = str(values.get("Fstart", "1k") or "1k").strip()
            fstop = str(values.get("Fstop", "100M") or "100M").strip()
            fund = str(values.get("Fund", "") or "").strip()
            suffix = f" FUND={fund}" if fund else ""
            return f"{cmd} {output} none DEC {points} {fstart} {fstop}{suffix}"
        parts = [cmd]
        for name, default, desc in self.info["params"]:
            w = self._fields.get(name)
            if w is None:
                continue
            if isinstance(w, QCheckBox):
                if w.isChecked():
                    parts.append(name)
            elif isinstance(w, QComboBox):
                val = w.currentText().strip()
                if val:
                    parts.append(val)
            elif isinstance(w, QLineEdit):
                val = w.text().strip()
                if val:
                    parts.append(val)
        return " ".join(parts)

    def get_values(self) -> dict:
        result = {}
        for name, default, _ in self.info["params"]:
            w = self._fields.get(name)
            if isinstance(w, QCheckBox):
                result[name] = w.isChecked()
            elif isinstance(w, QComboBox):
                value = w.currentText().strip()
                result[name] = normalize_pss_mode(value) if self.analysis_name == "PSS (Periodic Steady-State)" and name == "Mode" else value
            elif isinstance(w, QLineEdit):
                result[name] = w.text().strip()
        if self.analysis_name == "PSS (Periodic Steady-State)":
            result["Mode"] = normalize_pss_mode(result.get("Mode", PSS_MODE_DRIVEN))
        return result

    def set_values(self, values: dict):
        """Apply persisted analysis values to the form."""
        values = dict(values or {})
        if self.analysis_name == "PSS (Periodic Steady-State)":
            values = self._normalize_pss_form_values(values)
        for param_name, param_value in values.items():
            w = self._fields.get(param_name)
            if isinstance(w, QCheckBox):
                w.setChecked(bool(param_value))
            elif isinstance(w, QComboBox):
                self._set_combo_value(w, str(param_value))
            elif isinstance(w, QLineEdit):
                w.setText(str(param_value))
        if self.analysis_name == "PSS (Periodic Steady-State)":
            mode_widget = self._fields.get("Mode")
            if isinstance(mode_widget, QComboBox):
                self._update_pss_mode_labels(mode_widget.currentText())

    def validation_errors(self) -> list[str]:
        if self.analysis_name == "PSS (Periodic Steady-State)":
            return pss_validation_errors(self.get_values())
        if self.analysis_name in {"Noise", "PNOISE (Periodic Noise)"}:
            values = self.get_values()
            output = str(values.get("Output", "") or "").strip()
            if not output:
                return ["Choose an output node before running noise analysis."]
            if self.analysis_name == "PNOISE (Periodic Noise)":
                errors = []
                points = str(values.get("Points", "") or "").strip()
                try:
                    if int(points) <= 0:
                        errors.append("PNOISE points must be a positive integer.")
                except Exception:
                    errors.append("PNOISE points must be a positive integer.")
                for key in ("Fstart", "Fstop"):
                    text = str(values.get(key, "") or "").strip()
                    try:
                        if SimulatorBridge._parse_spice_number(text) <= 0.0:
                            errors.append(f"PNOISE {key} must be a positive frequency.")
                    except Exception:
                        errors.append(f"PNOISE {key} must be a positive frequency.")
                return errors
        return []

    def _normalize_pss_form_values(self, values: dict) -> dict:
        normalized = dict(values)
        normalized["Mode"] = normalize_pss_mode(
            normalized.get(
                "Mode",
                normalized.get(
                    "mode",
                    normalized.get("Oscillator", normalized.get("oscillator", PSS_MODE_DRIVEN)),
                ),
            )
        )
        for old, new in {
            "fund": "Fund",
            "harmonics": "Harmonics",
            "tstab": "Tstab",
            "tstab_periods": "TstabPeriods",
            "pss_adaptive": "Adaptive",
            "pss_continuation": "Continuation",
            "pss_use_ic": "UseIC",
            "pss_continuation_steps": "ContinuationSteps",
            "pss_residual_goal": "ResidualGoal",
        }.items():
            if old in normalized and new not in normalized:
                normalized[new] = normalized[old]
        return normalized

    def _set_combo_value(self, combo: QComboBox, value: str):
        is_mode = combo is self._fields.get("Mode")
        target = normalize_pss_mode(value) if is_mode else value.strip().lower()
        for idx in range(combo.count()):
            text = combo.itemText(idx)
            current = normalize_pss_mode(text) if is_mode else text.strip().lower()
            if current == target:
                combo.setCurrentIndex(idx)
                return

    def _update_pss_mode_labels(self, text: str):
        if not hasattr(self, "_pss_frequency_label"):
            return
        if normalize_pss_mode(text) == PSS_MODE_OSCILLATOR:
            self._pss_frequency_label.setText("Frequency estimate:")
            for name in ("Adaptive", "Continuation", "UseIC"):
                widget = self._fields.get(name)
                if isinstance(widget, QCheckBox):
                    widget.setChecked(True)
        else:
            self._pss_frequency_label.setText("Fundamental frequency:")


class SimulationDumpSettingsDialog(QDialog):
    """Dialog for choosing where SimENV run artifacts are written."""

    def __init__(self, current_dir: str, default_dir: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Simulation Dump Settings")
        self.setMinimumWidth(620)
        self._default_dir = str(default_dir or "")

        layout = QVBoxLayout(self)

        title = QLabel("Simulation Dump Folder")
        title.setStyleSheet("font-size:15px;font-weight:bold;color:#6b9ece;background:transparent;")
        layout.addWidget(title)

        description = QLabel(
            "SimENV writes every simulator run into this folder. Each run gets its own "
            "subfolder so input decks, logs, waveform files, and manifests stay together."
        )
        description.setWordWrap(True)
        description.setStyleSheet("color:#9aa8b6;background:transparent;")
        layout.addWidget(description)

        form = QGridLayout()
        form.addWidget(QLabel("Root folder:"), 0, 0)
        self.path_edit = QLineEdit(str(current_dir or default_dir or ""))
        self.path_edit.setMinimumWidth(420)
        form.addWidget(self.path_edit, 0, 1)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse)
        form.addWidget(browse_btn, 0, 2)

        default_btn = QPushButton("Use Default")
        default_btn.clicked.connect(self._use_default)
        form.addWidget(default_btn, 1, 2)

        self.preview_label = QLabel("")
        self.preview_label.setWordWrap(True)
        self.preview_label.setStyleSheet("color:#8c9aa8;background:transparent;")
        form.addWidget(self.preview_label, 1, 1)
        layout.addLayout(form)

        artifact_box = QGroupBox("Files Written Per Run")
        artifact_layout = QVBoxLayout(artifact_box)
        artifacts = QLabel(
            "input.sp\n"
            "stdout.log / stderr.log\n"
            "waveforms.raw when the simulator emits or Lumen can synthesize RAW\n"
            "selected_waveforms.raw when SimENV Outputs are selected\n"
            "run_manifest.json with command, paths, warnings, errors, and signal list\n"
            "latest_run.txt in the run-family folder"
        )
        artifacts.setStyleSheet("font-family:Consolas,monospace;color:#d7dde6;background:transparent;")
        artifact_layout.addWidget(artifacts)
        layout.addWidget(artifact_box)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color:#cc8888;background:transparent;")
        layout.addWidget(self.error_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.path_edit.textChanged.connect(self._update_preview)
        self._update_preview()

    def selected_path(self) -> str:
        return str(Path(self.path_edit.text().strip()).expanduser().resolve())

    def _browse(self):
        chosen = QFileDialog.getExistingDirectory(
            self,
            "Select Simulation Dump Folder",
            self.path_edit.text().strip() or self._default_dir,
        )
        if chosen:
            self.path_edit.setText(chosen)

    def _use_default(self):
        self.path_edit.setText(self._default_dir)

    def _update_preview(self):
        text = self.path_edit.text().strip()
        if not text:
            self.preview_label.setText("")
            return
        try:
            root = Path(text).expanduser().resolve()
            self.preview_label.setText(
                f"Example run folder: {root / 'simenv_<cell>' / 'YYYYMMDD_HHMMSS'}"
            )
        except OSError:
            self.preview_label.setText("")

    def _accept_if_valid(self):
        raw = self.path_edit.text().strip()
        if not raw:
            self.error_label.setText("Choose a simulation dump folder.")
            return
        try:
            path = Path(raw).expanduser().resolve()
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".lumen_write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except Exception as exc:
            self.error_label.setText(f"Folder is not writable: {exc}")
            return
        self.accept()


class SimulationMonitorWindow(QDialog):
    """Live simulator progress window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Simulation Monitor")
        self.setMinimumSize(720, 420)
        layout = QVBoxLayout(self)

        self.title_label = QLabel("Simulation running")
        self.title_label.setStyleSheet("font-size:15px;font-weight:bold;color:#6b9ece;background:transparent;")
        layout.addWidget(self.title_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("Starting...")
        layout.addWidget(self.progress_bar)

        summary_frame = QFrame()
        summary_frame.setStyleSheet(
            "QFrame{background:#141b21;border:1px solid #2f3c46;border-radius:4px;}"
            "QLabel{background:transparent;color:#d7dde6;}"
        )
        summary_grid = QGridLayout(summary_frame)
        summary_grid.setContentsMargins(8, 6, 8, 6)
        self.summary_labels: dict[str, QLabel] = {}
        for idx, (key, label) in enumerate((
            ("method", "Method"),
            ("steps", "Steps"),
            ("rejected", "Rejected"),
            ("newton", "Newton Avg"),
            ("dt", "Step Range"),
            ("points", "Points"),
        )):
            name_label = QLabel(label)
            name_label.setStyleSheet("color:#8fa9b8;background:transparent;font-size:10px;")
            value_label = QLabel("--")
            value_label.setStyleSheet("color:#f2f7fb;background:transparent;font-weight:bold;")
            self.summary_labels[key] = value_label
            row = idx // 3
            col = (idx % 3) * 2
            summary_grid.addWidget(name_label, row, col)
            summary_grid.addWidget(value_label, row, col + 1)
        layout.addWidget(summary_frame)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setStyleSheet(
            "QTextEdit{background:#101418;color:#d7dde6;border:1px solid #34424d;border-radius:4px;}"
        )
        layout.addWidget(self.log_text, stretch=1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.close_btn = QPushButton("Hide")
        self.close_btn.clicked.connect(self.hide)
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)

    def reset_for_run(self, title: str):
        self.title_label.setText(title)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Starting...")
        self.log_text.clear()
        for label in self.summary_labels.values():
            label.setText("--")

    def append_message(self, message: str):
        text = str(message or "").strip()
        if not text:
            return
        self.log_text.append(text)
        match = re.search(r"(\d+(?:\.\d+)?)%", text)
        if match:
            pct = max(0.0, min(100.0, float(match.group(1))))
            self.progress_bar.setValue(int(pct * 10))
            self.progress_bar.setFormat(f"{pct:.1f}%")
        else:
            p_match = re.search(r"elapsed\s+([\d:]+),\s*requested points\s*~?([\d,]+)", text, re.IGNORECASE)
            if p_match:
                elapsed_str = p_match.group(1)
                points_str = p_match.group(2)
                self.progress_bar.setFormat(f"Running... {elapsed_str} ({points_str} pts)")
                if hasattr(self, "summary_labels") and "points" in self.summary_labels:
                    self.summary_labels["points"].setText(points_str)
            elif "completed" in text.lower() or "finished" in text.lower():
                self.progress_bar.setValue(1000)
                self.progress_bar.setFormat("Complete")
            elif "failed" in text.lower() or "timed out" in text.lower():
                self.progress_bar.setFormat("Failed")
        self._update_summary_from_message(text)
        self.log_text.ensureCursorVisible()

    def _update_summary_from_message(self, text: str):
        if not hasattr(self, "summary_labels"):
            return
        body = text.split(":", 1)[1].strip() if text.startswith("GSPICE:") else text
        lower = body.lower()
        if lower.startswith("transient controls:"):
            method_match = re.search(r"method=(.+)$", body)
            if method_match:
                self.summary_labels["method"].setText(method_match.group(1).strip())
        elif lower.startswith("transient summary:"):
            values = dict(re.findall(r"([a-zA-Z_]+)=([^\s]+)", body))
            accepted = values.get("accepted", "--")
            rejected = values.get("rejected", "--")
            points = values.get("output_points", "--")
            min_step = values.get("min_step", "--")
            max_step = values.get("max_step", "--")
            self.summary_labels["steps"].setText(str(accepted))
            self.summary_labels["rejected"].setText(str(rejected))
            self.summary_labels["points"].setText(str(points))
            self.summary_labels["dt"].setText(f"{min_step} .. {max_step}")
        elif lower.startswith("newton summary:"):
            values = dict(re.findall(r"([a-zA-Z_]+)=([^\s]+)", body))
            avg = values.get("average_iterations", "--")
            max_iter = values.get("max_iterations", "--")
            self.summary_labels["newton"].setText(f"{avg} / max {max_iter}")
        elif lower.startswith("accuracy summary:"):
            method_match = re.search(r"method=(.*?)\s+reltol=", body)
            if method_match:
                self.summary_labels["method"].setText(method_match.group(1).strip())


class SimEnvSimulationWorker(QObject):
    """Run simulator jobs away from the Qt UI thread."""

    progress = Signal(str)
    result_ready = Signal(str, object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, simulator: str, exe_path: str, work_dir: str,
                 jobs: list[tuple[str, str, str]], threads: int = 1,
                 timeout: int = 0, workspace: str = "", compare_references: bool = True,
                 sim_env: str = "local", ssh_host: str = "", ssh_user: str = "",
                 ssh_key: str = "", remote_gspice: str = "",
                 save_mode: str = "all", adaptive_maxstep: bool = True,
                 verbose_compat: bool = False):
        super().__init__()
        self.simulator = simulator
        self.exe_path = exe_path
        self.work_dir = work_dir
        self.jobs = list(jobs)
        self.threads = max(1, min(16, int(threads or 1)))
        self.timeout = int(timeout or 0)
        self.workspace = workspace
        self.compare_references = compare_references
        self.sim_env = sim_env
        self.ssh_host = ssh_host
        self.ssh_user = ssh_user
        self.ssh_key = ssh_key
        self.remote_gspice = remote_gspice
        self.save_mode = save_mode
        self.adaptive_maxstep = bool(adaptive_maxstep)
        self.verbose_compat = bool(verbose_compat)
        self._bridge: SimulatorBridge | None = None
        self._bridges: list[SimulatorBridge] = []
        self._cancelled = False

    def run(self):
        try:
            if self.threads <= 1 or len(self.jobs) <= 1:
                for job in self.jobs:
                    if self._cancelled:
                        break
                    run_name, result = self._run_one(job)
                    self.result_ready.emit(run_name, result)
                    if self._cancelled:
                        break
            else:
                with concurrent.futures.ThreadPoolExecutor(max_workers=self.threads) as pool:
                    futures = [pool.submit(self._run_one, job) for job in self.jobs]
                    for future in concurrent.futures.as_completed(futures):
                        if self._cancelled:
                            break
                        run_name, result = future.result()
                        self.result_ready.emit(run_name, result)
                if self._cancelled:
                    for bridge in list(self._bridges):
                        bridge.cancel()
        except Exception:
            self.failed.emit(traceback.format_exc())
        finally:
            self.finished.emit()

    def _run_one(self, job: tuple[str, str, str]):
        run_name, netlist, sim_name = job
        self.progress.emit(f"Running {run_name}...")
        bridge = SimulatorBridge(
            self.simulator,
            exe_path=self.exe_path,
            work_dir=self.work_dir,
            sim_env=self.sim_env,
            ssh_host=self.ssh_host,
            ssh_user=self.ssh_user,
            ssh_key=self.ssh_key,
            remote_gspice=self.remote_gspice,
            save_mode=self.save_mode,
            adaptive_maxstep=self.adaptive_maxstep,
            verbose_compat=self.verbose_compat,
        )
        self._bridge = bridge
        self._bridges.append(bridge)
        try:
            if self._cancelled:
                raise RuntimeError("Simulation cancelled")
            result = bridge.simulate(
                    netlist,
                    sim_name=sim_name,
                    threads=1 if len(self.jobs) > 1 else self.threads,
                    timeout=self.timeout,
                    progress_callback=lambda msg: self.progress.emit(f"[{run_name}] {msg}"),
            )
            if self.compare_references and not self._cancelled:
                comparisons = ReferenceComparisonRunner(
                    self.workspace,
                    self.work_dir,
                ).compare(
                    self.simulator,
                    netlist,
                    result,
                    sim_name,
                    threads=1,
                    progress_callback=lambda msg: self.progress.emit(f"[{run_name}] {msg}"),
                )
                report = format_reference_report(comparisons)
                if report:
                    result.log += "\n" + report + "\n"
                    result.warnings.extend(
                        item.summary_line() for item in comparisons
                    )
                    result.artifacts["reference_comparison"] = report
            return run_name, result
        finally:
            try:
                self._bridges.remove(bridge)
            except ValueError:
                pass

    def cancel(self):
        self._cancelled = True
        if self._bridge is not None:
            self._bridge.cancel()
        for bridge in list(self._bridges):
            bridge.cancel()


class DesignVariablesWidget(QWidget):
    """Design variables table."""
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Design Variables"))
        add_btn = QPushButton("+ Add")
        add_btn.setFixedWidth(60)
        add_btn.clicked.connect(self._add_row)
        hdr.addWidget(add_btn)
        layout.addLayout(hdr)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Variable", "Value", "Description"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

    def _add_row(self):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem("var"))
        self.table.setItem(r, 1, QTableWidgetItem("1"))
        self.table.setItem(r, 2, QTableWidgetItem(""))

    def get_variables(self) -> dict[str, str]:
        result = {}
        for r in range(self.table.rowCount()):
            name_item = self.table.item(r, 0)
            val_item = self.table.item(r, 1)
            if name_item and val_item:
                result[name_item.text()] = val_item.text()
        return result


class ExpressionEditorDialog(QDialog):
    """Small helper for building and checking waveform expressions."""

    FUNCTIONS = [
        "V()", "I()", "dB()", "phase()", "group_delay()", "abs()", "real()", "imag()",
        "fft()", "deriv()", "integ()", "sqrt()", "log10()",
    ]

    def __init__(self, expression: str = "", signals: list[str] | None = None,
                 waveforms: dict | None = None, parent=None,
                 measurement_hook=None, spec_hook=None, history: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Expression Editor")
        self.resize(720, 460)
        self._waveforms = dict(waveforms or {})
        self._calculator = ExpressionCalculator()
        self._measurement_hook = measurement_hook
        self._spec_hook = spec_hook

        layout = QVBoxLayout(self)
        split = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 6, 0)
        history_items = [str(item).strip() for item in history or [] if str(item).strip()]
        if history_items:
            left_layout.addWidget(QLabel("History"))
            self.history_combo = QComboBox()
            self.history_combo.addItem("")
            self.history_combo.addItems(history_items)
            self.history_combo.currentTextChanged.connect(self._use_history_expression)
            left_layout.addWidget(self.history_combo)
        left_layout.addWidget(QLabel("Signals"))
        self.signal_list = QTreeWidget()
        self.signal_list.setHeaderLabels(["Name"])
        for name in sorted({str(s) for s in signals or [] if str(s).strip()}):
            self.signal_list.addTopLevelItem(QTreeWidgetItem([name]))
        self.signal_list.itemDoubleClicked.connect(lambda item, _col: self._insert(item.text(0)))
        left_layout.addWidget(self.signal_list)
        split.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 0, 0, 0)
        fn_grid = QGridLayout()
        for idx, fn in enumerate(self.FUNCTIONS):
            btn = QPushButton(fn)
            btn.clicked.connect(lambda _checked=False, text=fn: self._insert_function(text))
            fn_grid.addWidget(btn, idx // 4, idx % 4)
        right_layout.addLayout(fn_grid)

        self.expr_edit = QTextEdit()
        self.expr_edit.setAcceptRichText(False)
        self.expr_edit.setPlainText(expression or "V(out)")
        right_layout.addWidget(self.expr_edit, 1)

        controls = QHBoxLayout()
        validate_btn = QPushButton("Validate")
        validate_btn.clicked.connect(self._validate)
        controls.addWidget(validate_btn)
        preview_btn = QPushButton("Preview")
        preview_btn.clicked.connect(self._preview)
        controls.addWidget(preview_btn)
        meas_btn = QPushButton("Add Measurement")
        meas_btn.clicked.connect(self._add_measurement)
        controls.addWidget(meas_btn)
        spec_btn = QPushButton("Add Spec")
        spec_btn.clicked.connect(self._add_spec)
        controls.addWidget(spec_btn)
        controls.addStretch()
        right_layout.addLayout(controls)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        right_layout.addWidget(self.status_label)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        layout.addWidget(split)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def expression(self) -> str:
        return self.expr_edit.toPlainText().strip()

    def _use_history_expression(self, text: str) -> None:
        expr = str(text or "").strip()
        if expr:
            self.expr_edit.setPlainText(expr)

    def _insert(self, text: str) -> None:
        cursor = self.expr_edit.textCursor()
        cursor.insertText(text)
        self.expr_edit.setTextCursor(cursor)
        self.expr_edit.setFocus()

    def _insert_function(self, text: str) -> None:
        selected = self.expr_edit.textCursor().selectedText().strip()
        self._insert(f"{text[:-1]}{selected})" if selected and text.endswith("()") else text)

    def _validate(self) -> bool:
        expr = self.expression()
        if not expr:
            self.status_label.setText("Expression is empty.")
            return False
        if self._waveforms:
            result = self._calculator.evaluate(expr, self._waveforms)
            if result is None:
                self.status_label.setText("Could not evaluate against the latest waveforms.")
                return False
            self.status_label.setText(f"Valid: {len(result.get('y', []))} point(s).")
            return True
        if not re.search(r"[A-Za-z_]\w*\(|[A-Za-z_]\w*", expr):
            self.status_label.setText("Expression does not look like a waveform expression.")
            return False
        self.status_label.setText("Syntax looks usable. Run simulation for waveform preview.")
        return True

    def _preview(self) -> None:
        if not self._waveforms:
            self.status_label.setText("No latest waveforms available yet.")
            return
        self._validate()

    def _add_measurement(self) -> None:
        expr = self.expression()
        if expr and callable(self._measurement_hook):
            self._measurement_hook(expr)
            self.status_label.setText("Measurement added.")

    def _add_spec(self) -> None:
        expr = self.expression()
        if expr and callable(self._spec_hook):
            self._spec_hook(expr)
            self.status_label.setText("Spec added.")


class OutputsWidget(QWidget):
    """Output expressions table with support for post-processing expressions."""

    BUILT_IN_EXPRS = [
        "V(node)", "I(source)", "dB20(V(out))", "phase(V(out))",
        "group_delay(V(out))", "V(out)-V(in)", "V(out)/V(in)",
        "abs(V(out))", "real(V(out))", "imag(V(out))",
        "fft(V(out))", "deriv(V(out))", "integ(V(out))",
    ]

    def __init__(self, parent=None, target_provider=None, visualize_hook=None,
                 voltage_pick_hook=None, current_pick_hook=None, expression_edit_hook=None):
        super().__init__(parent)
        self._target_provider = target_provider
        self._visualize_hook = visualize_hook
        self._voltage_pick_hook = voltage_pick_hook
        self._current_pick_hook = current_pick_hook
        self._expression_edit_hook = expression_edit_hook
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Outputs"))
        add_btn = QPushButton("+ Add")
        add_btn.setFixedWidth(60)
        add_btn.clicked.connect(self._add_row)
        hdr.addWidget(add_btn)

        add_v_btn = QPushButton("+ V(net)")
        add_v_btn.setFixedWidth(72)
        add_v_btn.clicked.connect(self._on_add_voltage)
        hdr.addWidget(add_v_btn)

        add_i_btn = QPushButton("+ I(term)")
        add_i_btn.setFixedWidth(78)
        add_i_btn.clicked.connect(self._on_add_current)
        hdr.addWidget(add_i_btn)

        edit_expr_btn = QPushButton("Expr...")
        edit_expr_btn.setFixedWidth(72)
        edit_expr_btn.clicked.connect(self._edit_selected_expression)
        hdr.addWidget(edit_expr_btn)

        delete_btn = QPushButton("- Delete")
        delete_btn.setToolTip("Delete selected output row(s) (Shortcut: Delete key)")
        delete_btn.clicked.connect(self._delete_selected_rows)
        hdr.addWidget(delete_btn)

        # Expression helper
        expr_combo = QComboBox()
        expr_combo.addItems(["--- Quick Expressions ---"] + self.BUILT_IN_EXPRS)
        expr_combo.currentTextChanged.connect(self._on_quick_expr)
        hdr.addWidget(expr_combo)
        self._expr_combo = expr_combo

        layout.addLayout(hdr)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Signal", "Expression", "Plot", "Edit"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setToolTip("Right-click or press Delete key to remove saved outputs.")
        self.table.installEventFilter(self)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table)

        options_row = QHBoxLayout()
        self.chk_save_all_nodes = QCheckBox("Save All Node Voltages")
        self.chk_save_all_currents = QCheckBox("Save All Terminal Currents")
        self.chk_save_all_nodes.setChecked(False)
        self.chk_save_all_currents.setChecked(False)
        options_row.addWidget(self.chk_save_all_nodes)
        options_row.addWidget(self.chk_save_all_currents)
        options_row.addStretch()
        layout.addLayout(options_row)

        # Start empty. Outputs should come from real schematic nets/sources.

    def _on_quick_expr(self, text):
        if text and text != "--- Quick Expressions ---":
            self._add_entry("sig", text)
            self._expr_combo.setCurrentIndex(0)

    def _add_row(self):
        self._add_entry("sig", "V(node)")

    def eventFilter(self, source: QObject, event) -> bool:
        if source is self.table and event.type() == event.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                self._delete_selected_rows()
                return True
        return super().eventFilter(source, event)

    def _available_targets(self) -> tuple[list[str], list[tuple[str, str]]]:
        if callable(self._target_provider):
            try:
                data = self._target_provider() or {}
                nets = sorted({str(n).strip() for n in data.get("nets", []) if str(n).strip()})
                terms_raw = data.get("terminals", [])
                terminals: list[tuple[str, str]] = []
                for entry in terms_raw:
                    if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                        inst = str(entry[0]).strip()
                        pin = str(entry[1]).strip()
                        if inst and pin:
                            terminals.append((inst, pin))
                terminals = sorted(set(terminals))
                return nets, terminals
            except Exception:
                pass
        return [], []

    def _on_add_voltage(self):
        if callable(self._voltage_pick_hook):
            self._voltage_pick_hook()
            return
        nets, _ = self._available_targets()
        if not nets:
            QMessageBox.information(self, "Add V(net)", "No named nets found in this schematic.")
            return
        net, ok = QInputDialog.getItem(self, "Add Voltage Output", "Select net:", nets, 0, False)
        if not ok or not net:
            return
        self._add_entry(net, f"V({net})")

    def _on_add_current(self):
        if callable(self._current_pick_hook):
            self._current_pick_hook()
            return
        _nets, terminals = self._available_targets()
        if not terminals:
            QMessageBox.information(self, "Add I(term)", "No instance terminals found.")
            return
        choices = [f"{inst}.{pin}" for inst, pin in terminals]
        pick, ok = QInputDialog.getItem(self, "Add Current Output", "Select terminal:", choices, 0, False)
        if not ok or not pick:
            return
        inst, pin = pick.split(".", 1)
        # industry-style terminal-current expression placeholder for post-processing.
        expr = f"I({inst}.{pin})"
        self._add_entry(f"{inst}.{pin}", expr)

    def _add_entry(self, sig: str, expr: str):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(sig))
        self.table.setItem(r, 1, QTableWidgetItem(expr))
        chk = QCheckBox()
        chk.setChecked(True)
        self.table.setCellWidget(r, 2, chk)
        edit = QPushButton("...")
        edit.setToolTip("Open expression editor")
        edit.clicked.connect(lambda _checked=False, row=r: self._edit_expression_row(row))
        self.table.setCellWidget(r, 3, edit)
        return r

    def _selected_row(self) -> int:
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        return rows[0] if rows else self.table.currentRow()

    def _edit_selected_expression(self):
        row = self._selected_row()
        if row < 0:
            row = self._add_entry("sig", "V(out)")
        self._edit_expression_row(row)

    def _edit_expression_row(self, row: int):
        if row < 0 or row >= self.table.rowCount() or not callable(self._expression_edit_hook):
            return
        item = self.table.item(row, 1)
        updated = self._expression_edit_hook(item.text().strip() if item else "")
        if updated:
            self.table.setItem(row, 1, QTableWidgetItem(updated))
            sig = self.table.item(row, 0)
            if sig and sig.text().strip() in {"", "sig"}:
                sig.setText(updated)

    def _delete_selected_rows(self):
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)

    def clear_outputs(self):
        self.table.setRowCount(0)

    def _on_selection_changed(self):
        if not callable(self._visualize_hook):
            return
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        if not rows:
            self._visualize_hook({"nets": [], "terminals": []})
            return

        selected_nets: set[str] = set()
        selected_terms: set[tuple[str, str]] = set()
        for row in rows:
            expr_item = self.table.item(row, 1)
            if expr_item is None:
                continue
            expr = expr_item.text().strip()
            if not expr:
                continue
            m_v = re.match(r"^\s*V\(\s*([^)]+)\s*\)\s*$", expr, re.IGNORECASE)
            if m_v:
                selected_nets.add(m_v.group(1).strip())
                continue
            m_term = re.match(r"^\s*I\(\s*([A-Za-z_]\w*)\s*[:.]\s*([A-Za-z_]\w*)\s*\)\s*$", expr, re.IGNORECASE)
            if m_term:
                selected_terms.add((m_term.group(1), m_term.group(2)))
                continue
            m_i = re.match(r"^\s*I\(\s*([^)]+)\s*\)\s*$", expr, re.IGNORECASE)
            if m_i:
                inst = m_i.group(1).strip()
                if inst:
                    sig_item = self.table.item(row, 0)
                    sig = sig_item.text().strip() if sig_item else ""
                    if "." in sig:
                        i_name, i_pin = sig.split(".", 1)
                        if i_name.strip() == inst and i_pin.strip():
                            selected_terms.add((inst, i_pin.strip()))
                continue

        self._visualize_hook({
            "nets": sorted(selected_nets),
            "terminals": sorted(selected_terms),
        })

    def get_save_lines(self) -> list[str]:
        lines = []
        if self.chk_save_all_nodes.isChecked():
            lines.append(".SAVE ALL")
        for r in range(self.table.rowCount()):
            expr_item = self.table.item(r, 1)
            chk = self.table.cellWidget(r, 2)
            if expr_item and isinstance(chk, QCheckBox) and chk.isChecked():
                lines.append(f".SAVE {expr_item.text()}")
        return lines

    def get_expression_lines(self) -> list[str]:
        """Get output expression definitions for post-processing."""
        lines = []
        for r in range(self.table.rowCount()):
            sig_item = self.table.item(r, 0)
            expr_item = self.table.item(r, 1)
            if sig_item and expr_item:
                sig = sig_item.text().strip()
                expr = expr_item.text().strip()
                if sig and expr and not expr.startswith("V(") and not expr.startswith("I("):
                    lines.append(f".PRINT {sig} {expr}")
        return lines


class ParametricSweepWidget(QWidget):
    """Design-variable sweep configuration widget."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Variable Sweeps"))
        add_btn = QPushButton("+ Add Sweep")
        add_btn.setFixedWidth(90)
        add_btn.clicked.connect(self._add_sweep)
        hdr.addWidget(add_btn)
        layout.addLayout(hdr)

        self.sweep_table = QTableWidget(0, 5)
        self.sweep_table.setHorizontalHeaderLabels([
            "Variable", "Start", "Stop", "Step", "Enabled"
        ])
        self.sweep_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.sweep_table.verticalHeader().setVisible(False)
        layout.addWidget(self.sweep_table)

        info = QLabel("Sweeps run as expanded GSPICE jobs with per-run .PARAM overrides.")
        info.setStyleSheet("color: #808080; font-size: 10px; padding: 4px;")
        layout.addWidget(info)

    def _add_sweep(self):
        r = self.sweep_table.rowCount()
        self.sweep_table.insertRow(r)
        self.sweep_table.setItem(r, 0, QTableWidgetItem("var"))
        self.sweep_table.setItem(r, 1, QTableWidgetItem("0"))
        self.sweep_table.setItem(r, 2, QTableWidgetItem("1.8"))
        self.sweep_table.setItem(r, 3, QTableWidgetItem("0.1"))
        chk = QCheckBox()
        chk.setChecked(True)
        self.sweep_table.setCellWidget(r, 4, chk)

    def get_sweep_lines(self) -> list[str]:
        """Return informational comments; SimENV expands variable sweeps into jobs."""
        specs = self.get_sweep_specs()
        if not specs:
            return []
        return [
            f"* Variable sweep expanded by SimENV: {spec['variable']} {spec['start']} {spec['stop']} {spec['step']}"
            for spec in specs
        ]

    def get_sweep_specs(self) -> list[dict]:
        """Return enabled design-variable sweep specifications."""
        specs = []
        for r in range(self.sweep_table.rowCount()):
            var_item = self.sweep_table.item(r, 0)
            start_item = self.sweep_table.item(r, 1)
            stop_item = self.sweep_table.item(r, 2)
            step_item = self.sweep_table.item(r, 3)
            chk = self.sweep_table.cellWidget(r, 4)
            enabled = bool(chk.isChecked()) if isinstance(chk, QCheckBox) else True

            if enabled and var_item and start_item and stop_item and step_item:
                var = var_item.text().strip()
                start = start_item.text().strip()
                stop = stop_item.text().strip()
                step = step_item.text().strip()
                if var:
                    specs.append({
                        "variable": var,
                        "start": start,
                        "stop": stop,
                        "step": step,
                    })
        return specs

    def validation_errors(self) -> list[str]:
        errors = []
        for spec in self.get_sweep_specs():
            var = spec["variable"]
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", var):
                errors.append(f"Variable sweep name '{var}' is not a valid parameter name.")
                continue
            try:
                start = SimulatorBridge._parse_spice_number(spec["start"])
                stop = SimulatorBridge._parse_spice_number(spec["stop"])
                step = SimulatorBridge._parse_spice_number(spec["step"])
            except Exception:
                errors.append(f"Variable sweep '{var}' has invalid start/stop/step values.")
                continue
            if step == 0:
                errors.append(f"Variable sweep '{var}' step cannot be zero.")
            elif (stop - start) * step < 0:
                errors.append(f"Variable sweep '{var}' step sign does not move from start to stop.")
        return errors

    def expanded_points(self, max_points: int = 1000) -> list[tuple[str, dict[str, str]]]:
        """Return Cartesian sweep labels and variable override dictionaries."""
        specs = self.get_sweep_specs()
        if not specs:
            return [("", {})]

        axes: list[list[tuple[str, str, str]]] = []
        total = 1
        for spec in specs:
            var = spec["variable"]
            start = SimulatorBridge._parse_spice_number(spec["start"])
            stop = SimulatorBridge._parse_spice_number(spec["stop"])
            step = SimulatorBridge._parse_spice_number(spec["step"])
            values = []
            increasing = step > 0
            eps = abs(step) * 1e-9
            value = start
            count = 0
            while (value <= stop + eps) if increasing else (value >= stop - eps):
                value_text = f"{value:.12g}"
                values.append((var, value_text, f"{var}={value_text}"))
                count += 1
                if count > max_points:
                    raise ValueError(f"Variable sweep '{var}' exceeds {max_points} points.")
                value += step
            axes.append(values)
            total *= max(1, len(values))
            if total > max_points:
                raise ValueError(f"Variable sweep expansion exceeds {max_points} total runs.")

        points: list[tuple[str, dict[str, str]]] = [("", {})]
        for axis in axes:
            next_points = []
            for prefix, overrides in points:
                for var, value, label in axis:
                    merged = dict(overrides)
                    merged[var] = value
                    full_label = label if not prefix else f"{prefix}, {label}"
                    next_points.append((full_label, merged))
            points = next_points
        return points or [("", {})]


class MeasurementSetupWidget(QWidget):
    """Measurement setup UI for .MEASURE statements."""

    MEAS_TYPES = [
        "TRIG", "TARG", "AVG", "RMS", "MIN", "MAX", "PP",
        "FIND", "WHEN", "DERIV", "INTEG", "PARAM"
    ]

    def __init__(self, parent=None, expression_edit_hook=None):
        super().__init__(parent)
        self._expression_edit_hook = expression_edit_hook
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Measurements"))
        add_btn = QPushButton("+ Add")
        add_btn.setFixedWidth(60)
        add_btn.clicked.connect(self._add_row)
        hdr.addWidget(add_btn)
        edit_btn = QPushButton("Expr...")
        edit_btn.setFixedWidth(72)
        edit_btn.clicked.connect(self._edit_selected_expression)
        hdr.addWidget(edit_btn)
        layout.addLayout(hdr)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "Name", "Type", "Expression", "TARG/TRIG", "From", "To", "Edit"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

    def _add_row(self):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(f"meas_{r}"))

        type_combo = QComboBox()
        type_combo.addItems(self.MEAS_TYPES)
        self.table.setCellWidget(r, 1, type_combo)

        self.table.setItem(r, 2, QTableWidgetItem("V(out)"))
        self.table.setItem(r, 3, QTableWidgetItem(""))
        self.table.setItem(r, 4, QTableWidgetItem(""))
        self.table.setItem(r, 5, QTableWidgetItem(""))
        edit = QPushButton("...")
        edit.clicked.connect(lambda _checked=False, row=r: self._edit_expression_row(row, 2))
        self.table.setCellWidget(r, 6, edit)

    def _edit_selected_expression(self):
        row = self.table.currentRow()
        if row < 0:
            self._add_row()
            row = self.table.rowCount() - 1
        self._edit_expression_row(row, 2)

    def _edit_expression_row(self, row: int, col: int):
        if row < 0 or row >= self.table.rowCount() or not callable(self._expression_edit_hook):
            return
        item = self.table.item(row, col)
        updated = self._expression_edit_hook(item.text().strip() if item else "")
        if updated:
            self.table.setItem(row, col, QTableWidgetItem(updated))

    def get_measure_lines(self) -> list[str]:
        lines = []
        for r in range(self.table.rowCount()):
            name_item = self.table.item(r, 0)
            type_widget = self.table.cellWidget(r, 1)
            expr_item = self.table.item(r, 2)
            targ_item = self.table.item(r, 3)
            from_item = self.table.item(r, 4)
            to_item = self.table.item(r, 5)

            if not name_item or not expr_item or not type_widget:
                continue

            name = name_item.text().strip()
            mtype = type_widget.currentText()
            expr = expr_item.text().strip()

            if not name or not expr:
                continue

            parts = [f".MEASURE {mtype} {name}"]

            if mtype in ("TRIG", "TARG"):
                trig_expr = targ_item.text().strip() if targ_item else ""
                if trig_expr:
                    parts.append(f"{mtype}={expr}")
                    parts.append(trig_expr)
                else:
                    parts.append(expr)
            elif mtype == "FIND":
                parts.append(f"WHEN {expr}={targ_item.text().strip() if targ_item else '0'}")
            elif mtype == "WHEN":
                parts.append(f"{expr}={targ_item.text().strip() if targ_item else '0'}")
            else:
                parts.append(expr)

            if from_item and from_item.text().strip():
                parts.append(f"FROM={from_item.text().strip()}")
            if to_item and to_item.text().strip():
                parts.append(f"TO={to_item.text().strip()}")

            lines.append(" ".join(parts))
        return lines


class SpecSetupWidget(QWidget):
    """Simple pass/fail specs for result waveforms."""

    METRICS = ["final", "min", "max", "mean", "pp"]

    def __init__(self, parent=None, expression_edit_hook=None):
        super().__init__(parent)
        self._expression_edit_hook = expression_edit_hook
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Specs"))
        add_btn = QPushButton("+ Add")
        add_btn.setFixedWidth(60)
        add_btn.clicked.connect(self._add_row)
        hdr.addWidget(add_btn)
        edit_btn = QPushButton("Expr...")
        edit_btn.setFixedWidth(72)
        edit_btn.clicked.connect(self._edit_selected_expression)
        hdr.addWidget(edit_btn)
        layout.addLayout(hdr)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Name", "Expression", "Metric", "Min", "Max", "Enable", "Edit"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

    def _add_row(self):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(f"spec_{r}"))
        self.table.setItem(r, 1, QTableWidgetItem("V(out)"))
        metric = QComboBox()
        metric.addItems(self.METRICS)
        self.table.setCellWidget(r, 2, metric)
        self.table.setItem(r, 3, QTableWidgetItem(""))
        self.table.setItem(r, 4, QTableWidgetItem(""))
        enabled = QCheckBox()
        enabled.setChecked(True)
        self.table.setCellWidget(r, 5, enabled)
        edit = QPushButton("...")
        edit.clicked.connect(lambda _checked=False, row=r: self._edit_expression_row(row))
        self.table.setCellWidget(r, 6, edit)

    def _edit_selected_expression(self):
        row = self.table.currentRow()
        if row < 0:
            self._add_row()
            row = self.table.rowCount() - 1
        self._edit_expression_row(row)

    def _edit_expression_row(self, row: int):
        if row < 0 or row >= self.table.rowCount() or not callable(self._expression_edit_hook):
            return
        item = self.table.item(row, 1)
        updated = self._expression_edit_hook(item.text().strip() if item else "")
        if updated:
            self.table.setItem(row, 1, QTableWidgetItem(updated))

    def get_specs(self) -> list[SpecLimit]:
        specs: list[SpecLimit] = []
        for r in range(self.table.rowCount()):
            name = self.table.item(r, 0).text().strip() if self.table.item(r, 0) else f"spec_{r}"
            expr = self.table.item(r, 1).text().strip() if self.table.item(r, 1) else ""
            metric_widget = self.table.cellWidget(r, 2)
            metric = metric_widget.currentText() if isinstance(metric_widget, QComboBox) else "final"
            min_value = self.table.item(r, 3).text().strip() if self.table.item(r, 3) else ""
            max_value = self.table.item(r, 4).text().strip() if self.table.item(r, 4) else ""
            enabled_widget = self.table.cellWidget(r, 5)
            enabled = bool(enabled_widget.isChecked()) if isinstance(enabled_widget, QCheckBox) else True
            if expr:
                specs.append(SpecLimit(name, expr, metric, min_value, max_value, enabled))
        return specs


class StimulusEditorWidget(QWidget):
    """Stimulus source editor for DC, AC, and time-domain sources."""

    STIM_TYPES = ["DC", "AC", "PULSE", "SIN", "PWL", "SFFM", "EXP"]

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Stimulus Sources"))
        add_btn = QPushButton("+ Add")
        add_btn.setFixedWidth(60)
        add_btn.clicked.connect(self._add_row)
        hdr.addWidget(add_btn)
        layout.addLayout(hdr)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Source Name", "+ Node", "- Node", "Type", "Parameters"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

    def _add_row(self):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem("V1"))
        self.table.setItem(r, 1, QTableWidgetItem("net1"))
        self.table.setItem(r, 2, QTableWidgetItem("0"))

        type_combo = QComboBox()
        type_combo.addItems(self.STIM_TYPES)
        type_combo.currentTextChanged.connect(lambda t, row=r: self._update_params(row, t))
        self.table.setCellWidget(r, 3, type_combo)

        self.table.setItem(r, 4, QTableWidgetItem("1.8"))

    def _update_params(self, row, stim_type):
        defaults = {
            "DC": "1.8",
            "AC": "DC 0 AC 1",
            "PULSE": "PULSE(0 1.8 1n 1n 1n 5n 10n)",
            "SIN": "SIN(0.9 0.9 1G 1n 0)",
            "PWL": "PWL(0 0 1n 1.8 10n 1.8)",
            "SFFM": "SFFM(1.8 0.1 1G 5 1M)",
            "EXP": "EXP(0 1.8 1n 100n 5n 200n)",
        }
        self.table.setItem(row, 4, QTableWidgetItem(defaults.get(stim_type, "")))

    def get_stimulus_lines(self) -> list[str]:
        lines = []
        for r in range(self.table.rowCount()):
            name_item = self.table.item(r, 0)
            plus_item = self.table.item(r, 1)
            minus_item = self.table.item(r, 2)
            type_widget = self.table.cellWidget(r, 3)
            param_item = self.table.item(r, 4)

            if not name_item or not plus_item or not minus_item or not type_widget or not param_item:
                continue

            name = name_item.text().strip()
            plus = plus_item.text().strip()
            minus = minus_item.text().strip()
            stim_type = type_widget.currentText()
            params = param_item.text().strip()

            if not name or not plus or not minus or not params:
                continue

            lines.append(f"* Stimulus: {name}")
            if stim_type == "DC":
                lines.append(f"{name} {plus} {minus} DC {params}")
            elif stim_type == "AC":
                lines.append(f"{name} {plus} {minus} {self._format_ac_source_tail(params)}")
            else:
                lines.append(f"{name} {plus} {minus} {params}")
        return lines

    @staticmethod
    def _format_ac_source_tail(params: str) -> str:
        text = str(params or "").strip()
        if not text:
            return "DC 0 AC 1"
        upper = text.upper()
        if upper.startswith("DC ") or upper.startswith("AC "):
            return text
        pieces = text.split()
        if len(pieces) >= 2:
            return f"DC {pieces[0]} AC {' '.join(pieces[1:])}"
        return f"DC 0 AC {text}"


class ConvergenceHelpersWidget(QWidget):
    """Convergence helpers: .NODESET, .IC, .LOADBIAS, .SAVEBIAS with simulation setup style UI."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # NODESET
        nodeset_group = QGroupBox("NODESET (Initial Voltage Guess)")
        nodeset_layout = QVBoxLayout(nodeset_group)
        self.nodeset_table = self._create_table("NODESET")
        nodeset_layout.addWidget(self.nodeset_table)

        ns_btn_layout = QHBoxLayout()
        ns_add = QPushButton("+ Add")
        ns_add.setToolTip("Add a new NODESET entry")
        ns_add.clicked.connect(lambda: self._add_row(self.nodeset_table))
        ns_delete = QPushButton("- Delete")
        ns_delete.setToolTip("Delete selected NODESET row(s) (Shortcut: Delete key)")
        ns_delete.clicked.connect(lambda: self._delete_selected_rows(self.nodeset_table))
        ns_clear = QPushButton("Clear All")
        ns_clear.setToolTip("Clear all NODESET entries")
        ns_clear.clicked.connect(lambda: self._clear_table(self.nodeset_table))
        ns_btn_layout.addWidget(ns_add)
        ns_btn_layout.addWidget(ns_delete)
        ns_btn_layout.addWidget(ns_clear)
        ns_btn_layout.addStretch()
        nodeset_layout.addLayout(ns_btn_layout)
        layout.addWidget(nodeset_group)

        # IC
        ic_group = QGroupBox("IC (Initial Conditions)")
        ic_layout = QVBoxLayout(ic_group)
        self.ic_table = self._create_table("IC")
        ic_layout.addWidget(self.ic_table)

        ic_btn_layout = QHBoxLayout()
        ic_add = QPushButton("+ Add")
        ic_add.setToolTip("Add a new Initial Condition (.IC) entry")
        ic_add.clicked.connect(lambda: self._add_row(self.ic_table))
        ic_delete = QPushButton("- Delete")
        ic_delete.setToolTip("Delete selected Initial Condition row(s) (Shortcut: Delete key)")
        ic_delete.clicked.connect(lambda: self._delete_selected_rows(self.ic_table))
        ic_clear = QPushButton("Clear All")
        ic_clear.setToolTip("Clear all Initial Condition entries")
        ic_clear.clicked.connect(lambda: self._clear_table(self.ic_table))
        ic_btn_layout.addWidget(ic_add)
        ic_btn_layout.addWidget(ic_delete)
        ic_btn_layout.addWidget(ic_clear)
        ic_btn_layout.addStretch()
        ic_layout.addLayout(ic_btn_layout)
        layout.addWidget(ic_group)

        layout.addStretch()

    def _create_table(self, kind: str) -> QTableWidget:
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["Node Name", "Initial Voltage"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(lambda pos, t=table, k=kind: self._show_context_menu(t, pos, k))
        table.installEventFilter(self)
        table.setToolTip(f"Right-click or press Delete key to remove {kind} entries.")
        return table

    def eventFilter(self, source: QObject, event) -> bool:
        if isinstance(source, QTableWidget) and event.type() == event.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                self._delete_selected_rows(source)
                return True
        return super().eventFilter(source, event)

    def _add_row(self, table: QTableWidget, node="", value="0"):
        r = table.rowCount()
        table.insertRow(r)
        node_item = QTableWidgetItem(node)
        val_item = QTableWidgetItem(value)
        table.setItem(r, 0, node_item)
        table.setItem(r, 1, val_item)
        table.selectRow(r)
        table.editItem(node_item)

    @staticmethod
    def _convergence_line(kind: str, node: str, value: str) -> str:
        node = str(node or "").strip()
        value = str(value or "").strip()
        if not node or node.lower() == "node" or node.startswith("*"):
            return ""
        return f".{kind} {node}={value or '0'}"

    def _delete_selected_rows(self, table: QTableWidget):
        selected_rows = sorted({item.row() for item in table.selectedItems()}, reverse=True)
        if not selected_rows:
            return
        for r in selected_rows:
            table.removeRow(r)

    def _clear_table(self, table: QTableWidget):
        table.setRowCount(0)

    def _toggle_disable_selected_rows(self, table: QTableWidget):
        selected_rows = sorted({item.row() for item in table.selectedItems()})
        for r in selected_rows:
            node_item = table.item(r, 0)
            if not node_item:
                continue
            text = node_item.text().strip()
            if text.startswith("*"):
                # Re-enable
                node_item.setText(text.lstrip("*").strip())
                node_item.setForeground(QColor("#dce6f2"))
            else:
                # Comment out / disable
                node_item.setText(f"* {text}")
                node_item.setForeground(QColor("#7f8c9d"))

    def _show_context_menu(self, table: QTableWidget, pos, kind: str):
        row = table.rowAt(pos.y())
        menu = QMenu(self)

        act_add = QAction(f"Add {kind} Entry", self)
        act_add.triggered.connect(lambda: self._add_row(table))
        menu.addAction(act_add)

        if row >= 0 or table.selectedItems():
            act_delete = QAction(f"Delete Selected {kind}(s)", self)
            act_delete.setShortcut(QKeySequence("Delete"))
            act_delete.triggered.connect(lambda: self._delete_selected_rows(table))
            menu.addAction(act_delete)

            act_disable = QAction(f"Enable / Disable Selected {kind}(s)", self)
            act_disable.triggered.connect(lambda: self._toggle_disable_selected_rows(table))
            menu.addAction(act_disable)

        menu.addSeparator()
        act_clear = QAction(f"Clear All {kind}s", self)
        act_clear.triggered.connect(lambda: self._clear_table(table))
        menu.addAction(act_clear)

        menu.exec(table.viewport().mapToGlobal(pos))

    def get_nodeset_lines(self) -> list[str]:
        lines = []
        for r in range(self.nodeset_table.rowCount()):
            node_item = self.nodeset_table.item(r, 0)
            val_item = self.nodeset_table.item(r, 1)
            if node_item and val_item:
                line = self._convergence_line("NODESET", node_item.text(), val_item.text())
                if line:
                    lines.append(line)
        return lines

    def get_ic_lines(self) -> list[str]:
        lines = []
        for r in range(self.ic_table.rowCount()):
            node_item = self.ic_table.item(r, 0)
            val_item = self.ic_table.item(r, 1)
            if node_item and val_item:
                line = self._convergence_line("IC", node_item.text(), val_item.text())
                if line:
                    lines.append(line)
        return lines


class ADEWindow(QMainWindow):
    """SimENV: tabbed simulation environment window.

    The class name remains unchanged so older callers keep working.
    """

    def __init__(self, db: LibraryDatabase, library: str, cell: str,
                 ciw=None, pdk_registry=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.library = library
        self.cell = cell
        self.ciw = ciw
        self._waveform_viewers = []
        self._attached_sigview = None
        self._last_sigview_waveforms: dict = {}
        self._last_sigview_payload: dict = {}
        self._expression_history: list[str] = []
        self._result_waveforms_by_row: dict[int, dict] = {}
        self._result_all_waveforms_by_row: dict[int, dict] = {}
        self._spec_results_by_row: dict[int, list[dict]] = {}
        self._baseline_run_name = ""
        self._result_section_rows: set[int] = set()
        self._result_section_corners: set[str] = set()
        self._corner_result_rows: dict[str, list[int]] = {}
        self._corner_sweep_result_rows: dict[tuple[str, str], list[int]] = {}
        self._disabled_run_cells: set[tuple[str, str]] = set()
        self._run_selected_cells_once: set[tuple[str, str]] = set()
        self._run_matrix_status: dict[tuple[str, str], str] = {}
        self._sim_thread: QThread | None = None
        self._sim_worker: SimEnvSimulationWorker | None = None
        self._sim_jobs_total = 0
        self._sim_jobs_done = 0
        self._sim_merged_waveforms: dict = {}
        self._sim_cancel_requested = False
        self._sim_log_window: SimulationMonitorWindow | None = None
        self._startup_warnings: list[str] = []
        self._pdk_registry = pdk_registry
        self._pdk_registry_loaded = pdk_registry is not None
        self._pdk_combo_populated = False
        self._pending_simenv_pdk = ""
        self._sim_status_refresh_scheduled = False
        self._corner_model_directives: dict[str, list[ModelDirective]] = {}
        self._global_model_directives: list[ModelDirective] = []
        self._model_bindings: list[DeviceModelBinding] = []
        self._model_setup_name = "default"

        self.setWindowTitle(f"Lumen SimENV - {cell} [{library}]")
        apply_window_branding(self)
        self.setMinimumSize(1100, 720)
        self.resize(1280, 820)

        self._analysis_tabs: dict[str, AnalysisSetupWidget] = {}
        self._current_simulator = "GSPICE"
        try:
            self._current_simulator = SimulatorRuntimeManager(
                str(getattr(self.db, "workspace", ""))
            ).get_active_simulator()
        except Exception:
            self._current_simulator = "GSPICE"
        self._missing_sim_prompted: set[str] = set()
        self._sim_dump_dir = self._default_sim_dump_dir()
        self._sim_threads = 1
        self._sim_timeout = 0
        self._sim_accuracy = "High"
        self._sim_tolerance_override = ""
        self._sim_method = "Auto"
        self._sim_save_mode = "all"
        self._sim_adaptive_maxstep = True
        self._sim_save_adaptive_points = True
        self._sim_prefer_klu = True
        self._sim_verbose_compat = False
        self._simenv_autosave_suspended = False
        self._build_ui()
        self._apply_ade_workbench_style()
        self._create_menus()
        self._create_toolbar()
        self._create_status_bar()
        self._load_simenv_view()
        for warning in self._startup_warnings:
            self._log(warning)

    def _ensure_pdk_registry(self):
        """Load the PDK registry on demand; discovery is too slow for window construction."""
        if self._pdk_registry_loaded:
            return self._pdk_registry
        self._pdk_registry_loaded = True
        self._pdk_registry = self._create_pdk_registry()
        return self._pdk_registry

    def _create_pdk_registry(self):
        """Create a PDK registry scoped to the design workspace."""
        workspace = str(getattr(self.db, "workspace", "")) or ""
        try:
            return get_registry(workspace)
        except Exception as exc:
            self._startup_warnings.append(f"PDK registry unavailable: {exc}")
            return None

    def _default_sim_dump_dir(self) -> str:
        workspace = Path(str(getattr(self.db, "workspace", "")) or ".")
        return str((workspace / "runs" / "simenv").resolve())

    def _resolved_sim_dump_dir(self) -> str:
        raw = str(self._sim_dump_dir or "").strip()
        if not raw:
            raw = self._default_sim_dump_dir()
            self._sim_dump_dir = raw
        return str(Path(raw).expanduser().resolve())

    def _build_bridge(self) -> SimulatorBridge:
        dump_dir = self._resolved_sim_dump_dir()
        os.makedirs(dump_dir, exist_ok=True)
        runtime = SimulatorRuntimeManager(str(getattr(self.db, "workspace", "")))
        runtime.apply_environment_overrides()
        exe = runtime.get_active_executable(self._current_simulator)
        return SimulatorBridge(
            self._current_simulator,
            exe_path=exe,
            work_dir=dump_dir,
            save_mode=self._sim_save_mode,
            adaptive_maxstep=self._sim_adaptive_maxstep,
            verbose_compat=self._sim_verbose_compat,
        )

    def _sim_thread_count(self) -> int:
        value = self._sim_threads
        if hasattr(self, "thread_spin"):
            value = self.thread_spin.value()
        return max(1, min(16, int(value or 1)))

    def _on_threads_changed(self, value: int):
        self._sim_threads = self._sim_thread_count()
        if hasattr(self, "thread_spin") and self.thread_spin.value() != self._sim_threads:
            self.thread_spin.setValue(self._sim_threads)
        self._log(f"{self._current_simulator} threads set to: {self._sim_threads}")
        self._refresh_run_plan()
        self._save_simenv_view_silent()

    def _accuracy_presets(self) -> dict:
        return {name: dict(values) for name, values in GSPICE_ACCURACY_PRESETS.items()}

    def _accuracy_options_line(self) -> str:
        preset = self._accuracy_presets().get(self._sim_accuracy, self._accuracy_presets()["High"])
        tolerance_override = str(getattr(self, "_sim_tolerance_override", "") or "").strip()
        if tolerance_override and ADEWindow._is_tighter_tolerance_override(tolerance_override, preset):
            preset = dict(preset)
            preset["RELTOL"] = tolerance_override
            preset["LTE_RELTOL"] = tolerance_override
        if self._current_simulator != "GSPICE":
            compatible = ["RELTOL", "VNTOL", "ABSTOL"]
            return ".OPTIONS " + " ".join(
                f"{key}={preset[key]}" for key in compatible if key in preset
            )
        accuracy = self._sim_accuracy.replace(" ", "").upper()
        method = self._sim_method_token()
        parts = [
            f"ACCURACY={accuracy}",
            f"METHOD={method}",
            "ADAPTIVE=1",
            f"SAVE={self._sim_save_mode_token()}",
            f"SOLVER={'KLU' if getattr(self, '_sim_prefer_klu', True) else 'AUTO'}",
            "TRAN_STAMP_CACHE=1",
            *[f"{key}={value}" for key, value in preset.items()],
        ]
        if self._sim_adaptive_maxstep:
            parts.append("MAXSTEP=AUTO")
        if getattr(self, "_sim_save_adaptive_points", True):
            parts.append("SAVEADAPTIVE=1")
        return ".OPTIONS " + " ".join(parts)

    @staticmethod
    def _is_tighter_tolerance_override(value: str, preset: dict) -> bool:
        try:
            parsed = SimulatorBridge._parse_spice_number(value)
            preset_reltol = SimulatorBridge._parse_spice_number(preset.get("RELTOL", "1e-3"))
        except Exception:
            return False
        return parsed > 0 and parsed <= preset_reltol

    def _sim_method_token(self) -> str:
        return {
            "Auto": "AUTO",
            "Backward Euler": "BE",
            "Trapezoidal": "TRAP",
            "Gear2": "GEAR2",
        }.get(str(self._sim_method or "Auto"), "AUTO")

    def _sim_save_mode_token(self) -> str:
        return {
            "all": "ALL",
            "selected": "SELECTED",
            "none": "NONE",
        }.get(str(self._sim_save_mode or "all").lower(), "ALL")

    def _sim_save_mode_label(self) -> str:
        return {
            "all": "All",
            "selected": "Selected",
            "none": "None",
        }.get(str(self._sim_save_mode or "all").lower(), "All")

    def _accuracy_transient_defaults(self, stop: str = "10u") -> dict:
        return gspice_transient_defaults(self._sim_accuracy, stop)

    def _analysis_spice_line(self, name: str, widget: AnalysisSetupWidget) -> str:
        """Build an analysis line, resolving blank transient fields from accuracy."""
        if name == "AC Small-Signal":
            values = widget.get_values()
            sweep = str(values.get("Sweep", "DEC") or "DEC").strip()
            points = str(values.get("Points", "100") or "100").strip()
            fstart = str(values.get("Fstart", "1") or "1").strip()
            fstop = str(values.get("Fstop", "10G") or "10G").strip()
            ac_line = f"{ANALYSES[name]['cmd']} {sweep} {points} {fstart} {fstop}"
            if bool(values.get("BiasOP", True)):
                return "* AC bias point\n.OP\n" + ac_line
            return ac_line
        if name != "Transient":
            return widget.get_spice_line()

        def auto_value(value) -> str:
            text = str(value or "").strip()
            return "" if text.lower() in {"auto", "default"} else text

        values = widget.get_values()
        stop = auto_value(values.get("Stop", "")) or "10u"
        defaults = self._accuracy_transient_defaults(stop)
        step = auto_value(values.get("Step", "")) or defaults["step"]
        start = auto_value(values.get("Start", ""))
        maxstep = auto_value(values.get("MaxStep", "")) or defaults["maxstep"]

        parts = [ANALYSES[name]["cmd"], step, stop]
        start_is_zero = start in {"", "0", "0.0"}
        if (start and not start_is_zero) or maxstep:
            parts.append(start or "0")
        if maxstep:
            parts.append(maxstep)
        if bool(values.get("UIC", False)) or ADEWindow._has_transient_initial_conditions(self):
            parts.append("UIC")
        return " ".join(parts)

    def _has_transient_initial_conditions(self) -> bool:
        convergence_widget = getattr(self, "convergence_widget", None)
        if not convergence_widget or not hasattr(convergence_widget, "get_ic_lines"):
            return False
        try:
            return bool(convergence_widget.get_ic_lines())
        except Exception:
            return False

    def _on_accuracy_changed(self, text: str):
        self._sim_accuracy = text if text in self._accuracy_presets() else "High"
        self._log(f"{self._current_simulator} accuracy set to: {self._sim_accuracy}")
        self._refresh_run_plan()
        self._save_simenv_view_silent()

    def _sim_timeout_seconds(self) -> int:
        value = self._sim_timeout
        if hasattr(self, "timeout_spin"):
            value = self.timeout_spin.value()
        return max(0, min(86400, int(value or 0)))

    def _on_timeout_changed(self, value: int):
        self._sim_timeout = self._sim_timeout_seconds()
        label = "Auto" if self._sim_timeout <= 0 else f"{self._sim_timeout}s"
        self._log(f"{self._current_simulator} timeout set to: {label}")
        self._refresh_run_plan()
        self._save_simenv_view_silent()

    def _on_tolerance_override_changed(self, text: str):
        value = str(text or "").strip()
        if value:
            try:
                parsed = SimulatorBridge._parse_spice_number(value)
            except Exception:
                parsed = None
            if parsed is None or parsed <= 0:
                self._log(f"Ignored invalid tolerance override: {value}")
                if hasattr(self, "tolerance_override_edit"):
                    self.tolerance_override_edit.setText(self._sim_tolerance_override)
                return
            preset = self._accuracy_presets().get(self._sim_accuracy, self._accuracy_presets()["High"])
            if not self._is_tighter_tolerance_override(value, preset):
                self._log(
                    f"Ignored loose tolerance override: {value}; "
                    f"{self._sim_accuracy} preset RELTOL is {preset.get('RELTOL', '1e-3')}"
                )
                if hasattr(self, "tolerance_override_edit"):
                    self.tolerance_override_edit.setText(self._sim_tolerance_override)
                return
        self._sim_tolerance_override = value
        label = self._sim_tolerance_override or "preset"
        self._log(f"{self._current_simulator} tolerance override set to: {label}")
        self._refresh_run_plan()
        self._save_simenv_view_silent()

    def _on_method_changed(self, text: str):
        allowed = {"Auto", "Backward Euler", "Trapezoidal", "Gear2"}
        self._sim_method = text if text in allowed else "Auto"
        self._log(f"{self._current_simulator} transient method set to: {self._sim_method}")
        self._refresh_run_plan()
        self._save_simenv_view_silent()

    def _on_save_mode_changed(self, text: str):
        token = str(text or "All").strip().lower()
        self._sim_save_mode = token if token in {"all", "selected", "none"} else "all"
        self._log(f"{self._current_simulator} save mode set to: {self._sim_save_mode_label()}")
        self._refresh_run_plan()
        self._save_simenv_view_silent()

    def _on_adaptive_maxstep_changed(self, checked: bool):
        self._sim_adaptive_maxstep = bool(checked)
        state = "enabled" if self._sim_adaptive_maxstep else "disabled"
        self._log(f"{self._current_simulator} adaptive transient maxstep {state}")
        self._refresh_run_plan()
        self._save_simenv_view_silent()

    def _on_save_adaptive_points_changed(self, checked: bool):
        self._sim_save_adaptive_points = bool(checked)
        state = "enabled" if self._sim_save_adaptive_points else "disabled"
        self._log(f"{self._current_simulator} transient internal-point RAW output {state}")
        self._refresh_run_plan()
        self._save_simenv_view_silent()

    def _on_klu_changed(self, checked: bool):
        self._sim_prefer_klu = bool(checked)
        runtime = SimulatorRuntimeManager(str(getattr(self.db, "workspace", "")))
        ok = runtime.set_gspice_prefer_klu(self._sim_prefer_klu)
        if checked and not ok:
            self._sim_prefer_klu = False
            if hasattr(self, "klu_check"):
                self.klu_check.blockSignals(True)
                self.klu_check.setChecked(False)
                self.klu_check.blockSignals(False)
            self._log("GSPICE KLU build not found; build/select a SuiteSparse-KLU GSPICE runtime.")
        else:
            self._log(f"GSPICE KLU solver {'enabled' if self._sim_prefer_klu else 'disabled'}")
        self._schedule_simulator_status_refresh()
        self._refresh_run_plan()
        self._save_simenv_view_silent()

    def _find_schematic_editor(self):
        """Find an open schematic editor matching this SimENV target cell."""
        parent = self.parent()
        if parent is not None and hasattr(parent, "editor"):
            editor = getattr(parent, "editor", None)
            if (
                editor is not None
                and getattr(editor, "library", "") == self.library
                and getattr(editor, "cell", "") == self.cell
            ):
                return editor, parent

        if self.ciw and hasattr(self.ciw, "_editor_windows"):
            for win in list(getattr(self.ciw, "_editor_windows", [])):
                if not getattr(win, "isVisible", lambda: False)():
                    continue
                if getattr(win, "library", "") != self.library or getattr(win, "cell", "") != self.cell:
                    continue
                editor = getattr(win, "editor", None)
                if editor is not None:
                    return editor, win
        return None, None

    def _clear_schematic_dc_annotations_for_run(self):
        editor, _win = self._find_schematic_editor()
        if editor is not None and hasattr(editor, "clear_dc_annotations"):
            editor.clear_dc_annotations()

    def _collect_output_targets(self) -> dict:
        """Collect net and terminal targets for output/save convenience pickers."""
        data = self.db.load_view(self.library, self.cell, "schematic") or {}
        gen = NetlistGenerator(self.db)
        nets: set[str] = set()
        terminals: set[tuple[str, str]] = set()

        try:
            net_map = gen._build_net_map_connectivity(data)
        except Exception:
            net_map = gen._build_net_map(data)

        for value in net_map.values():
            text = str(value or "").strip()
            if text and text not in ("?",):
                nets.add(text)

        for wire in data.get("wires", []):
            name = str(wire.get("net", "")).strip()
            if name:
                nets.add(name)
        for label in data.get("labels", []):
            name = str(label.get("text", "")).strip()
            if name:
                nets.add(name)
        for pin in data.get("pins", []):
            name = str(pin.get("name", "")).strip()
            if name:
                nets.add(name)

        for inst in data.get("instances", []):
            iname = str(inst.get("name", "")).strip()
            if not iname:
                continue
            lib = str(inst.get("library", "")).strip()
            cell = str(inst.get("cell", "")).strip()
            if not lib or not cell:
                continue
            pins = gen._pins_for_instance(lib, cell)
            for pin in pins:
                if isinstance(pin, dict):
                    pname = str(pin.get("name", "")).strip()
                else:
                    pname = str(pin).strip()
                if pname:
                    terminals.add((iname, pname))

        return {
            "nets": sorted(nets),
            "terminals": sorted(terminals),
        }

    def _visualize_output_targets(self, selection: dict):
        """Highlight selected output nets and current terminals on the schematic."""
        editor, editor_win = self._find_schematic_editor()
        if editor is None:
            return

        nets = [str(x).strip() for x in (selection.get("nets", []) if isinstance(selection, dict) else []) if str(x).strip()]
        terminals_raw = selection.get("terminals", []) if isinstance(selection, dict) else []
        terminals: list[tuple[str, str]] = []
        for entry in terminals_raw:
            if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                inst = str(entry[0]).strip()
                pin = str(entry[1]).strip()
                if inst and pin:
                    terminals.append((inst, pin))

        editor.clear_probe_overlays()
        if nets:
            editor.highlight_nets(nets)
        if terminals:
            editor.mark_current_terminals(terminals)
        editor.redraw()

        if editor_win is not None:
            editor_win.raise_()
            editor_win.activateWindow()

    def _ensure_schematic_editor_for_pick(self):
        editor, editor_win = self._find_schematic_editor()
        if editor is not None:
            return editor, editor_win

        if self.ciw and hasattr(self.ciw, "open_schematic_editor"):
            self.ciw.open_schematic_editor(self.library, self.cell, "schematic")
            editor, editor_win = self._find_schematic_editor()
        return editor, editor_win

    def _start_voltage_pick(self):
        self._start_schematic_output_pick("voltage")

    def _start_current_pick(self):
        self._start_schematic_output_pick("current")

    def _start_schematic_output_pick(self, kind: str, target_field=None):
        editor, editor_win = self._ensure_schematic_editor_for_pick()
        if editor is None:
            QMessageBox.information(
                self,
                "Pick Output",
                "Open the matching schematic view first, then pick the output again.",
            )
            return

        self._analysis_output_pick_field = target_field
        try:
            editor.output_pick_requested.disconnect(self._on_schematic_output_picked)
        except (TypeError, RuntimeError):
            pass
        editor.output_pick_requested.connect(self._on_schematic_output_picked)
        editor.begin_output_pick(kind)

        if editor_win is not None:
            editor_win.raise_()
            editor_win.activateWindow()
            if hasattr(editor_win, "statusBar"):
                if target_field is not None:
                    message = "Pick a voltage net for the noise output"
                else:
                    noun = "net for voltage" if kind == "voltage" else "terminal for current"
                    message = f"Pick a {noun} output for SimENV"
                editor_win.statusBar().showMessage(message, 7000)
        self._log(f"Pick {'voltage net' if kind == 'voltage' else 'current terminal'} from schematic...")

    def _on_schematic_output_picked(self, kind: str, payload: object):
        if not isinstance(payload, dict):
            return

        if kind == "voltage":
            net = str(payload.get("net", "")).strip()
            if not net:
                return
            target_field = getattr(self, "_analysis_output_pick_field", None)
            if isinstance(target_field, QLineEdit):
                target_field.setText(f"V({net})")
                self._analysis_output_pick_field = None
                self._visualize_output_targets({"nets": [net], "terminals": []})
                self._log(f"Selected noise output: V({net})")
                self._refresh_run_plan()
                self._save_simenv_view_silent()
                return
            row = self.outputs_widget._add_entry(net, f"V({net})")
            self.outputs_widget.table.selectRow(row)
            self._visualize_output_targets({"nets": [net], "terminals": []})
            self._log(f"Added voltage output: V({net})")

        elif kind == "current":
            inst = str(payload.get("instance", "")).strip()
            pin = str(payload.get("pin", "")).strip()
            if not inst or not pin:
                return
            signal = f"{inst}.{pin}"
            row = self.outputs_widget._add_entry(signal, f"I({signal})")
            self.outputs_widget.table.selectRow(row)
            self._visualize_output_targets({"nets": [], "terminals": [(inst, pin)]})
            self._log(f"Added current output: I({signal})")
        else:
            return

        self._refresh_run_plan()
        self._save_simenv_view_silent()

    def _add_or_select_output_expression(self, signal: str, expression: str, plot: bool = True) -> int:
        sig = str(signal or expression or "sig").strip() or "sig"
        expr = str(expression or "").strip()
        if not expr:
            return -1
        table = self.outputs_widget.table
        for row in range(table.rowCount()):
            sig_item = table.item(row, 0)
            expr_item = table.item(row, 1)
            cur_sig = sig_item.text().strip() if sig_item else ""
            cur_expr = expr_item.text().strip() if expr_item else ""
            if self._trace_key(cur_sig) == self._trace_key(sig) and self._trace_key(cur_expr) == self._trace_key(expr):
                chk = table.cellWidget(row, 2)
                if isinstance(chk, QCheckBox):
                    chk.setChecked(bool(plot))
                table.selectRow(row)
                return row
        row = self.outputs_widget._add_entry(sig, expr)
        chk = table.cellWidget(row, 2)
        if isinstance(chk, QCheckBox):
            chk.setChecked(bool(plot))
        table.selectRow(row)
        return row

    def _add_measurement_entry(
        self,
        name: str,
        meas_type: str,
        expression: str,
        target: str = "",
        from_time: str = "",
        to_time: str = "",
    ) -> int:
        table = self.measurement_widget.table
        expr_key = self._trace_key(expression)
        type_key = self._trace_key(meas_type)
        for row in range(table.rowCount()):
            type_widget = table.cellWidget(row, 1)
            cur_type = type_widget.currentText().strip() if isinstance(type_widget, QComboBox) else ""
            cur_expr = self._table_text(table, row, 2)
            cur_from = self._table_text(table, row, 4)
            cur_to = self._table_text(table, row, 5)
            if (
                self._trace_key(cur_type) == type_key
                and self._trace_key(cur_expr) == expr_key
                and str(cur_from).strip() == str(from_time).strip()
                and str(cur_to).strip() == str(to_time).strip()
            ):
                table.selectRow(row)
                return row
        self.measurement_widget._add_row()
        row = table.rowCount() - 1
        self._set_table_text(table, row, 0, name or f"meas_{row}")
        type_widget = table.cellWidget(row, 1)
        if isinstance(type_widget, QComboBox):
            idx = type_widget.findText(meas_type)
            if idx >= 0:
                type_widget.setCurrentIndex(idx)
        self._set_table_text(table, row, 2, expression)
        self._set_table_text(table, row, 3, target)
        self._set_table_text(table, row, 4, from_time)
        self._set_table_text(table, row, 5, to_time)
        table.selectRow(row)
        return row

    def _on_sigview_output_request(self, payload: object):
        if not isinstance(payload, dict):
            return
        row = self._add_or_select_output_expression(
            str(payload.get("signal", "") or payload.get("expression", "")).strip(),
            str(payload.get("expression", "")).strip(),
            bool(payload.get("plot", True)),
        )
        if row >= 0:
            self._refresh_run_plan()
            self._save_simenv_view_silent()
            self._log(f"Added SimENV output from SigView: {payload.get('expression', '')}")

    def _on_sigview_measurement_request(self, payload: object):
        if not isinstance(payload, dict):
            return
        row = self._add_measurement_entry(
            str(payload.get("name", "")).strip(),
            str(payload.get("type", "AVG")).strip().upper() or "AVG",
            str(payload.get("expression", "")).strip(),
            str(payload.get("target", "")).strip(),
            str(payload.get("from", "")).strip(),
            str(payload.get("to", "")).strip(),
        )
        if row >= 0:
            self._refresh_run_plan()
            self._save_simenv_view_silent()
            self._log(f"Added SimENV measurement from SigView: {payload.get('type', 'AVG')} {payload.get('expression', '')}")

    def _add_measurement_from_expression(
        self,
        expression: str,
        name: str = "",
        meas_type: str = "AVG",
        target: str = "",
        from_time: str = "",
        to_time: str = "",
    ):
        row = self._add_measurement_entry(name, meas_type, expression, target, from_time, to_time)
        if row >= 0:
            self._refresh_run_plan()
            self._save_simenv_view_silent()
        return row

    def _add_spec_from_expression(self, expression: str, metric: str = "final") -> int:
        expr = str(expression or "").strip()
        if not expr or not hasattr(self, "spec_widget"):
            return -1
        table = self.spec_widget.table
        for row in range(table.rowCount()):
            if self._trace_key(self._table_text(table, row, 1)) == self._trace_key(expr):
                table.selectRow(row)
                return row
        self.spec_widget._add_row()
        row = table.rowCount() - 1
        self._set_table_text(table, row, 0, f"spec_{row}")
        self._set_table_text(table, row, 1, expr)
        metric_widget = table.cellWidget(row, 2)
        if isinstance(metric_widget, QComboBox):
            idx = metric_widget.findText(metric)
            if idx >= 0:
                metric_widget.setCurrentIndex(idx)
        table.selectRow(row)
        self._refresh_run_plan()
        self._save_simenv_view_silent()
        return row

    def _current_waveforms_for_sigview(self) -> dict:
        selected = self.results_table.currentRow() if hasattr(self, "results_table") else -1
        if selected in self._result_all_waveforms_by_row:
            return dict(self._result_all_waveforms_by_row[selected])
        if selected in self._result_waveforms_by_row:
            return dict(self._result_waveforms_by_row[selected])
        if self._last_sigview_waveforms:
            return dict(self._last_sigview_waveforms)
        return {}

    def _edit_expression(self, expression: str = "") -> str:
        waveforms = self._current_waveforms_for_sigview()
        signals = [
            str(name)
            for name in self._plottable_signal_names(waveforms)
        ] if waveforms else []
        if not signals:
            targets = self._collect_output_targets()
            signals.extend([f"V({net})" for net in targets.get("nets", [])])
            signals.extend([f"I({inst}.{pin})" for inst, pin in targets.get("terminals", [])])
        dlg = ExpressionEditorDialog(
            expression,
            signals,
            waveforms,
            self,
            measurement_hook=lambda expr: self._add_measurement_from_expression(expr, meas_type="AVG"),
            spec_hook=lambda expr: self._add_spec_from_expression(expr, "final"),
            history=self._expression_history,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return ""
        expr = dlg.expression()
        self._remember_expression(expr)
        return expr

    def _remember_expression(self, expression: str) -> None:
        expr = str(expression or "").strip()
        if not expr:
            return
        self._expression_history = [item for item in self._expression_history if item != expr]
        self._expression_history.insert(0, expr)
        del self._expression_history[25:]

    def _show_expression_in_sigview(self, expression: str, name_hint: str = "", show_calculator: bool = False):
        expr = str(expression or "").strip()
        waveforms = self._current_waveforms_for_sigview()
        if not expr or not waveforms:
            self.statusBar().showMessage("No waveform data available for SigView expression plotting", 5000)
            return
        direct = self._match_waveform_for_expression(expr, waveforms)
        payload = self._sigview_payload_for_waveforms(
            waveforms,
            explicit_signals=[direct] if direct else [],
            focus_expression=expr,
            show_calculator=show_calculator,
        )
        if not direct:
            payload["derived_expressions"] = [{
                "name": str(name_hint or expr).strip() or expr,
                "expression": expr,
                "visible": True,
            }]
        self._last_sigview_waveforms = dict(waveforms)
        self._last_sigview_payload = payload
        self._remember_expression(expr)
        self._show_waveforms(payload, calculator=show_calculator)

    def _on_outputs_context_menu(self, pos):
        table = self.outputs_widget.table
        row = table.rowAt(pos.y())
        menu = QMenu(self)
        if row < 0 and not table.selectedIndexes():
            act_clear = QAction("Clear All Outputs", self)
            act_clear.triggered.connect(self.outputs_widget.clear_outputs)
            menu.addAction(act_clear)
            menu.exec(table.viewport().mapToGlobal(pos))
            return
        if row >= 0:
            table.selectRow(row)
        active_row = row if row >= 0 else table.currentRow()
        sig = self._table_text(table, active_row, 0, "sig")
        expr = self._table_text(table, active_row, 1, "")
        title = QAction(sig or expr or "Output", self)
        title.setEnabled(False)
        menu.addAction(title)
        menu.addSeparator()
        if expr:
            act_plot = QAction("Plot In SigView", self)
            act_plot.triggered.connect(lambda: self._show_expression_in_sigview(expr, sig, show_calculator=False))
            menu.addAction(act_plot)
            act_calc = QAction("Send To Calculator", self)
            act_calc.triggered.connect(lambda: self._show_expression_in_sigview(expr, sig, show_calculator=True))
            menu.addAction(act_calc)
            act_meas = QAction("Add Measurement From Output", self)
            act_meas.triggered.connect(lambda: self._add_measurement_from_expression(expr, f"avg_{sig or active_row}", "AVG"))
            menu.addAction(act_meas)
            menu.addSeparator()
        act_delete = QAction("Delete Selected Output(s)", self)
        act_delete.setShortcut(QKeySequence("Delete"))
        act_delete.triggered.connect(self.outputs_widget._delete_selected_rows)
        menu.addAction(act_delete)
        act_clear = QAction("Clear All Outputs", self)
        act_clear.triggered.connect(self.outputs_widget.clear_outputs)
        menu.addAction(act_clear)
        menu.exec(table.viewport().mapToGlobal(pos))

    def _on_measurements_context_menu(self, pos):
        table = self.measurement_widget.table
        row = table.rowAt(pos.y())
        if row < 0:
            return
        table.selectRow(row)
        name = self._table_text(table, row, 0, f"meas_{row}")
        expr = self._table_text(table, row, 2, "")
        menu = QMenu(self)
        title = QAction(name or expr or "Measurement", self)
        title.setEnabled(False)
        menu.addAction(title)
        menu.addSeparator()
        act_plot = QAction("Plot In SigView", self)
        act_plot.triggered.connect(lambda: self._show_expression_in_sigview(expr, name, show_calculator=False))
        menu.addAction(act_plot)
        act_calc = QAction("Send To Calculator", self)
        act_calc.triggered.connect(lambda: self._show_expression_in_sigview(expr, name, show_calculator=True))
        menu.addAction(act_calc)
        menu.exec(table.viewport().mapToGlobal(pos))

    def _save_simenv_view_silent(self):
        if getattr(self, "_simenv_autosave_suspended", False):
            return
        try:
            data = self._collect_simenv_setup()
            self.db.save_view(self.library, self.cell, "simenv", data)
            self.session_badge.setText("Session: saved view")
            self.statusBar().showMessage(f"Saved {self.library}/{self.cell}/simenv", 3000)
        except Exception as exc:
            self._log(f"Could not autosave SimENV view: {exc}")

    def _infer_pdk_name(self) -> str:
        """Infer the PDK from library attachment, schematic instances, or active registry state."""
        registry = self._ensure_pdk_registry()
        if registry:
            try:
                pdk_name = self.db.get_library_pdk(self.library)
                if pdk_name and registry.get_pdk(pdk_name):
                    return pdk_name
            except Exception:
                pass

            try:
                data = self.db.load_view(self.library, self.cell, "schematic") or {}
                for inst in data.get("instances", []):
                    lib_name = inst.get("library", "")
                    if lib_name.startswith("pdk:"):
                        pdk_name = lib_name.split(":", 1)[1]
                        if registry.get_pdk(pdk_name):
                            return pdk_name
            except Exception:
                pass

            try:
                active_name = registry.get_active_name()
                if active_name:
                    return active_name
            except Exception:
                pass
        return ""

    def _selected_pdk_name(self, infer: bool = True) -> str:
        """Return the SimENV-selected PDK, falling back to schematic/active inference."""
        pdk_name = self.pdk_combo.currentData() if hasattr(self, "pdk_combo") else ""
        if pdk_name:
            return pdk_name
        return self._infer_pdk_name() if infer else ""

    def _used_pdk_devices(self, pdk_name: str) -> list:
        """Return PDK devices used by this schematic."""
        registry = self._ensure_pdk_registry()
        if not pdk_name or not registry:
            return []
        devices = []
        try:
            data = self.db.load_view(self.library, self.cell, "schematic") or {}
            for inst in data.get("instances", []):
                if inst.get("library") != f"pdk:{pdk_name}":
                    continue
                dev = registry.find_device(inst.get("cell", ""), pdk_name)
                if dev and dev not in devices:
                    devices.append(dev)
        except Exception:
            pass
        return devices

    def _configure_pdk_model_directives(self, directives: NetlistDirectives,
                                        pdk_name: str, process: str = "",
                                        corner_name: str = ""):
        """Add explicit model directives to the netlist."""
        resolved = self._resolved_model_directives(process, corner_name, pdk_name)
        includes, libs = directives_to_netlist_entries(resolved)
        directives.includes.extend(includes)
        directives.libs.extend(libs)

    def _resolved_model_directives(self, process: str = "", corner_name: str = "",
                                   pdk_name: str = "") -> list[ModelDirective]:
        if corner_name and corner_name in self._corner_model_directives:
            return list(self._corner_model_directives.get(corner_name, []))
        global_directives = self._collect_model_table_directives() if hasattr(self, "model_table") else list(self._global_model_directives)
        if global_directives:
            return global_directives
        if (pdk_name or self._selected_pdk_name()) == "ihp_sg13g2":
            return self._default_model_directives_for_process(process or "tt")
        return []

    def _section_matches_process(self, section: str, process: str) -> bool:
        sec = str(section or "").strip().lower()
        proc = str(process or "").strip().lower()
        return bool(sec and proc and (sec == proc or sec.endswith(f"_{proc}") or sec.endswith(f"-{proc}")))

    def _mapped_model_directives_for_corner(self, corner: dict) -> list[ModelDirective]:
        process = str(corner.get("process", "") if isinstance(corner, dict) else "").strip()
        mapped: list[ModelDirective] = []
        for directive in self._collect_model_table_directives():
            if directive.kind.lower() != "lib":
                mapped.append(directive)
                continue
            sections = extract_lib_sections(directive.path)
            match = next((section for section in sections if self._section_matches_process(section, process)), "")
            if match:
                mapped.append(ModelDirective(directive.kind, directive.path, match))
            elif directive.section:
                mapped.append(directive)
        return mapped

    def _map_model_sections_to_corners(self):
        corners = self.get_corner_data() if hasattr(self, "corner_table") else []
        if not corners:
            self.statusBar().showMessage("No enabled corners to map", 4000)
            return
        count = 0
        for corner in corners:
            name = str(corner.get("name", "")).strip()
            directives = self._mapped_model_directives_for_corner(corner)
            if name and directives:
                self._corner_model_directives[name] = directives
                count += 1
        self._refresh_corner_model_buttons()
        self._sync_corner_inspector()
        self._refresh_run_plan()
        self._save_simenv_view_silent()
        self.statusBar().showMessage(f"Mapped model sections for {count} corner(s)", 4000)

    def _default_model_directives_for_process(self, process: str) -> list[ModelDirective]:
        """Create IHP SG13G2 GSPICE wrapper directives for old/minimal setups."""
        registry = self._ensure_pdk_registry()
        pdk = registry.get_pdk("ihp_sg13g2") if registry else None
        if not pdk:
            return []
        model_files = list(getattr(pdk, "model_files", []) or [])
        if not model_files:
            return []
        used_devices = self._used_pdk_devices("ihp_sg13g2")
        wanted = self._ihp_model_file_names(used_devices)
        sim_folder = "ngspice"
        preferred = sorted(
            model_files,
            key=lambda mf: (
                0 if f"{os.sep}{sim_folder}{os.sep}" in mf.path.lower() else 1,
                mf.path.lower(),
            ),
        )
        directives: list[ModelDirective] = []
        used_wrappers = set()
        for mf in preferred:
            filename = os.path.basename(mf.path)
            if filename in used_wrappers or filename not in wanted:
                continue
            directives.append(ModelDirective("lib", mf.path, self._ihp_section_for_file(filename, process or "tt")))
            used_wrappers.add(filename)
        return directives

    def _ihp_model_file_names(self, devices: list) -> set[str]:
        """Choose IHP corner wrapper files needed by the placed devices."""
        if not devices:
            return {
                "cornerMOSlv.lib", "cornerMOShv.lib", "cornerRES.lib",
                "cornerCAP.lib", "cornerDIO.lib", "cornerHBT.lib",
            }

        wanted = set()
        for dev in devices:
            name = getattr(dev, "name", "").lower()
            category = str(getattr(getattr(dev, "category", ""), "value", getattr(dev, "category", ""))).lower()
            if name.startswith("sg13_lv_"):
                wanted.add("cornerMOSlv.lib")
            elif name.startswith("sg13_hv_"):
                wanted.add("cornerMOShv.lib")
            elif "res" in category or name.startswith(("r", "rsil", "rppd")):
                wanted.add("cornerRES.lib")
            elif "cap" in category or "cap" in name or name == "cmim":
                wanted.add("cornerCAP.lib")
            elif "diode" in category or "dio" in name:
                wanted.add("cornerDIO.lib")
            elif "bjt" in category or name.startswith(("npn", "pnp")):
                wanted.add("cornerHBT.lib")
        return wanted or {"cornerMOSlv.lib"}

    def _ihp_section_for_file(self, filename: str, process: str) -> str:
        """Map SimENV corner names to IHP .LIB sections."""
        proc = (process or "tt").lower()
        if proc in ("typ", "typical"):
            proc = "tt"

        if filename in ("cornerMOSlv.lib", "cornerMOShv.lib"):
            return f"mos_{proc if proc in ('tt', 'ss', 'ff', 'sf', 'fs') else 'tt'}"
        if filename == "cornerDIO.lib":
            return f"dio_{proc if proc in ('tt', 'ss', 'ff') else 'tt'}"
        if filename == "cornerRES.lib":
            return "res_typ" if proc in ("tt", "typ") else "res_bcs"
        if filename == "cornerCAP.lib":
            return "cap_typ" if proc in ("tt", "typ") else "cap_bcs"
        if filename == "cornerHBT.lib":
            return "hbt_typ" if proc in ("tt", "typ") else "hbt_bcs"
        return proc

    def _match_lib_section(self, sections: list[str], process: str) -> str:
        """Find the closest .LIB section for a requested process corner."""
        if not sections:
            return ""
        proc = (process or "").lower()
        if not proc:
            return sections[0]
        for section in sections:
            if section.lower() == proc:
                return section
        for section in sections:
            if proc in section.lower():
                return section
        return sections[0]

    def _apply_ade_workbench_style(self):
        """Apply a dense Simulation Cockpit local skin for this window."""
        self.setStyleSheet(
            """
            QMainWindow {
                background: #202020;
                color: #d6d6d6;
                font-family: "Segoe UI", Arial, sans-serif;
                font-size: 10pt;
            }
            QFrame#simenvHeader {
                background: #2a2a2a;
                border: 1px solid #4a4a4a;
                border-radius: 2px;
            }
            QLabel#adeTitle {
                color: #f0f0f0;
                font-size: 18px;
                font-weight: 700;
                background: transparent;
            }
            QLabel#adeSubtitle {
                color: #b9c2c7;
                background: transparent;
                font-family: Consolas, "Segoe UI", monospace;
            }
            QLabel#adeSessionBadge {
                color: #111111;
                background: #d8b45f;
                border: 1px solid #f0cf75;
                border-radius: 2px;
                padding: 5px 10px;
                font-weight: 700;
            }
            QFrame#adeReadinessBanner {
                background: #18241d;
                border: 1px solid #315a3f;
                border-radius: 2px;
            }
            QLabel#adeReadinessTitle {
                color: #d8f3dc;
                background: transparent;
                font-weight: 700;
            }
            QLabel#adeReadinessDetail {
                color: #b7c7bc;
                background: transparent;
            }
            QPushButton#adeWorkflowChip {
                background: #303030;
                color: #d6d6d6;
                border: 1px solid #4a4a4a;
                border-radius: 2px;
                padding: 3px 8px;
                font-weight: 600;
            }
            QPushButton#adeWorkflowChip[ready="true"] {
                color: #b7f0c0;
                border-color: #3d7350;
            }
            QPushButton#adeWorkflowChip[ready="false"] {
                color: #ffd166;
                border-color: #6c5825;
            }
            QSplitter::handle {
                background: #3a3a3a;
            }
            QTabWidget#adeMainTabs::pane,
            QTabWidget#adeSubTabs::pane,
            QTabWidget#adeTestTabs::pane {
                border: 1px solid #4a4a4a;
                background: #242424;
            }
            QTabBar::tab {
                background: #333333;
                color: #c8c8c8;
                border: 1px solid #4a4a4a;
                border-bottom: none;
                border-radius: 0;
                padding: 5px 14px;
                min-height: 20px;
            }
            QTabBar::tab:selected {
                background: #242424;
                color: #ffffff;
                border-top: 2px solid #d8b45f;
            }
            QFrame#adeNavigator {
                background: #2b2b2b;
                border: 1px solid #464646;
                border-radius: 2px;
            }
            QLabel#adePanelLabel,
            QLabel#adePanelTitle {
                color: #d8b45f;
                background: transparent;
                font-weight: 700;
                padding: 3px 0;
            }
            QGroupBox {
                border: 1px solid #494949;
                border-radius: 2px;
                margin-top: 8px;
                padding-top: 14px;
                background: #282828;
            }
            QGroupBox::title {
                color: #d8b45f;
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 3px;
                font-weight: 700;
            }
            QTreeWidget#adeAnalysisTree,
            QTreeWidget,
            QTableWidget,
            QTextEdit {
                background: #1f1f1f;
                color: #dcdcdc;
                border: 1px solid #454545;
                border-radius: 2px;
                gridline-color: #383838;
                selection-background-color: #4b3f24;
                selection-color: #ffffff;
            }
            QTextEdit#adeConsole {
                background: #151515;
                color: #b9c2c7;
                font-family: Consolas, "Cascadia Mono", monospace;
            }
            QHeaderView::section {
                background: #303030;
                color: #d6d6d6;
                border: 1px solid #454545;
                padding: 4px 6px;
                font-weight: 700;
            }
            QLineEdit,
            QComboBox,
            QSpinBox,
            QDoubleSpinBox {
                background: #181818;
                color: #eeeeee;
                border: 1px solid #565656;
                border-radius: 2px;
                padding: 4px 6px;
                min-height: 20px;
            }
            QLineEdit:focus,
            QComboBox:focus,
            QSpinBox:focus {
                border: 1px solid #d8b45f;
            }
            QPushButton {
                background: #363636;
                color: #f0f0f0;
                border: 1px solid #595959;
                border-radius: 2px;
                padding: 5px 10px;
            }
            QPushButton:hover {
                background: #444444;
                border-color: #d8b45f;
            }
            QPushButton#adePrimaryButton {
                background: #5b4521;
                border-color: #d8b45f;
                font-weight: 700;
            }
            QToolBar {
                background: #2b2b2b;
                border-bottom: 1px solid #454545;
                spacing: 3px;
                padding: 3px;
            }
            QStatusBar {
                background: #2b2b2b;
                color: #d6d6d6;
                border-top: 1px solid #454545;
            }
            """
        )

    def _build_ui(self):
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setObjectName("adeRootSplitter")
        self.setCentralWidget(splitter)

        splitter.addWidget(self._build_session_header())

        # Session tabs
        self.main_tabs = QTabWidget()
        self.main_tabs.setObjectName("adeMainTabs")
        self.main_tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.main_tabs.currentChanged.connect(self._on_main_tab_changed)
        splitter.addWidget(self.main_tabs)

        self._build_data_view_tab()
        self._build_analyses_tab()
        self._build_model_libraries_tab()
        self._build_corners_tab()
        self._build_run_plan_tab()
        self._build_results_tab()
        self._refresh_workflow_status()

        # Bottom: log
        self.log_view = QTextEdit()
        self.log_view.setObjectName("adeConsole")
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Consolas", 9))
        self.log_view.setMaximumHeight(180)
        splitter.addWidget(self.log_view)
        splitter.setSizes([150, 560, 160])

    def _on_main_tab_changed(self, _idx: int = 0):
        self._refresh_run_plan()
        self._refresh_workflow_status()

    def _build_session_header(self):
        header = QFrame()
        header.setObjectName("simenvHeader")
        header.setMaximumHeight(162)
        layout = QVBoxLayout(header)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel("Simulation Cockpit")
        title.setObjectName("adeTitle")
        subtitle = QLabel(f"{self.library}/{self.cell}/simenv")
        subtitle.setObjectName("adeSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        top_row.addLayout(title_box, stretch=1)

        dump_btn = QPushButton("📂 Dump Settings")
        dump_btn.setToolTip("Choose where SimENV writes input.sp, logs, RAW waveform files, and run manifests")
        dump_btn.clicked.connect(self._on_set_sim_dump_dir)
        dump_btn.setFixedWidth(126)
        top_row.addWidget(dump_btn)

        self.session_badge = QLabel("Session: interactive")
        self.session_badge.setObjectName("adeSessionBadge")
        self.session_badge.setMinimumWidth(128)
        self.session_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_row.addWidget(self.session_badge)
        self.pdk_badge = QLabel("PDK: none")
        self.pdk_badge.setObjectName("adeSessionBadge")
        self.pdk_badge.setMinimumWidth(160)
        self.pdk_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_row.addWidget(self.pdk_badge)
        layout.addLayout(top_row)

        readiness = QFrame()
        readiness.setObjectName("adeReadinessBanner")
        ready_row = QHBoxLayout(readiness)
        ready_row.setContentsMargins(8, 4, 8, 4)
        ready_row.setSpacing(8)
        self.readiness_title = QLabel("Checking setup")
        self.readiness_title.setObjectName("adeReadinessTitle")
        ready_row.addWidget(self.readiness_title)
        self.readiness_detail = QLabel("")
        self.readiness_detail.setObjectName("adeReadinessDetail")
        self.readiness_detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        ready_row.addWidget(self.readiness_detail, 1)
        self.readiness_fix_btn = QPushButton("Fix")
        self.readiness_fix_btn.setFixedWidth(72)
        self.readiness_fix_btn.clicked.connect(self._fix_next_setup_gap)
        ready_row.addWidget(self.readiness_fix_btn)
        layout.addWidget(readiness)

        workflow_row = QHBoxLayout()
        workflow_row.setSpacing(6)
        self.workflow_buttons = {}
        for key, label, tab in (
            ("pdk", "1 PDK", "Model Setup"),
            ("models", "2 Models", "Model Setup"),
            ("corners", "3 Corners", "Corners"),
            ("analyses", "4 Analyses", "Analyses"),
            ("outputs", "5 Outputs", "Setup"),
            ("run", "6 Run", "Run Plan"),
        ):
            btn = QPushButton(label)
            btn.setObjectName("adeWorkflowChip")
            btn.setProperty("ready", "false")
            btn.clicked.connect(lambda _checked=False, name=tab: self._show_main_tab(name))
            workflow_row.addWidget(btn)
            self.workflow_buttons[key] = btn
        workflow_row.addStretch(1)
        layout.addLayout(workflow_row)

        controls_row = QHBoxLayout()
        controls_row.setSpacing(12)

        thread_box = QHBoxLayout()
        thread_box.setSpacing(6)
        thread_label = QLabel("Threads")
        thread_box.addWidget(thread_label)
        self.thread_spin = QSpinBox()
        self.thread_spin.setRange(1, 16)
        self.thread_spin.setValue(self._sim_threads)
        self.thread_spin.setToolTip("Simulator worker threads. Backends that do not expose a thread option ignore this setting.")
        self.thread_spin.valueChanged.connect(self._on_threads_changed)
        thread_box.addWidget(self.thread_spin)
        controls_row.addLayout(thread_box)

        timeout_box = QHBoxLayout()
        timeout_box.setSpacing(6)
        timeout_label = QLabel("Timeout")
        timeout_box.addWidget(timeout_label)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(0, 86400)
        self.timeout_spin.setSingleStep(60)
        self.timeout_spin.setSpecialValueText("Auto")
        self.timeout_spin.setValue(self._sim_timeout)
        self.timeout_spin.setToolTip(
            "Maximum runtime per simulation in seconds. Auto uses the GSPICE production default."
        )
        self.timeout_spin.valueChanged.connect(self._on_timeout_changed)
        timeout_box.addWidget(self.timeout_spin)
        controls_row.addLayout(timeout_box)

        accuracy_box = QHBoxLayout()
        accuracy_box.setSpacing(6)
        accuracy_label = QLabel("Accuracy")
        accuracy_box.addWidget(accuracy_label)
        self.accuracy_combo = QComboBox()
        self.accuracy_combo.addItems(["Low", "Medium", "High", "Very High"])
        self.accuracy_combo.setCurrentText(self._sim_accuracy)
        self.accuracy_combo.setToolTip("Simulation accuracy preset. Higher settings reduce transient timestep error and tighten solver tolerances.")
        self.accuracy_combo.currentTextChanged.connect(self._on_accuracy_changed)
        accuracy_box.addWidget(self.accuracy_combo)
        controls_row.addLayout(accuracy_box)

        tolerance_box = QHBoxLayout()
        tolerance_box.setSpacing(6)
        tolerance_label = QLabel("Tol")
        tolerance_box.addWidget(tolerance_label)
        self.tolerance_override_edit = QLineEdit(self._sim_tolerance_override)
        self.tolerance_override_edit.setPlaceholderText("Preset")
        self.tolerance_override_edit.setToolTip(
            "Optional RELTOL/LTE_RELTOL override for tighter-than-preset runs, for example 1e-5. "
            "Blank uses the selected accuracy preset; TRTOL remains 1."
        )
        self.tolerance_override_edit.editingFinished.connect(
            lambda: self._on_tolerance_override_changed(self.tolerance_override_edit.text())
        )
        tolerance_box.addWidget(self.tolerance_override_edit)
        controls_row.addLayout(tolerance_box)

        method_box = QHBoxLayout()
        method_box.setSpacing(6)
        method_label = QLabel("Method")
        method_box.addWidget(method_label)
        self.method_combo = QComboBox()
        self.method_combo.addItems(["Auto", "Backward Euler", "Trapezoidal", "Gear2"])
        self.method_combo.setCurrentText(self._sim_method)
        self.method_combo.setToolTip("Transient integration method. Native GSPICE records the selected method; external backends receive compatible tolerance options.")
        self.method_combo.currentTextChanged.connect(self._on_method_changed)
        method_box.addWidget(self.method_combo)
        controls_row.addLayout(method_box)

        save_box = QHBoxLayout()
        save_box.setSpacing(6)
        save_label = QLabel("Save")
        save_box.addWidget(save_label)
        self.save_mode_combo = QComboBox()
        self.save_mode_combo.addItems(["All", "Selected", "None"])
        self.save_mode_combo.setCurrentText(self._sim_save_mode_label())
        self.save_mode_combo.setToolTip("GSPICE waveform save policy. All matches industry-style save-all; Selected writes only output expressions; None writes time only.")
        self.save_mode_combo.currentTextChanged.connect(self._on_save_mode_changed)
        save_box.addWidget(self.save_mode_combo)
        controls_row.addLayout(save_box)

        self.adaptive_maxstep_check = QCheckBox("Auto maxstep")
        self.adaptive_maxstep_check.setChecked(self._sim_adaptive_maxstep)
        self.adaptive_maxstep_check.setToolTip(
            "Leave transient MaxStep blank so GSPICE can adapt internal steps from LTE. "
            "A typed MaxStep remains a hard internal timestep cap."
        )
        self.adaptive_maxstep_check.stateChanged.connect(
            lambda state: self._on_adaptive_maxstep_changed(state == Qt.CheckState.Checked.value)
        )
        controls_row.addWidget(self.adaptive_maxstep_check)

        self.save_adaptive_points_check = QCheckBox("Save internal points")
        self.save_adaptive_points_check.setChecked(self._sim_save_adaptive_points)
        self.save_adaptive_points_check.setToolTip(
            "Write accepted transient solver timesteps to RAW in addition to the .TRAN print grid. "
            "This gives smoother fast-edge waveforms and can increase RAW file size."
        )
        self.save_adaptive_points_check.stateChanged.connect(
            lambda state: self._on_save_adaptive_points_changed(state == Qt.CheckState.Checked.value)
        )
        controls_row.addWidget(self.save_adaptive_points_check)

        runtime = SimulatorRuntimeManager(str(getattr(self.db, "workspace", "")))
        self._sim_prefer_klu = runtime.gspice_prefer_klu()
        self.klu_check = QCheckBox("KLU")
        self.klu_check.setChecked(self._sim_prefer_klu)
        self.klu_check.setToolTip("Use a SuiteSparse-KLU GSPICE runtime and request SOLVER=KLU for sparse matrix solves.")
        self.klu_check.stateChanged.connect(
            lambda state: self._on_klu_changed(state == Qt.CheckState.Checked.value)
        )
        controls_row.addWidget(self.klu_check)
        self.compat_diag_check = QCheckBox("Compat diagnostics")
        self.compat_diag_check.setChecked(self._sim_verbose_compat)
        self.compat_diag_check.setToolTip("Show native GSPICE PSP/IHP compatibility diagnostics. Leave off for quiet normal runs.")
        self.compat_diag_check.stateChanged.connect(
            lambda state: self._on_verbose_compat_changed(state == Qt.CheckState.Checked.value)
        )
        controls_row.addWidget(self.compat_diag_check)
        layout.addLayout(controls_row)
        return header

    def _setup_readiness(self) -> dict[str, tuple[bool, str]]:
        pdk_name = self._selected_pdk_name() if hasattr(self, "pdk_combo") else ""
        model_rows = self.model_table.rowCount() if hasattr(self, "model_table") else 0
        corner_rows = self.corner_table.rowCount() if hasattr(self, "corner_table") else 0
        analyses = len(getattr(self, "_analysis_tabs", {}) or {})
        output_rows = self.outputs_widget.table.rowCount() if hasattr(self, "outputs_widget") else 0
        save_all = bool(
            hasattr(self, "outputs_widget")
            and (
                self.outputs_widget.chk_save_all_nodes.isChecked()
                or self.outputs_widget.chk_save_all_currents.isChecked()
            )
        )
        return {
            "pdk": (bool(pdk_name), pdk_name or "none"),
            "models": (model_rows > 0, f"{model_rows} file row(s)"),
            "corners": (corner_rows > 0, f"{corner_rows} corner(s)"),
            "analyses": (analyses > 0, f"{analyses} enabled"),
            "outputs": (output_rows > 0 or save_all, f"{output_rows} row(s)" if output_rows else ("save all" if save_all else "none")),
            "run": (bool(pdk_name) and model_rows > 0 and corner_rows > 0 and analyses > 0, "ready" if analyses else "needs analysis"),
        }

    def _refresh_workflow_status(self):
        if not hasattr(self, "readiness_title"):
            return
        status = self._setup_readiness()
        blocking = [
            name for name in ("pdk", "models", "corners", "analyses")
            if not status.get(name, (False, ""))[0]
        ]
        warnings = [
            name for name in ("outputs",)
            if not status.get(name, (False, ""))[0]
        ]
        if blocking:
            self.readiness_title.setText("Needs Setup")
            self.readiness_fix_btn.setEnabled(True)
        elif warnings:
            self.readiness_title.setText("Runnable")
            self.readiness_fix_btn.setEnabled(True)
        else:
            self.readiness_title.setText("Ready to Run")
            self.readiness_fix_btn.setEnabled(False)

        self.readiness_detail.setText(" | ".join(
            f"{name.title()}: {status[name][1]}"
            for name in ("pdk", "models", "corners", "analyses", "outputs")
        ))

        labels = {
            "pdk": "1 PDK",
            "models": "2 Models",
            "corners": "3 Corners",
            "analyses": "4 Analyses",
            "outputs": "5 Outputs",
            "run": "6 Run",
        }
        for key, btn in getattr(self, "workflow_buttons", {}).items():
            ready, text = status.get(key, (False, ""))
            btn.setText(f"{labels.get(key, key)} {'✓' if ready else '!'}")
            btn.setProperty("ready", "true" if ready else "false")
            btn.setToolTip(text)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _fix_next_setup_gap(self):
        status = self._setup_readiness()
        if not status["pdk"][0]:
            self._show_main_tab("Model Setup")
            self._log("Select or attach a PDK before running.")
            return
        if not status["models"][0]:
            if self._apply_selected_pdk_manifest():
                self._refresh_workflow_status()
                return
            self._show_main_tab("Model Setup")
            return
        if not status["corners"][0]:
            self._add_corner_row()
            self._show_main_tab("Corners")
            self._refresh_workflow_status()
            return
        if not status["analyses"][0]:
            self._add_analysis("Transient")
            self._refresh_workflow_status()
            return
        if not status["outputs"][0] and hasattr(self, "outputs_widget"):
            row = self.outputs_widget._add_entry("out", "V(out)")
            self.outputs_widget.table.selectRow(row)
            self._show_main_tab("Setup")
            self._refresh_workflow_status()

    def _build_data_view_tab(self):
        data_tabs = QTabWidget()
        data_tabs.setObjectName("adeSubTabs")
        data_tabs.setDocumentMode(True)

        self.var_widget = DesignVariablesWidget()
        data_tabs.addTab(self.var_widget, "Variables")

        self.outputs_widget = OutputsWidget(
            target_provider=self._collect_output_targets,
            visualize_hook=self._visualize_output_targets,
            voltage_pick_hook=self._start_voltage_pick,
            current_pick_hook=self._start_current_pick,
            expression_edit_hook=self._edit_expression,
        )
        self.outputs_widget.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.outputs_widget.table.customContextMenuRequested.connect(self._on_outputs_context_menu)
        data_tabs.addTab(self.outputs_widget, "Outputs")

        self.measurement_widget = MeasurementSetupWidget(expression_edit_hook=self._edit_expression)
        self.measurement_widget.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.measurement_widget.table.customContextMenuRequested.connect(self._on_measurements_context_menu)
        data_tabs.addTab(self.measurement_widget, "Measurements")

        self.spec_widget = SpecSetupWidget(expression_edit_hook=self._edit_expression)
        data_tabs.addTab(self.spec_widget, "Specs")

        self.stimulus_widget = StimulusEditorWidget()
        data_tabs.addTab(self.stimulus_widget, "Stimuli")

        self.convergence_widget = ConvergenceHelpersWidget()
        data_tabs.addTab(self.convergence_widget, "Convergence")

        self.sweep_widget = ParametricSweepWidget()
        self.sweep_widget.sweep_table.itemChanged.connect(lambda _item: self._refresh_corner_run_matrix_preview())
        data_tabs.addTab(self.sweep_widget, "Sweeps")

        self.main_tabs.addTab(data_tabs, "Setup")

    def _build_analyses_tab(self):
        analyses_widget = QWidget()
        layout = QHBoxLayout(analyses_widget)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        # Left: simulator selector + analysis tree
        left_panel = QFrame()
        left_panel.setObjectName("adeNavigator")
        left_panel.setMinimumWidth(260)
        left_panel.setMaximumWidth(340)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(8)

        # Simulator selector
        sim_group = QGroupBox("Simulator")
        sim_group.setObjectName("adeControlGroup")
        sim_form = QVBoxLayout(sim_group)
        self.sim_combo = QComboBox()
        for sim in ACTIVE_SIMULATORS:
            self.sim_combo.addItem(get_simulator_label(sim), sim)
        idx = self.sim_combo.findData(self._current_simulator)
        if idx < 0:
            idx = self.sim_combo.findData("GSPICE")
        if idx >= 0:
            self.sim_combo.setCurrentIndex(idx)
            self._current_simulator = self.sim_combo.currentData() or self._current_simulator
        self.sim_combo.setEnabled(True)
        self.sim_combo.currentIndexChanged.connect(self._on_simulator_changed)
        sim_form.addWidget(self.sim_combo)

        # Availability indicator
        self.sim_status_label = QLabel()
        self.sim_status_label.setStyleSheet("background:transparent;padding:2px;")
        sim_form.addWidget(self.sim_status_label)
        left_layout.addWidget(sim_group)

        # Machine selector (Local or Remote SSH)
        machine_group = QGroupBox("Machine")
        machine_group.setObjectName("adeControlGroup")
        machine_layout = QVBoxLayout(machine_group)

        mach_row = QHBoxLayout()
        mach_row.addWidget(QLabel("Target:"))
        self.machine_combo = QComboBox()
        self.machine_combo.addItem("Local", "local")
        self.machine_combo.addItem("Remote (SSH)", "remote")
        self.machine_combo.currentIndexChanged.connect(self._on_machine_changed)
        mach_row.addWidget(self.machine_combo)
        machine_layout.addLayout(mach_row)

        self.remote_ssh_widget = QWidget()
        remote_form = QFormLayout(self.remote_ssh_widget)
        remote_form.setContentsMargins(0, 4, 0, 0)

        self.ssh_host_edit = QLineEdit()
        self.ssh_host_edit.setPlaceholderText("e.g. 192.168.1.100")
        self.ssh_host_edit.textChanged.connect(lambda _t: self._on_machine_changed())
        remote_form.addRow("Host / IP:", self.ssh_host_edit)

        self.ssh_user_edit = QLineEdit()
        self.ssh_user_edit.setPlaceholderText("e.g. username")
        self.ssh_user_edit.textChanged.connect(lambda _t: self._on_machine_changed())
        remote_form.addRow("SSH User:", self.ssh_user_edit)

        ssh_key_box = QHBoxLayout()
        self.ssh_key_edit = QLineEdit()
        self.ssh_key_edit.setPlaceholderText("Optional key path")
        self.ssh_key_edit.textChanged.connect(lambda _t: self._on_machine_changed())
        ssh_key_box.addWidget(self.ssh_key_edit)
        browse_key_btn = QPushButton("...")
        browse_key_btn.setFixedWidth(26)
        browse_key_btn.clicked.connect(self._on_browse_ssh_key)
        ssh_key_box.addWidget(browse_key_btn)
        remote_form.addRow("SSH Key:", ssh_key_box)

        self.remote_gspice_edit = QLineEdit()
        self.remote_gspice_edit.setPlaceholderText("gspice")
        self.remote_gspice_edit.setText("gspice")
        self.remote_gspice_edit.textChanged.connect(lambda _t: self._on_machine_changed())
        remote_form.addRow("Remote GSPICE:", self.remote_gspice_edit)

        self.remote_ssh_widget.setVisible(False)
        machine_layout.addWidget(self.remote_ssh_widget)
        left_layout.addWidget(machine_group)

        lbl = QLabel("Available Analyses")
        lbl.setObjectName("adePanelLabel")
        left_layout.addWidget(lbl)

        self.analysis_tree = QTreeWidget()
        self.analysis_tree.setObjectName("adeAnalysisTree")
        self.analysis_tree.setHeaderHidden(True)
        self.analysis_tree.setMinimumWidth(220)
        self.analysis_tree.itemDoubleClicked.connect(self._on_analysis_dblclick)
        left_layout.addWidget(self.analysis_tree)

        add_btn = QPushButton("Add Analysis \u2192")
        add_btn.setObjectName("adePrimaryButton")
        add_btn.clicked.connect(self._add_selected_analysis)
        left_layout.addWidget(add_btn)
        layout.addWidget(left_panel)

        # Right: setup tabs for added analyses
        self.analysis_setup_tabs = QTabWidget()
        self.analysis_setup_tabs.setObjectName("adeTestTabs")
        self.analysis_setup_tabs.setTabsClosable(True)
        self.analysis_setup_tabs.tabCloseRequested.connect(self._on_close_analysis_tab)
        layout.addWidget(self.analysis_setup_tabs, stretch=1)

        self.main_tabs.addTab(analyses_widget, "Analyses")

        # Populate initial state
        self._refresh_analysis_tree()
        QTimer.singleShot(0, self._schedule_simulator_status_refresh)

    def _on_simulator_changed(self, index):
        """Handle simulator selection change."""
        selected = self.sim_combo.currentData()
        if not selected:
            return
        self._current_simulator = selected
        try:
            runtime = SimulatorRuntimeManager(str(getattr(self.db, "workspace", "")))
            runtime.set_active_simulator(self._current_simulator)
            runtime.apply_environment_overrides()
        except Exception as exc:
            self._log(f"Could not persist simulator selection: {exc}")
        self._refresh_analysis_tree()
        # Clear existing analysis tabs (they may not be supported)
        incompatible = []
        supported = get_supported_analyses(self._current_simulator)
        for name in list(self._analysis_tabs.keys()):
            if name not in supported:
                incompatible.append(name)
        if incompatible:
            for name in incompatible:
                for i in range(self.analysis_setup_tabs.count()):
                    if self.analysis_setup_tabs.tabText(i) == name:
                        self.analysis_setup_tabs.removeTab(i)
                        break
                del self._analysis_tabs[name]
            self._log(f"Removed unsupported analyses: {', '.join(incompatible)}")
        self._log(f"Simulator changed to: {get_simulator_label(self._current_simulator)}")
        # Update toolbar label
        if hasattr(self, 'toolbar_sim_label'):
            self.toolbar_sim_label.setText(self._current_simulator)
        self._schedule_simulator_status_refresh()
        self._refresh_run_plan()
        self._save_simenv_view_silent()

    def _build_bridge(self) -> SimulatorBridge:
        runtime = SimulatorRuntimeManager(str(getattr(self.db, "workspace", "")))
        exe = runtime.get_active_executable(self._current_simulator)
        work_dir = self._resolved_sim_dump_dir() if hasattr(self, "_resolved_sim_dump_dir") else ""
        machine_type = self.machine_combo.currentData() if hasattr(self, "machine_combo") else "local"
        host = self.ssh_host_edit.text().strip() if hasattr(self, "ssh_host_edit") else ""
        user = self.ssh_user_edit.text().strip() if hasattr(self, "ssh_user_edit") else ""
        key = self.ssh_key_edit.text().strip() if hasattr(self, "ssh_key_edit") else ""
        remote_exe = self.remote_gspice_edit.text().strip() if hasattr(self, "remote_gspice_edit") else "gspice"

        return SimulatorBridge(
            self._current_simulator,
            exe_path=exe,
            work_dir=work_dir,
            sim_env=machine_type,
            ssh_host=host,
            ssh_user=user,
            ssh_key=key,
            remote_gspice=remote_exe,
            save_mode=self._sim_save_mode,
            adaptive_maxstep=self._sim_adaptive_maxstep,
        )

    def _sync_machine_visibility(self):
        is_remote = hasattr(self, "machine_combo") and (self.machine_combo.currentData() == "remote")
        if hasattr(self, "remote_ssh_widget"):
            self.remote_ssh_widget.setVisible(is_remote)
        return is_remote

    def _schedule_simulator_status_refresh(self):
        if not hasattr(self, "sim_status_label"):
            return
        self.sim_status_label.setText("Checking runtime...")
        self.sim_status_label.setStyleSheet("color:#c9b26a;background:transparent;padding:2px;")
        if self._sim_status_refresh_scheduled:
            return
        self._sim_status_refresh_scheduled = True
        QTimer.singleShot(0, self._refresh_simulator_status)

    def _refresh_simulator_status(self):
        self._sim_status_refresh_scheduled = False
        if not hasattr(self, "sim_status_label"):
            return
        is_remote = self._sync_machine_visibility()
        bridge = self._build_bridge()
        if bridge.is_available():
            if is_remote:
                user = self.ssh_user_edit.text().strip() if hasattr(self, "ssh_user_edit") else ""
                host = self.ssh_host_edit.text().strip() if hasattr(self, "ssh_host_edit") else ""
                target = f"Remote ({user}@{host})" if user and host else "Remote SSH"
                self.sim_status_label.setText(target)
            else:
                runtime = SimulatorRuntimeManager(str(getattr(self.db, "workspace", "")))
                self.sim_status_label.setText("Found + KLU" if runtime.active_gspice_has_klu() else "Found")
            self.sim_status_label.setStyleSheet("color:#8bc78b;background:transparent;padding:2px;")
        else:
            self.sim_status_label.setText(f"Not found: {bridge.exe_path}")
            self.sim_status_label.setStyleSheet("color:#cc8888;background:transparent;padding:2px;")
            if self._current_simulator not in self._missing_sim_prompted:
                self._missing_sim_prompted.add(self._current_simulator)
                ready = ensure_simulator_available(
                    self,
                    str(getattr(self.db, "workspace", "")),
                    self._current_simulator,
                    logger=self._log,
                )
                if ready:
                    bridge = self._build_bridge()
                    if bridge.is_available():
                        self.sim_status_label.setText("Found")
                        self.sim_status_label.setStyleSheet(
                            "color:#8bc78b;background:transparent;padding:2px;"
                        )
        self._refresh_run_plan()

    def _on_machine_changed(self, _index=0):
        self._sync_machine_visibility()
        self._schedule_simulator_status_refresh()
        self._refresh_run_plan()
        self._save_simenv_view_silent()

    def _on_verbose_compat_changed(self, checked: bool):
        self._sim_verbose_compat = bool(checked)
        self._log(f"GSPICE compatibility diagnostics {'enabled' if self._sim_verbose_compat else 'disabled'}")
        self._refresh_run_plan()
        self._save_simenv_view_silent()

    def _on_browse_ssh_key(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select SSH Private Key",
            "",
            "All Files (*)",
        )
        if path:
            self.ssh_key_edit.setText(path)
            self._on_machine_changed()

    def _refresh_analysis_tree(self):
        """Rebuild the analysis tree showing only supported analyses."""
        self.analysis_tree.clear()
        supported = get_supported_analyses(self._current_simulator)
        categories = {}
        for name, info in ANALYSES.items():
            if name not in supported:
                continue
            cat = info["category"]
            if cat not in categories:
                cat_item = QTreeWidgetItem([cat])
                cat_item.setForeground(0, QColor("#6b9ece"))
                font = cat_item.font(0)
                font.setBold(True)
                cat_item.setFont(0, font)
                self.analysis_tree.addTopLevelItem(cat_item)
                categories[cat] = cat_item
                cat_item.setExpanded(True)
            item = QTreeWidgetItem([name])
            item.setData(0, Qt.ItemDataRole.UserRole, name)
            categories[cat].addChild(item)

    def _on_close_analysis_tab(self, index):
        name = self.analysis_setup_tabs.tabText(index)
        self._remove_analysis(name)

    def _build_corners_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)

        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Process Corners"))
        add_btn = QPushButton("+ Add Corner")
        add_btn.setFixedWidth(100)
        add_btn.clicked.connect(self._add_corner_row)
        hdr.addWidget(add_btn)

        preset_btn = QPushButton("Add PVT Preset")
        preset_btn.clicked.connect(self._add_pvt_preset_corners)
        hdr.addWidget(preset_btn)

        duplicate_btn = QPushButton("Duplicate")
        duplicate_btn.clicked.connect(self._duplicate_selected_corner)
        hdr.addWidget(duplicate_btn)

        apply_models_btn = QPushButton("Apply Shared Models")
        apply_models_btn.setToolTip("Copy the shared model library setup to selected corners")
        apply_models_btn.clicked.connect(self._apply_shared_models_to_selected_corners)
        hdr.addWidget(apply_models_btn)

        # PDK selector for corner-aware models
        hdr.addWidget(QLabel("PDK:"))
        self.pdk_combo = QComboBox()
        self.pdk_combo.addItem("None", "")
        self.pdk_combo.currentIndexChanged.connect(self._on_pdk_combo_changed)
        hdr.addWidget(self.pdk_combo)

        # Corner run mode
        hdr.addWidget(QLabel("Run Mode:"))
        self.corner_mode_combo = QComboBox()
        self.corner_mode_combo.addItems(["Single", "All Corners", "Selected"])
        self.corner_mode_combo.currentIndexChanged.connect(lambda _idx: (self._refresh_corner_run_matrix_preview(), self._refresh_run_plan()))
        hdr.addWidget(self.corner_mode_combo)

        layout.addLayout(hdr)

        split = QSplitter(Qt.Orientation.Horizontal)

        self.corner_table = QTableWidget(0, 6)
        self.corner_table.setHorizontalHeaderLabels([
            "Name", "Temperature", "Voltage", "Process", "Run", "Models"
        ])
        self.corner_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.corner_table.verticalHeader().setVisible(False)
        self.corner_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.corner_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.corner_table.itemChanged.connect(lambda _item: self._on_corner_table_changed())
        self.corner_table.itemSelectionChanged.connect(self._sync_corner_inspector)
        self.corner_table.setVisible(False)

        self.corner_setup_matrix = QTableWidget(6, 0)
        self.corner_setup_matrix.setVerticalHeaderLabels([
            "Run", "Process", "Temperature", "VDD", "Models", "Validation"
        ])
        self.corner_setup_matrix.verticalHeader().setVisible(True)
        self.corner_setup_matrix.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.corner_setup_matrix.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectColumns)
        self.corner_setup_matrix.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.corner_setup_matrix.itemChanged.connect(self._on_corner_setup_matrix_changed)
        self.corner_setup_matrix.itemSelectionChanged.connect(self._select_corner_from_setup_matrix)
        self.corner_setup_matrix.itemDoubleClicked.connect(self._edit_corner_models_from_matrix)
        split.addWidget(self.corner_setup_matrix)

        inspector = QGroupBox("Selected Corner")
        form = QFormLayout(inspector)
        self.corner_name_edit = QLineEdit()
        self.corner_temp_edit = QLineEdit()
        self.corner_vdd_edit = QLineEdit()
        self.corner_process_edit = QLineEdit()
        for edit in (self.corner_name_edit, self.corner_temp_edit, self.corner_vdd_edit, self.corner_process_edit):
            edit.editingFinished.connect(self._apply_corner_inspector)
        form.addRow("Name", self.corner_name_edit)
        form.addRow("Temperature", self.corner_temp_edit)
        form.addRow("VDD", self.corner_vdd_edit)
        form.addRow("Process", self.corner_process_edit)
        self.corner_model_label = QLabel("Shared models")
        self.corner_model_label.setWordWrap(True)
        form.addRow("Models", self.corner_model_label)
        edit_models_btn = QPushButton("Edit Models")
        edit_models_btn.clicked.connect(lambda: self._edit_corner_models(self.corner_table.currentRow()))
        form.addRow("", edit_models_btn)
        self.corner_validation_label = QLabel("")
        self.corner_validation_label.setWordWrap(True)
        form.addRow("Validation", self.corner_validation_label)
        split.addWidget(inspector)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        layout.addWidget(split)

        preview_label = QLabel("Run Matrix Preview")
        preview_label.setObjectName("adePanelLabel")
        layout.addWidget(preview_label)
        self.corner_run_matrix_preview = QTableWidget(0, 0)
        self.corner_run_matrix_preview.setMinimumHeight(160)
        self.corner_run_matrix_preview.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.corner_run_matrix_preview.verticalHeader().setVisible(True)
        self.corner_run_matrix_preview.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.corner_run_matrix_preview.setToolTip("Columns are enabled corners. Rows are variable sweep points.")
        self.corner_run_matrix_preview.itemChanged.connect(self._on_run_matrix_preview_changed)
        layout.addWidget(self.corner_run_matrix_preview)
        run_buttons = QHBoxLayout()
        run_selected_btn = QPushButton("Run Selected Cells")
        run_selected_btn.clicked.connect(self._run_selected_matrix_cells)
        run_buttons.addWidget(run_selected_btn)
        rerun_failed_btn = QPushButton("Rerun Failed Cells")
        rerun_failed_btn.clicked.connect(self._rerun_failed_matrix_cells)
        run_buttons.addWidget(rerun_failed_btn)
        run_buttons.addStretch()
        layout.addLayout(run_buttons)

        # Add default corners
        for name, temp, vdd, proc in [
            ("TT_25C", "25", "1.8", "tt"),
            ("FF_m40C", "-40", "1.98", "ff"),
            ("SS_125C", "125", "1.62", "ss"),
        ]:
            self._add_corner(name, temp, vdd, proc)
        self._refresh_corner_setup_matrix()
        self._refresh_corner_run_matrix_preview()
        self.corner_table.selectRow(0)

        self.main_tabs.addTab(widget, "Corners")
        QTimer.singleShot(0, self._populate_pdk_combo)

    def _populate_pdk_combo(self):
        if not hasattr(self, "pdk_combo") or self._pdk_combo_populated:
            return
        self._pdk_combo_populated = True
        registry = self._ensure_pdk_registry()
        if not registry:
            return

        self.pdk_combo.blockSignals(True)
        try:
            existing = {
                self.pdk_combo.itemData(i)
                for i in range(self.pdk_combo.count())
                if self.pdk_combo.itemData(i)
            }
            hidden_pdks = {"sky130", "gf180mcu"}
            for pdk in registry.get_all_pdks():
                if pdk.name in hidden_pdks:
                    continue
                if pdk.name not in existing:
                    self.pdk_combo.addItem(pdk.display_name, pdk.name)
                    existing.add(pdk.name)

            target = self._pending_simenv_pdk or ""
            if not target and not self.pdk_combo.currentData():
                target = self._infer_pdk_name()
            if target:
                if self.pdk_combo.findData(target) < 0:
                    pdk = registry.get_pdk(target)
                    if pdk:
                        self.pdk_combo.addItem(pdk.display_name, pdk.name)
                idx = self.pdk_combo.findData(target)
                if idx >= 0:
                    self.pdk_combo.setCurrentIndex(idx)
        except Exception as exc:
            self._log(f"Could not load PDK list: {exc}")
        finally:
            self.pdk_combo.blockSignals(False)
        self._update_pdk_badge()
        self._refresh_pdk_model_overview()
        self._refresh_run_plan()

    def _on_pdk_combo_changed(self, _idx: int = 0):
        self._update_pdk_badge()
        self._refresh_pdk_model_overview()
        self._refresh_run_plan()

    def _update_pdk_badge(self):
        if not hasattr(self, "pdk_badge"):
            return
        pdk_name = self._selected_pdk_name(infer=True)
        attached = ""
        try:
            attached = self.db.get_library_pdk(self.library)
        except Exception:
            attached = ""
        label = pdk_name or "none"
        if attached and attached == pdk_name:
            label = f"{label} attached"
        self.pdk_badge.setText(f"PDK: {label}")

    def _add_corner_row(self):
        self._add_corner(self._unique_corner_name("corner"), "25", "1.8", "tt")

    def _add_corner(self, name, temp, vdd, proc):
        r = self.corner_table.rowCount()
        self.corner_table.insertRow(r)
        self.corner_table.setItem(r, 0, QTableWidgetItem(name))
        self.corner_table.setItem(r, 1, QTableWidgetItem(temp))
        self.corner_table.setItem(r, 2, QTableWidgetItem(vdd))
        self.corner_table.setItem(r, 3, QTableWidgetItem(proc))
        chk = QCheckBox()
        chk.setChecked(True)
        chk.stateChanged.connect(lambda _state: self._on_corner_table_changed())
        self.corner_table.setCellWidget(r, 4, chk)
        edit = QPushButton(self._corner_model_summary(str(name)))
        edit.setToolTip("Edit model directives for this corner")
        edit.clicked.connect(lambda _checked=False, row=r: self._edit_corner_models(row))
        self.corner_table.setCellWidget(r, 5, edit)
        self._refresh_run_plan()
        self._refresh_corner_setup_matrix()
        self._refresh_corner_run_matrix_preview()
        self._refresh_model_corner_summary()
        return r

    def _corner_names(self) -> set[str]:
        return {
            self._table_text(self.corner_table, r, 0)
            for r in range(self.corner_table.rowCount())
            if self._table_text(self.corner_table, r, 0)
        }

    def _unique_corner_name(self, base: str) -> str:
        base = str(base or "corner").strip() or "corner"
        names = self._corner_names()
        if base not in names:
            return base
        idx = 2
        while f"{base}_{idx}" in names:
            idx += 1
        return f"{base}_{idx}"

    def _add_pvt_preset_corners(self):
        for name, temp, vdd, proc in [
            ("TT_25C", "25", "1.8", "tt"),
            ("FF_m40C", "-40", "1.98", "ff"),
            ("SS_125C", "125", "1.62", "ss"),
        ]:
            if name not in self._corner_names():
                self._add_corner(name, temp, vdd, proc)
        self._refresh_corner_model_buttons()
        self._refresh_corner_setup_matrix()
        self._sync_corner_inspector()

    def _duplicate_selected_corner(self):
        row = self.corner_table.currentRow()
        if row < 0:
            return
        old_name = self._table_text(self.corner_table, row, 0, "corner")
        new_name = self._unique_corner_name(f"{old_name}_copy")
        new_row = self._add_corner(
            new_name,
            self._table_text(self.corner_table, row, 1, "25"),
            self._table_text(self.corner_table, row, 2, "1.8"),
            self._table_text(self.corner_table, row, 3, "tt"),
        )
        directives = list(self._corner_model_directives.get(old_name, []))
        if directives:
            self._corner_model_directives[new_name] = directives
        self.corner_table.selectRow(new_row)
        self._refresh_corner_model_buttons()
        self._refresh_corner_setup_matrix()
        self._save_simenv_view_silent()

    def _apply_shared_models_to_selected_corners(self):
        directives = self._collect_model_table_directives() if hasattr(self, "model_table") else []
        rows = sorted({idx.row() for idx in self.corner_table.selectedIndexes()})
        if not rows:
            row = self.corner_table.currentRow()
            rows = [row] if row >= 0 else []
        for row in rows:
            name = self._table_text(self.corner_table, row, 0, "corner")
            if directives:
                self._corner_model_directives[name] = list(directives)
            else:
                self._corner_model_directives.pop(name, None)
        self._refresh_corner_model_buttons()
        self._refresh_corner_setup_matrix()
        self._sync_corner_inspector()
        self._refresh_run_plan()
        self._save_simenv_view_silent()

    def _corner_model_summary(self, name: str) -> str:
        count = len(self._corner_model_directives.get(name, []))
        return f"{count} model(s)" if count else "Shared"

    def _refresh_corner_model_buttons(self):
        if not hasattr(self, "corner_table"):
            return
        for row in range(self.corner_table.rowCount()):
            name = self._table_text(self.corner_table, row, 0, "corner")
            button = self.corner_table.cellWidget(row, 5)
            if isinstance(button, QPushButton):
                button.setText(self._corner_model_summary(name))
        self._refresh_corner_setup_matrix()
        self._refresh_model_corner_summary()

    def _on_corner_table_changed(self):
        self._refresh_corner_setup_matrix()
        self._refresh_corner_run_matrix_preview()
        self._sync_corner_inspector()
        self._refresh_model_corner_summary()
        self._refresh_run_plan()

    def _refresh_corner_setup_matrix(self):
        if not hasattr(self, "corner_setup_matrix") or not hasattr(self, "corner_table"):
            return
        if getattr(self, "_corner_matrix_syncing", False):
            return
        self._corner_matrix_syncing = True
        try:
            table = self.corner_setup_matrix
            cols = self.corner_table.rowCount()
            table.blockSignals(True)
            table.setColumnCount(cols)
            headers = [
                self._table_text(self.corner_table, col, 0, f"corner_{col}")
                for col in range(cols)
            ]
            table.setHorizontalHeaderLabels(headers)
            for col in range(cols):
                name = self._table_text(self.corner_table, col, 0, f"corner_{col}")
                proc = self._table_text(self.corner_table, col, 3, "tt")
                chk = self.corner_table.cellWidget(col, 4)
                enabled = bool(chk.isChecked()) if isinstance(chk, QCheckBox) else True
                values = [
                    "Run" if enabled else "Skip",
                    proc,
                    self._table_text(self.corner_table, col, 1, "25"),
                    self._table_text(self.corner_table, col, 2, "1.8"),
                    self._corner_model_summary(name),
                    "PASS",
                ]
                directives = self._resolved_model_directives(proc, name, self._selected_pdk_name())
                errors = validate_model_directives(directives)
                if errors:
                    values[5] = f"{len(errors)} issue(s)"
                for row, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if row == 0:
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                        item.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
                    elif row in (4, 5):
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if row == 5:
                        if errors:
                            item.setForeground(QColor("#ffd166"))
                            item.setBackground(QColor("#3a3117"))
                            item.setToolTip("; ".join(errors[:8]))
                        else:
                            item.setForeground(QColor("#74c69d"))
                            item.setBackground(QColor("#173524"))
                    table.setItem(row, col, item)
            table.resizeRowsToContents()
            table.blockSignals(False)
        finally:
            self._corner_matrix_syncing = False

    def _corner_row_for_setup_column(self, col: int) -> int:
        return col if 0 <= col < self.corner_table.rowCount() else -1

    def _on_corner_setup_matrix_changed(self, item: QTableWidgetItem):
        if getattr(self, "_corner_matrix_syncing", False) or item is None:
            return
        row = item.row()
        col = item.column()
        corner_row = self._corner_row_for_setup_column(col)
        if corner_row < 0:
            return
        self._corner_matrix_syncing = True
        try:
            if row == 0:
                chk = self.corner_table.cellWidget(corner_row, 4)
                if isinstance(chk, QCheckBox):
                    chk.setChecked(item.checkState() == Qt.CheckState.Checked)
            elif row == 1:
                self._set_table_text(self.corner_table, corner_row, 3, item.text().strip() or "tt")
            elif row == 2:
                self._set_table_text(self.corner_table, corner_row, 1, item.text().strip() or "25")
            elif row == 3:
                self._set_table_text(self.corner_table, corner_row, 2, item.text().strip() or "1.8")
        finally:
            self._corner_matrix_syncing = False
        self.corner_table.selectRow(corner_row)
        self._refresh_corner_setup_matrix()
        self._refresh_corner_run_matrix_preview()
        self._sync_corner_inspector()
        self._refresh_run_plan()
        self._save_simenv_view_silent()

    def _select_corner_from_setup_matrix(self):
        if not hasattr(self, "corner_setup_matrix") or getattr(self, "_corner_matrix_syncing", False):
            return
        cols = sorted({idx.column() for idx in self.corner_setup_matrix.selectedIndexes()})
        if not cols:
            return
        row = self._corner_row_for_setup_column(cols[0])
        if row >= 0 and self.corner_table.currentRow() != row:
            self.corner_table.selectRow(row)

    def _edit_corner_models_from_matrix(self, item: QTableWidgetItem):
        if item is None:
            return
        row = self._corner_row_for_setup_column(item.column())
        if row < 0:
            return
        self.corner_table.selectRow(row)
        if item.row() == 4:
            self._edit_corner_models(row)

    def _refresh_corner_run_matrix_preview(self):
        if not hasattr(self, "corner_run_matrix_preview") or not hasattr(self, "corner_table"):
            return
        table = self.corner_run_matrix_preview
        mode = self.corner_mode_combo.currentText() if hasattr(self, "corner_mode_combo") else "Single"
        corners = [{"name": "Single"}] if mode == "Single" else self.get_corner_data()
        try:
            sweep_points = self.sweep_widget.expanded_points() if hasattr(self, "sweep_widget") else [("", {})]
        except Exception as exc:
            sweep_points = [(f"Invalid sweep: {exc}", {})]
        sweep_labels = [label or "Single" for label, _overrides in sweep_points] or ["Single"]
        table.blockSignals(True)
        try:
            table.setRowCount(len(sweep_labels))
            table.setColumnCount(len(corners))
            table.setHorizontalHeaderLabels([corner.get("name", "corner") for corner in corners])
            table.setVerticalHeaderLabels(sweep_labels)
            for row, sweep_label in enumerate(sweep_labels):
                for col, corner in enumerate(corners):
                    key = (corner.get("name", "corner"), sweep_label)
                    status = self._run_matrix_status.get(key, "Run")
                    text = status
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setFlags((item.flags() & ~Qt.ItemFlag.ItemIsEditable) | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Unchecked if key in self._disabled_run_cells else Qt.CheckState.Checked)
                    item.setData(Qt.ItemDataRole.UserRole, {
                        "corner": key[0],
                        "sweep": sweep_label,
                    })
                    if key in self._disabled_run_cells:
                        item.setText("Skip")
                        item.setForeground(QColor("#7f8c99"))
                    elif status == "Pending":
                        item.setForeground(QColor("#d7e7ef"))
                        item.setBackground(QColor("#263340"))
                    elif status == "Running":
                        item.setForeground(QColor("#ffd166"))
                        item.setBackground(QColor("#463a12"))
                    elif status == "PASS":
                        item.setForeground(QColor("#74c69d"))
                        item.setBackground(QColor("#173524"))
                    elif status == "FAIL":
                        item.setForeground(QColor("#ff8fa3"))
                        item.setBackground(QColor("#4a0e17"))
                    else:
                        item.setForeground(QColor("#74c69d"))
                        item.setBackground(QColor("#173524"))
                    table.setItem(row, col, item)
            table.resizeRowsToContents()
            table.resizeColumnsToContents()
        finally:
            table.blockSignals(False)

    def _on_run_matrix_preview_changed(self, item: QTableWidgetItem):
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return
        key = (str(data.get("corner", "")).strip(), str(data.get("sweep", "")).strip() or "Single")
        if not key[0]:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self._disabled_run_cells.discard(key)
        else:
            self._disabled_run_cells.add(key)
        self._refresh_corner_run_matrix_preview()
        self._refresh_run_plan()
        self._save_simenv_view_silent()

    def _run_selected_matrix_cells(self):
        if not hasattr(self, "corner_run_matrix_preview"):
            return
        selected: set[tuple[str, str]] = set()
        for idx in self.corner_run_matrix_preview.selectedIndexes():
            item = self.corner_run_matrix_preview.item(idx.row(), idx.column())
            data = item.data(Qt.ItemDataRole.UserRole) if item else {}
            if isinstance(data, dict):
                corner = str(data.get("corner", "")).strip()
                sweep = str(data.get("sweep", "")).strip() or "Single"
                if corner:
                    selected.add((corner, sweep))
        if not selected:
            self.statusBar().showMessage("Select run matrix cell(s) first", 5000)
            return
        self._run_selected_cells_once = selected
        self._on_run()

    def _rerun_failed_matrix_cells(self):
        failed = {
            key for key, status in self._run_matrix_status.items()
            if status == "FAIL" and key not in self._disabled_run_cells
        }
        if not failed:
            self.statusBar().showMessage("No failed run matrix cells to rerun", 5000)
            return
        self._run_selected_cells_once = failed
        self._on_run()

    def _run_cell_enabled(self, corner: str, sweep_label: str) -> bool:
        key = (str(corner or "Single").strip() or "Single", str(sweep_label or "Single").strip() or "Single")
        if self._run_selected_cells_once and key not in self._run_selected_cells_once:
            return False
        return key not in self._disabled_run_cells

    def _run_cell_key_from_name(self, run_name: str) -> tuple[str, str]:
        corner = self._results_corner_from_run_name(run_name) or "Single"
        return (corner, self._results_sweep_from_run_name(run_name, corner))

    def _mark_run_cell_status(self, run_name: str, status: str):
        self._run_matrix_status[self._run_cell_key_from_name(run_name)] = status
        self._refresh_corner_run_matrix_preview()

    def _mark_jobs_pending(self, jobs: list[tuple[str, str, str]]):
        for run_name, _netlist, _sim_name in jobs:
            self._run_matrix_status[self._run_cell_key_from_name(run_name)] = "Pending"
        self._refresh_corner_run_matrix_preview()

    def _sync_corner_inspector(self):
        if not hasattr(self, "corner_name_edit"):
            return
        row = self.corner_table.currentRow()
        enabled = row >= 0
        for edit in (self.corner_name_edit, self.corner_temp_edit, self.corner_vdd_edit, self.corner_process_edit):
            edit.setEnabled(enabled)
        if not enabled:
            self.corner_model_label.setText("")
            self.corner_validation_label.setText("")
            return
        edits = [
            (self.corner_name_edit, 0, "corner"),
            (self.corner_temp_edit, 1, "25"),
            (self.corner_vdd_edit, 2, "1.8"),
            (self.corner_process_edit, 3, "tt"),
        ]
        for edit, col, default in edits:
            edit.blockSignals(True)
            edit.setText(self._table_text(self.corner_table, row, col, default))
            edit.blockSignals(False)
        name = self._table_text(self.corner_table, row, 0, "corner")
        proc = self._table_text(self.corner_table, row, 3, "tt")
        pdk_name = self._selected_pdk_name()
        directives = self._resolved_model_directives(proc, name, pdk_name)
        own = len(self._corner_model_directives.get(name, []))
        self.corner_model_label.setText(f"{own or 'Shared'}; resolved {len(directives)} directive(s)")
        errors = validate_model_directives(directives)
        self.corner_validation_label.setText("PASS" if not errors else "; ".join(errors[:3]))

    def _apply_corner_inspector(self):
        row = self.corner_table.currentRow()
        if row < 0:
            return
        old_name = self._table_text(self.corner_table, row, 0, "corner")
        new_name = self.corner_name_edit.text().strip() or old_name
        values = [
            new_name,
            self.corner_temp_edit.text().strip() or "25",
            self.corner_vdd_edit.text().strip() or "1.8",
            self.corner_process_edit.text().strip() or "tt",
        ]
        for col, value in enumerate(values):
            self.corner_table.setItem(row, col, QTableWidgetItem(value))
        if new_name != old_name and old_name in self._corner_model_directives:
            self._corner_model_directives[new_name] = self._corner_model_directives.pop(old_name)
        self._refresh_corner_model_buttons()
        self._sync_corner_inspector()
        self._save_simenv_view_silent()

    def _build_model_libraries_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        title = QLabel("Model Setup")
        title.setObjectName("adePanelTitle")
        toolbar.addWidget(title)
        toolbar.addWidget(QLabel("Setup:"))
        self.model_setup_name_edit = QLineEdit(self._model_setup_name)
        self.model_setup_name_edit.setMaximumWidth(180)
        self.model_setup_name_edit.editingFinished.connect(self._on_model_setup_name_changed)
        toolbar.addWidget(self.model_setup_name_edit)
        toolbar.addStretch()
        load_pdk_btn = QPushButton("Load PDK Models")
        load_pdk_btn.setToolTip("Load discovered model files from the selected PDK into the explicit model table")
        load_pdk_btn.clicked.connect(self._load_selected_pdk_model_files)
        toolbar.addWidget(load_pdk_btn)
        apply_pdk_btn = QPushButton("Apply PDK Setup")
        apply_pdk_btn.setToolTip("Load the selected PDK's model files, sections, and corner presets")
        apply_pdk_btn.clicked.connect(self._apply_selected_pdk_manifest)
        toolbar.addWidget(apply_pdk_btn)
        save_setup_btn = QPushButton("Save Setup")
        save_setup_btn.setToolTip("Save this model library setup by name")
        save_setup_btn.clicked.connect(self._on_save_model_setup)
        toolbar.addWidget(save_setup_btn)
        load_setup_btn = QPushButton("Load Setup")
        load_setup_btn.setToolTip("Load a saved model library setup")
        load_setup_btn.clicked.connect(self._on_load_model_setup)
        toolbar.addWidget(load_setup_btn)
        layout.addLayout(toolbar)

        pdk_frame = QFrame()
        pdk_frame.setObjectName("adeNavigator")
        pdk_layout = QGridLayout(pdk_frame)
        pdk_layout.setContentsMargins(8, 6, 8, 6)
        pdk_layout.setHorizontalSpacing(12)
        pdk_layout.setVerticalSpacing(4)
        pdk_title = QLabel("PDK / Model Library")
        pdk_title.setObjectName("adePanelLabel")
        pdk_layout.addWidget(pdk_title, 0, 0)
        self.model_pdk_label = QLabel("PDK: none")
        self.model_pdk_label.setStyleSheet("background:transparent;color:#f0f0f0;font-weight:700;")
        pdk_layout.addWidget(self.model_pdk_label, 0, 1)
        self.model_pdk_health_label = QLabel("Health: not checked")
        self.model_pdk_health_label.setStyleSheet("background:transparent;color:#b9c2c7;")
        pdk_layout.addWidget(self.model_pdk_health_label, 0, 2)
        self.model_pdk_lock_label = QLabel("Lock: not written")
        self.model_pdk_lock_label.setStyleSheet("background:transparent;color:#8fa9b8;")
        pdk_layout.addWidget(self.model_pdk_lock_label, 1, 1, 1, 2)
        validate_btn = QPushButton("Validate")
        validate_btn.setToolTip("Validate selected PDK health, model files, and corner mapping")
        validate_btn.clicked.connect(self._validate_pdk_model_setup)
        pdk_layout.addWidget(validate_btn, 0, 3)
        repair_btn = QPushButton("Choose Models Folder")
        repair_btn.setToolTip("Repair selected PDK model discovery from inside SimENV")
        repair_btn.clicked.connect(self._repair_selected_pdk_models_folder)
        pdk_layout.addWidget(repair_btn, 1, 3)
        pdk_layout.setColumnStretch(2, 1)
        layout.addWidget(pdk_frame)

        files_toolbar = QHBoxLayout()
        files_toolbar.setSpacing(8)
        files_label = QLabel("Model Files")
        files_label.setObjectName("adePanelLabel")
        files_toolbar.addWidget(files_label)
        add_lib = QPushButton("+ .lib")
        add_lib.clicked.connect(lambda: self._add_model_directive_row("lib", "", ""))
        files_toolbar.addWidget(add_lib)
        add_inc = QPushButton("+ include")
        add_inc.clicked.connect(lambda: self._add_model_directive_row("include", "", ""))
        files_toolbar.addWidget(add_inc)
        ihp_btn = QPushButton("IHP Template")
        ihp_btn.setToolTip("Populate shared IHP SG13G2 GSPICE model wrappers for a typical setup")
        ihp_btn.clicked.connect(self._populate_ihp_model_template)
        files_toolbar.addWidget(ihp_btn)
        map_sections_btn = QPushButton("Map Sections")
        map_sections_btn.setToolTip("Assign loaded .lib sections to corners by process name")
        map_sections_btn.clicked.connect(self._map_model_sections_to_corners)
        files_toolbar.addWidget(map_sections_btn)
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self._remove_selected_model_directives)
        files_toolbar.addWidget(remove_btn)
        files_toolbar.addStretch()
        delete_setup_btn = QPushButton("Delete Setup")
        delete_setup_btn.setToolTip("Delete a saved model library setup")
        delete_setup_btn.clicked.connect(self._on_delete_model_setup)
        files_toolbar.addWidget(delete_setup_btn)
        layout.addLayout(files_toolbar)

        self.model_table = QTableWidget(0, 5)
        self.model_table.setHorizontalHeaderLabels(["Type", "Path", "Browse", "Section", "Status"])
        self.model_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.model_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.model_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.model_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.model_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.model_table.verticalHeader().setVisible(False)
        self.model_table.setMinimumHeight(126)
        self.model_table.setMaximumHeight(190)
        self.model_table.itemChanged.connect(lambda _item: self._on_model_table_changed())
        layout.addWidget(self.model_table)

        summary_label = QLabel("Corner Section Map")
        summary_label.setObjectName("adePanelLabel")
        layout.addWidget(summary_label)
        self.model_corner_summary_table = QTableWidget(0, 4)
        self.model_corner_summary_table.setHorizontalHeaderLabels(["Corner", "Process", "Section", "Models"])
        self.model_corner_summary_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.model_corner_summary_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.model_corner_summary_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.model_corner_summary_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.model_corner_summary_table.verticalHeader().setVisible(False)
        self.model_corner_summary_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.model_corner_summary_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.model_corner_summary_table.setMinimumHeight(82)
        self.model_corner_summary_table.setMaximumHeight(130)
        layout.addWidget(self.model_corner_summary_table)

        self.model_advanced_tabs = QTabWidget()
        self.model_advanced_tabs.setObjectName("adeSubTabs")

        catalog_tab = QWidget()
        catalog_layout = QVBoxLayout(catalog_tab)
        catalog_layout.setContentsMargins(6, 6, 6, 6)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter:"))
        self.model_catalog_filter_edit = QLineEdit()
        self.model_catalog_filter_edit.setPlaceholderText("model, type, section, or path")
        self.model_catalog_filter_edit.textChanged.connect(lambda _text: self._refresh_model_catalog())
        filter_row.addWidget(self.model_catalog_filter_edit)
        refresh_catalog_btn = QPushButton("Refresh")
        refresh_catalog_btn.setToolTip("Parse loaded model files for .MODEL and .SUBCKT names")
        refresh_catalog_btn.clicked.connect(self._refresh_model_catalog)
        filter_row.addWidget(refresh_catalog_btn)
        catalog_layout.addLayout(filter_row)
        self.model_catalog_table = QTableWidget(0, 5)
        self.model_catalog_table.setHorizontalHeaderLabels(["Name", "Kind", "Type / Pins", "Section", "Path"])
        self.model_catalog_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.model_catalog_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.model_catalog_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.model_catalog_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.model_catalog_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.model_catalog_table.verticalHeader().setVisible(False)
        catalog_layout.addWidget(self.model_catalog_table)
        self.model_advanced_tabs.addTab(catalog_tab, "Discovered Models")

        bindings_tab = QWidget()
        bindings_layout = QVBoxLayout(bindings_tab)
        bindings_layout.setContentsMargins(6, 6, 6, 6)
        binding_toolbar = QHBoxLayout()
        add_binding_btn = QPushButton("Add From Schematic")
        add_binding_btn.clicked.connect(self._populate_model_bindings_from_schematic)
        binding_toolbar.addWidget(add_binding_btn)
        apply_model_btn = QPushButton("Use Selected Model")
        apply_model_btn.clicked.connect(self._apply_selected_catalog_model_to_binding)
        binding_toolbar.addWidget(apply_model_btn)
        remove_binding_btn = QPushButton("Remove Binding")
        remove_binding_btn.clicked.connect(self._remove_selected_model_bindings)
        binding_toolbar.addWidget(remove_binding_btn)
        binding_toolbar.addStretch()
        bindings_layout.addLayout(binding_toolbar)

        self.model_binding_table = QTableWidget(0, 5)
        self.model_binding_table.setHorizontalHeaderLabels(["Enable", "Instance", "Device", "Model", "Corner"])
        self.model_binding_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.model_binding_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.model_binding_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.model_binding_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.model_binding_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.model_binding_table.verticalHeader().setVisible(False)
        self.model_binding_table.itemChanged.connect(lambda _item: (self._collect_model_bindings(), self._refresh_binding_statuses(), self._refresh_run_plan()))
        bindings_layout.addWidget(self.model_binding_table)
        self.model_advanced_tabs.addTab(bindings_tab, "Device Bindings")

        layout.addWidget(self.model_advanced_tabs, 1)

        hint = QLabel(
            "Corners use these model files unless a corner has its own model list. "
            "Use Advanced tabs only when you need catalog inspection or per-instance overrides."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#8c9aa8;background:transparent;padding:4px;")
        layout.addWidget(hint)

        self.main_tabs.addTab(widget, "Model Setup")
        QTimer.singleShot(0, self._refresh_model_catalog)
        QTimer.singleShot(0, self._refresh_model_corner_summary)
        QTimer.singleShot(0, self._refresh_pdk_model_overview)

    def _on_model_setup_name_changed(self):
        if hasattr(self, "model_setup_name_edit"):
            self._model_setup_name = self.model_setup_name_edit.text().strip() or "default"
        self._refresh_run_plan()
        self._save_simenv_view_silent()

    def _refresh_pdk_model_overview(self):
        if not hasattr(self, "model_pdk_label"):
            return
        pdk_name = self._selected_pdk_name()
        attached = ""
        try:
            attached = self.db.get_library_pdk(self.library)
        except Exception:
            attached = ""
        suffix = " inherited" if attached and attached == pdk_name else ""
        self.model_pdk_label.setText(f"PDK: {pdk_name or 'none'}{suffix}")
        self.model_pdk_lock_label.setText(f"Lock: {self._pdk_lock_path()}")

        registry = self._ensure_pdk_registry()
        if not pdk_name or not registry:
            self.model_pdk_health_label.setText("Health: no PDK selected")
            return
        report = registry.get_pdk_health_report(pdk_name) if hasattr(registry, "get_pdk_health_report") else {}
        issues = report.get("issues", []) or []
        rows = self.model_table.rowCount() if hasattr(self, "model_table") else 0
        corner_count = self.corner_table.rowCount() if hasattr(self, "corner_table") else 0
        if not report:
            self.model_pdk_health_label.setText(f"Health: {rows} model row(s), {corner_count} corner(s)")
        elif issues:
            self.model_pdk_health_label.setText(f"Health: {len(issues)} issue(s), {rows} model row(s), {corner_count} corner(s)")
        else:
            self.model_pdk_health_label.setText(f"Health: Ready, {rows} model row(s), {corner_count} corner(s)")

    def _validate_pdk_model_setup(self):
        pdk_name = self._selected_pdk_name()
        registry = self._ensure_pdk_registry()
        messages = []
        if not pdk_name or not registry:
            messages.append("No PDK selected.")
        elif hasattr(registry, "get_pdk_health_report"):
            report = registry.get_pdk_health_report(pdk_name)
            messages.extend(report.get("issues", []) or [])
        directives = self._collect_model_table_directives() if hasattr(self, "model_table") else []
        messages.extend(validate_model_directives(directives))
        if hasattr(self, "corner_table") and self.corner_table.rowCount() == 0:
            messages.append("No corners configured.")
        self._refresh_pdk_model_overview()
        if messages:
            QMessageBox.warning(self, "Validate Model Setup", "\n".join(f"- {msg}" for msg in messages[:12]))
            return False
        QMessageBox.information(self, "Validate Model Setup", "PDK, model files, and corners look ready.")
        return True

    def _repair_selected_pdk_models_folder(self):
        pdk_name = self._selected_pdk_name()
        registry = self._ensure_pdk_registry()
        if not pdk_name or not registry:
            QMessageBox.information(self, "Choose Models Folder", "Select a PDK first.")
            return
        pdk = registry.get_pdk(pdk_name)
        start = getattr(pdk, "models_path", "") or getattr(pdk, "root_path", "") or ""
        path = QFileDialog.getExistingDirectory(self, "Choose PDK Models Folder", start)
        if not path:
            return
        repaired = registry.set_pdk_models_path(pdk_name, path)
        if not repaired:
            QMessageBox.warning(self, "Choose Models Folder", "Could not use that models folder.")
            return
        self._apply_selected_pdk_manifest()
        self._refresh_pdk_model_overview()
        QMessageBox.information(self, "Choose Models Folder", f"Updated model discovery for {repaired.display_name or repaired.name}.")

    def _save_model_setup_named(self, name: str):
        name = str(name or "").strip()
        if not name:
            return
        if hasattr(self, "model_setup_name_edit"):
            self.model_setup_name_edit.setText(name)
            self._on_model_setup_name_changed()
        store = self._load_preset_store()
        store[name] = self._collect_named_preset("models")
        self._save_preset_store(store)

    def _model_setup_names(self) -> list[str]:
        store = self._load_preset_store()
        return sorted(
            name for name, entry in store.items()
            if isinstance(entry, dict) and entry.get("kind") == "models"
        )

    def _load_model_setup_named(self, name: str) -> bool:
        entry = self._load_preset_store().get(str(name or "").strip())
        if not isinstance(entry, dict) or entry.get("kind") != "models":
            return False
        self._apply_named_preset(entry)
        return True

    def _delete_model_setup_named(self, name: str) -> bool:
        store = self._load_preset_store()
        key = str(name or "").strip()
        entry = store.get(key)
        if not isinstance(entry, dict) or entry.get("kind") != "models":
            return False
        del store[key]
        self._save_preset_store(store)
        return True

    def _on_save_model_setup(self):
        default = self.model_setup_name_edit.text().strip() if hasattr(self, "model_setup_name_edit") else self._model_setup_name
        name, ok = QInputDialog.getText(self, "Save Model Setup", "Setup name:", text=default or "default")
        if not ok or not str(name).strip():
            return
        self._save_model_setup_named(str(name).strip())
        self.statusBar().showMessage(f"Saved model setup: {str(name).strip()}", 4000)

    def _on_load_model_setup(self):
        names = self._model_setup_names()
        if not names:
            QMessageBox.information(self, "Load Model Setup", "No model setups have been saved yet.")
            return
        name, ok = QInputDialog.getItem(self, "Load Model Setup", "Setup:", names, 0, False)
        if ok and name and self._load_model_setup_named(str(name)):
            self.statusBar().showMessage(f"Loaded model setup: {name}", 4000)

    def _on_delete_model_setup(self):
        names = self._model_setup_names()
        if not names:
            QMessageBox.information(self, "Delete Model Setup", "No model setups have been saved yet.")
            return
        name, ok = QInputDialog.getItem(self, "Delete Model Setup", "Setup:", names, 0, False)
        if ok and name and self._delete_model_setup_named(str(name)):
            self.statusBar().showMessage(f"Deleted model setup: {name}", 4000)

    def _add_model_directive_row(self, kind: str, path: str, section: str = ""):
        if not hasattr(self, "model_table"):
            return
        r = self.model_table.rowCount()
        self.model_table.insertRow(r)
        kind_combo = QComboBox()
        kind_combo.addItems(["lib", "include", "gsdi"])
        idx = kind_combo.findText(str(kind or "lib").lower())
        kind_combo.setCurrentIndex(idx if idx >= 0 else 0)
        kind_combo.currentIndexChanged.connect(lambda _idx: self._on_model_table_changed())
        self.model_table.setCellWidget(r, 0, kind_combo)
        self.model_table.setItem(r, 1, QTableWidgetItem(str(path or "")))
        browse = QPushButton("...")
        browse.setToolTip("Browse model file")
        browse.clicked.connect(lambda _checked=False, row=r: self._browse_model_directive_path(row))
        self.model_table.setCellWidget(r, 2, browse)
        section_combo = QComboBox()
        section_combo.setEditable(True)
        section_combo.currentTextChanged.connect(lambda _text: self._on_model_table_changed())
        self.model_table.setCellWidget(r, 3, section_combo)
        self.model_table.setItem(r, 4, QTableWidgetItem(""))
        self._refresh_model_section_combo(r, section)
        self._on_model_table_changed()

    def _on_model_table_changed(self):
        self._sync_corner_inspector()
        self._refresh_model_directive_statuses()
        self._refresh_model_catalog()
        self._refresh_model_binding_model_choices()
        self._refresh_binding_statuses()
        self._refresh_model_corner_summary()
        self._refresh_pdk_model_overview()
        self._refresh_run_plan()

    def _browse_model_directive_path(self, row: int):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Model File",
            "",
            "Model Files (*.lib *.sp *.spice *.cir *.model *.scs *.gsdi);;All Files (*)",
        )
        if not path:
            return
        self.model_table.setItem(row, 1, QTableWidgetItem(path))
        suffix = os.path.splitext(path)[1].lower()
        kind_widget = self.model_table.cellWidget(row, 0)
        if isinstance(kind_widget, QComboBox):
            kind_widget.setCurrentText("lib" if suffix == ".lib" else ("gsdi" if suffix == ".gsdi" else "include"))
        self._refresh_model_section_combo(row, "")
        self._on_model_table_changed()

    def _refresh_model_section_combo(self, row: int, selected: str = ""):
        combo = self.model_table.cellWidget(row, 3) if hasattr(self, "model_table") else None
        if not isinstance(combo, QComboBox):
            return
        current = str(selected or combo.currentText() or "").strip()
        path = self._table_text(self.model_table, row, 1)
        sections = extract_lib_sections(path)
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("")
        combo.addItems(sections)
        if current:
            idx = combo.findText(current)
            if idx < 0:
                combo.addItem(current)
                idx = combo.findText(current)
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _refresh_model_directive_statuses(self):
        if not hasattr(self, "model_table"):
            return
        was_blocked = self.model_table.signalsBlocked()
        self.model_table.blockSignals(True)
        try:
            for row in range(self.model_table.rowCount()):
                directive = self._model_directive_from_row(row)
                errors = validate_model_directives([directive]) if directive.path else ["empty path"]
                text = "OK" if not errors else errors[0]
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if errors:
                    item.setForeground(QColor("#ffd166"))
                    item.setBackground(QColor("#3a3117"))
                    item.setToolTip("; ".join(errors))
                else:
                    item.setForeground(QColor("#74c69d"))
                    item.setBackground(QColor("#173524"))
                self.model_table.setItem(row, 4, item)
        finally:
            self.model_table.blockSignals(was_blocked)

    def _refresh_model_corner_summary(self):
        if not hasattr(self, "model_corner_summary_table"):
            return
        table = self.model_corner_summary_table
        corners = self.get_corner_data() if hasattr(self, "corner_table") else []
        table.blockSignals(True)
        try:
            table.setRowCount(len(corners))
            pdk_name = self._selected_pdk_name()
            for row, corner in enumerate(corners):
                name = str(corner.get("name", "") or f"corner_{row}")
                process = str(corner.get("process", "") or "tt")
                directives = self._resolved_model_directives(process, name, pdk_name)
                sections = sorted({
                    directive.section.strip()
                    for directive in directives
                    if directive.kind == "lib" and directive.section.strip()
                })
                paths = [os.path.basename(directive.path) or directive.path for directive in directives]
                values = [
                    name,
                    process,
                    ", ".join(sections) if sections else "-",
                    ", ".join(paths[:3]) + (f" +{len(paths) - 3}" if len(paths) > 3 else ""),
                ]
                for col, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if col == 2 and not sections and directives:
                        item.setForeground(QColor("#ffd166"))
                    table.setItem(row, col, item)
            table.resizeColumnsToContents()
            table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        finally:
            table.blockSignals(False)

    def _model_directive_from_row(self, row: int) -> ModelDirective:
        kind_widget = self.model_table.cellWidget(row, 0)
        kind = kind_widget.currentText() if isinstance(kind_widget, QComboBox) else "lib"
        section_widget = self.model_table.cellWidget(row, 3)
        section = section_widget.currentText().strip() if isinstance(section_widget, QComboBox) else self._table_text(self.model_table, row, 3)
        return ModelDirective(kind, self._table_text(self.model_table, row, 1), section)

    def _remove_selected_model_directives(self):
        if not hasattr(self, "model_table"):
            return
        rows = sorted({idx.row() for idx in self.model_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.model_table.removeRow(row)
        self._sync_corner_inspector()
        self._refresh_model_catalog()
        self._refresh_model_corner_summary()
        self._refresh_run_plan()

    def _collect_model_table_directives(self) -> list[ModelDirective]:
        if not hasattr(self, "model_table"):
            return list(self._global_model_directives)
        directives: list[ModelDirective] = []
        for r in range(self.model_table.rowCount()):
            directive = self._model_directive_from_row(r)
            if directive.path:
                directives.append(directive)
        self._global_model_directives = directives
        return directives

    def _model_catalog_entries(self) -> list[ModelEntry]:
        directives = self._collect_model_table_directives() if hasattr(self, "model_table") else []
        return parse_model_entries(directives)

    def _refresh_model_catalog(self):
        if not hasattr(self, "model_catalog_table"):
            return
        entries = self._model_catalog_entries()
        query = self.model_catalog_filter_edit.text().strip().lower() if hasattr(self, "model_catalog_filter_edit") else ""
        if query:
            entries = [
                entry for entry in entries
                if query in " ".join([
                    entry.name,
                    entry.kind,
                    entry.device_type,
                    entry.section,
                    entry.path,
                    " ".join(entry.pins),
                ]).lower()
            ]
        table = self.model_catalog_table
        table.blockSignals(True)
        try:
            table.setRowCount(len(entries))
            for row, entry in enumerate(entries):
                details = entry.device_type or " ".join(entry.pins)
                values = [entry.name, entry.kind, details, entry.section, entry.path]
                for col, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    table.setItem(row, col, item)
            table.resizeColumnsToContents()
        finally:
            table.blockSignals(False)
        self._refresh_model_binding_model_choices()
        self._refresh_binding_statuses()

    def _schematic_model_instances(self) -> list[dict]:
        data = self.db.load_view(self.library, self.cell, "schematic") or {}
        rows = []
        for inst in data.get("instances", []):
            name = str(inst.get("name", "")).strip()
            if not name:
                continue
            params = inst.get("params", {}) or {}
            cell = str(inst.get("cell", "")).strip()
            if "model" not in params and cell.lower() not in {
                "nmos", "pmos", "nmos3", "pmos3", "diode", "zener",
                "bjt_npn", "bjt_pnp", "jfet_n", "jfet_p", "switch",
                "mos_bulk", "mos_depl", "spice_netlist", "subckt_file",
            }:
                continue
            model = str(params.get("model", "")).strip()
            rows.append({
                "instance": name,
                "device": f"{inst.get('library', '')}/{cell}".strip("/"),
                "model": model,
            })
        return rows

    def _populate_model_bindings_from_schematic(self):
        if not hasattr(self, "model_binding_table"):
            return
        existing = {
            self._table_text(self.model_binding_table, row, 1)
            for row in range(self.model_binding_table.rowCount())
        }
        for inst in self._schematic_model_instances():
            if inst["instance"] not in existing:
                self._add_model_binding_row(
                    inst["instance"],
                    inst["device"],
                    inst["model"],
                    "",
                    True,
                )
        self._collect_model_bindings()
        self._refresh_run_plan()
        self._save_simenv_view_silent()

    def _add_model_binding_row(self, instance: str, device: str, model: str, corner: str = "", enabled: bool = True):
        if not hasattr(self, "model_binding_table"):
            return
        table = self.model_binding_table
        row = table.rowCount()
        table.insertRow(row)
        chk = QCheckBox()
        chk.setChecked(bool(enabled))
        chk.stateChanged.connect(lambda _state: (self._collect_model_bindings(), self._refresh_run_plan()))
        table.setCellWidget(row, 0, chk)
        table.setItem(row, 1, QTableWidgetItem(str(instance or "")))
        table.setItem(row, 2, QTableWidgetItem(str(device or "")))
        model_combo = QComboBox()
        model_combo.setEditable(True)
        model_combo.currentTextChanged.connect(lambda _text: (self._collect_model_bindings(), self._refresh_binding_statuses(), self._refresh_run_plan()))
        table.setCellWidget(row, 3, model_combo)
        table.setItem(row, 4, QTableWidgetItem(str(corner or "")))
        self._refresh_model_binding_model_choices(row, model)

    def _collect_model_bindings(self) -> list[DeviceModelBinding]:
        if not hasattr(self, "model_binding_table"):
            return list(self._model_bindings)
        bindings: list[DeviceModelBinding] = []
        for row in range(self.model_binding_table.rowCount()):
            chk = self.model_binding_table.cellWidget(row, 0)
            model_widget = self.model_binding_table.cellWidget(row, 3)
            model = model_widget.currentText().strip() if isinstance(model_widget, QComboBox) else self._table_text(self.model_binding_table, row, 3)
            bindings.append(DeviceModelBinding(
                instance=self._table_text(self.model_binding_table, row, 1),
                device=self._table_text(self.model_binding_table, row, 2),
                model=model,
                corner=self._table_text(self.model_binding_table, row, 4),
                enabled=bool(chk.isChecked()) if isinstance(chk, QCheckBox) else True,
            ))
        self._model_bindings = bindings
        return bindings

    def _apply_selected_catalog_model_to_binding(self):
        if not hasattr(self, "model_catalog_table") or not hasattr(self, "model_binding_table"):
            return
        model_row = self.model_catalog_table.currentRow()
        bind_row = self.model_binding_table.currentRow()
        if model_row < 0 or bind_row < 0:
            self.statusBar().showMessage("Select one discovered model and one binding row", 5000)
            return
        model = self._table_text(self.model_catalog_table, model_row, 0)
        if model:
            model_widget = self.model_binding_table.cellWidget(bind_row, 3)
            if isinstance(model_widget, QComboBox):
                idx = model_widget.findText(model)
                if idx < 0:
                    model_widget.addItem(model)
                    idx = model_widget.findText(model)
                model_widget.setCurrentIndex(idx)
            else:
                self.model_binding_table.setItem(bind_row, 3, QTableWidgetItem(model))
            self._collect_model_bindings()
            self._refresh_binding_statuses()
            self._refresh_run_plan()
            self._save_simenv_view_silent()

    def _refresh_model_binding_model_choices(self, only_row: int | None = None, selected: str = ""):
        if not hasattr(self, "model_binding_table"):
            return
        names = sorted({entry.name for entry in self._model_catalog_entries()}, key=str.lower)
        rows = [only_row] if only_row is not None else list(range(self.model_binding_table.rowCount()))
        for row in rows:
            combo = self.model_binding_table.cellWidget(row, 3)
            if not isinstance(combo, QComboBox):
                continue
            current = str(selected or combo.currentText() or "").strip()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("")
            combo.addItems(names)
            if current:
                idx = combo.findText(current)
                if idx < 0:
                    combo.addItem(current)
                    idx = combo.findText(current)
                combo.setCurrentIndex(idx)
            combo.blockSignals(False)

    def _refresh_binding_statuses(self):
        if not hasattr(self, "model_binding_table"):
            return
        entries = self._model_catalog_entries()
        instance_names = {item["instance"] for item in self._schematic_model_instances()}
        errors = validate_model_bindings(self._collect_model_bindings(), entries, instance_names)
        by_text = "\n".join(errors)
        for row in range(self.model_binding_table.rowCount()):
            instance = self._table_text(self.model_binding_table, row, 1)
            model_widget = self.model_binding_table.cellWidget(row, 3)
            model = model_widget.currentText().strip() if isinstance(model_widget, QComboBox) else self._table_text(self.model_binding_table, row, 3)
            row_errors = [
                err for err in errors
                if (instance and instance in err) or (model and model in err)
            ]
            tooltip = "; ".join(row_errors) or by_text
            for col in range(self.model_binding_table.columnCount()):
                item = self.model_binding_table.item(row, col)
                if item:
                    item.setToolTip(tooltip)
                    if row_errors:
                        item.setBackground(QColor("#3a3117"))
                    else:
                        item.setBackground(QColor())

    def _remove_selected_model_bindings(self):
        if not hasattr(self, "model_binding_table"):
            return
        rows = sorted({idx.row() for idx in self.model_binding_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.model_binding_table.removeRow(row)
        self._collect_model_bindings()
        self._refresh_run_plan()
        self._save_simenv_view_silent()

    def _active_model_binding_map(self, corner: str = "") -> dict[str, str]:
        result: dict[str, str] = {}
        for binding in self._collect_model_bindings():
            if not binding.enabled or not binding.instance or not binding.model:
                continue
            bind_corner = str(binding.corner or "").strip()
            if bind_corner and corner and bind_corner != corner:
                continue
            if bind_corner and not corner:
                continue
            result[binding.instance] = binding.model
        return result

    def _populate_ihp_model_template(self):
        registry = self._ensure_pdk_registry()
        pdk_name = self._selected_pdk_name() or "ihp_sg13g2"
        if not registry:
            return
        pdk = registry.get_pdk(pdk_name)
        if not pdk or pdk.name != "ihp_sg13g2":
            self._log("IHP template is available only when IHP SG13G2 is selected or detected.")
            return
        wanted = [
            ("cornerMOSlv.lib", "mos_tt"),
            ("cornerMOShv.lib", "mos_tt"),
            ("cornerRES.lib", "res_typ"),
            ("cornerCAP.lib", "cap_typ"),
            ("cornerDIO.lib", "dio_tt"),
            ("cornerHBT.lib", "hbt_typ"),
        ]
        model_files = list(getattr(pdk, "model_files", []) or [])
        self.model_table.setRowCount(0)
        for filename, section in wanted:
            match = next((mf for mf in model_files if os.path.basename(mf.path) == filename and f"{os.sep}ngspice{os.sep}" in mf.path.lower()), None)
            match = match or next((mf for mf in model_files if os.path.basename(mf.path) == filename), None)
            if match:
                self._add_model_directive_row("lib", match.path, section)
        self._log("Loaded IHP SG13G2 shared model template.")

    def _load_selected_pdk_model_files(self):
        registry = self._ensure_pdk_registry()
        pdk_name = self._selected_pdk_name()
        if not pdk_name or not registry:
            self._log("Select a PDK before loading discovered model files.")
            return
        pdk = registry.get_pdk(pdk_name)
        model_files = list(getattr(pdk, "model_files", []) or []) if pdk else []
        if not model_files:
            self._log(f"No discovered model files for PDK: {pdk_name}")
            return
        self.model_table.setRowCount(0)
        for mf in model_files:
            suffix = os.path.splitext(mf.path)[1].lower()
            sections = list(getattr(mf, "corners", []) or [])
            if suffix == ".lib":
                self._add_model_directive_row("lib", mf.path, sections[0] if sections else "")
            elif suffix in (".scs", ".spice", ".sp", ".model"):
                self._add_model_directive_row("include", mf.path, "")
            elif suffix == ".gsdi":
                self._add_model_directive_row("gsdi", mf.path, "")
        self._log(f"Loaded {self.model_table.rowCount()} discovered model file(s) from {pdk_name}.")

    def _apply_selected_pdk_manifest(self, auto: bool = False) -> bool:
        registry = self._ensure_pdk_registry()
        pdk_name = self._selected_pdk_name()
        if not pdk_name or not registry:
            if not auto:
                self._log("Select a PDK before applying a PDK setup.")
            return False
        pdk = registry.get_pdk(pdk_name)
        manifest = build_pdk_model_manifest(pdk, self._current_simulator)
        if not manifest.model_directives and not manifest.corners:
            if not auto:
                self._log(f"No model manifest data found for PDK: {pdk_name}")
            return False

        self.model_table.blockSignals(True)
        try:
            self.model_table.setRowCount(0)
            for directive in manifest.model_directives:
                self._add_model_directive_row(directive.kind, directive.path, directive.section)
        finally:
            self.model_table.blockSignals(False)

        if manifest.corners:
            self.corner_table.blockSignals(True)
            try:
                self.corner_table.setRowCount(0)
                self._corner_model_directives.clear()
                for corner in manifest.corners:
                    row = self._add_corner(corner.name, corner.temp, corner.vdd, corner.process)
                    chk = self.corner_table.cellWidget(row, 4)
                    if isinstance(chk, QCheckBox):
                        chk.setChecked(corner.enabled)
                    if corner.model_directives:
                        self._corner_model_directives[corner.name] = list(corner.model_directives)
            finally:
                self.corner_table.blockSignals(False)
            idx = self.corner_mode_combo.findText("All Corners")
            if idx >= 0:
                self.corner_mode_combo.setCurrentIndex(idx)

        self._refresh_model_directive_statuses()
        self._refresh_model_catalog()
        self._refresh_corner_model_buttons()
        self._refresh_corner_setup_matrix()
        self._refresh_corner_run_matrix_preview()
        self._sync_corner_inspector()
        self._refresh_model_corner_summary()
        self._refresh_run_plan()
        self._save_simenv_view_silent()
        action = "Auto-applied attached PDK setup" if auto else "Applied PDK setup"
        self._log(f"{action}: {manifest.display_name or pdk_name} ({len(manifest.corners)} corner(s)).")
        self._refresh_pdk_model_overview()
        self._refresh_workflow_status()
        return True

    def _auto_apply_attached_pdk_setup(self) -> bool:
        try:
            pdk_name = self.db.get_library_pdk(self.library)
        except Exception:
            return False
        if not pdk_name or not hasattr(self, "pdk_combo"):
            self._update_pdk_badge()
            return False
        registry = self._ensure_pdk_registry()
        if not registry or not registry.get_pdk(pdk_name):
            self._update_pdk_badge()
            return False
        if self.model_table.rowCount() > 0 or self._corner_model_directives:
            self._update_pdk_badge()
            return False

        self._pending_simenv_pdk = pdk_name
        if self.pdk_combo.findData(pdk_name) < 0:
            pdk = registry.get_pdk(pdk_name)
            self.pdk_combo.addItem(getattr(pdk, "display_name", pdk_name), pdk_name)
        idx = self.pdk_combo.findData(pdk_name)
        if idx >= 0:
            self.pdk_combo.setCurrentIndex(idx)
        applied = self._apply_selected_pdk_manifest(auto=True)
        self._update_pdk_badge()
        return applied

    def _edit_corner_models(self, row: int):
        if row < 0 or row >= self.corner_table.rowCount():
            return
        name = self._table_text(self.corner_table, row, 0, f"corner_{row}")
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Corner Models - {name}")
        layout = QVBoxLayout(dlg)
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["Type", "Path", "Section"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table)

        def add_row(directive: ModelDirective | None = None):
            d = directive or ModelDirective("lib", "", "")
            r = table.rowCount()
            table.insertRow(r)
            kind_combo = QComboBox()
            kind_combo.addItems(["lib", "include", "gsdi"])
            idx = kind_combo.findText(d.kind)
            kind_combo.setCurrentIndex(idx if idx >= 0 else 0)
            table.setCellWidget(r, 0, kind_combo)
            table.setItem(r, 1, QTableWidgetItem(d.path))
            table.setItem(r, 2, QTableWidgetItem(d.section))

        for directive in self._corner_model_directives.get(name, []):
            add_row(directive)

        controls = QHBoxLayout()
        add_btn = QPushButton("+ Add")
        add_btn.clicked.connect(lambda: add_row())
        controls.addWidget(add_btn)
        inherit_btn = QPushButton("Use Shared")
        inherit_btn.clicked.connect(lambda: table.setRowCount(0))
        controls.addWidget(inherit_btn)
        ihp_btn = QPushButton("IHP For Process")
        ihp_btn.clicked.connect(lambda: self._populate_corner_table_with_ihp(table, self._table_text(self.corner_table, row, 3, "tt")))
        controls.addWidget(ihp_btn)
        controls.addStretch()
        layout.addLayout(controls)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        directives = []
        for r in range(table.rowCount()):
            kind_widget = table.cellWidget(r, 0)
            kind = kind_widget.currentText() if isinstance(kind_widget, QComboBox) else "lib"
            path = table.item(r, 1).text().strip() if table.item(r, 1) else ""
            section = table.item(r, 2).text().strip() if table.item(r, 2) else ""
            if path:
                directives.append(ModelDirective(kind, path, section))
        if directives:
            self._corner_model_directives[name] = directives
        else:
            self._corner_model_directives.pop(name, None)
        self._refresh_corner_model_buttons()
        self._sync_corner_inspector()
        self._refresh_run_plan()
        self._save_simenv_view_silent()

    def _populate_corner_table_with_ihp(self, table: QTableWidget, process: str):
        table.setRowCount(0)
        for directive in self._default_model_directives_for_process(process):
            r = table.rowCount()
            table.insertRow(r)
            kind_combo = QComboBox()
            kind_combo.addItems(["lib", "include", "gsdi"])
            kind_combo.setCurrentText(directive.kind)
            table.setCellWidget(r, 0, kind_combo)
            table.setItem(r, 1, QTableWidgetItem(directive.path))
            table.setItem(r, 2, QTableWidgetItem(directive.section))

    def _build_run_plan_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)

        top = QHBoxLayout()
        title = QLabel("Run Plan")
        title.setObjectName("adePanelTitle")
        top.addWidget(title)
        top.addStretch()
        refresh_btn = QPushButton("Refresh Plan")
        refresh_btn.clicked.connect(self._refresh_run_plan)
        top.addWidget(refresh_btn)
        layout.addLayout(top)

        self.run_plan_tree = QTreeWidget()
        self.run_plan_tree.setHeaderLabels(["Item", "Value"])
        self.run_plan_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.run_plan_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.run_plan_tree)

        hint = QLabel(
            "This tab summarizes the SimENV session before execution: tests, "
            "variables, corners, outputs, measurements, and simulator target."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#8c9aa8;background:transparent;padding:4px;")
        layout.addWidget(hint)

        self.main_tabs.addTab(widget, "Run Plan")
        self._refresh_run_plan()

    def _refresh_run_plan(self):
        if not hasattr(self, "run_plan_tree"):
            return

        self.run_plan_tree.clear()

        def add_parent(name: str, value: str = ""):
            item = QTreeWidgetItem([name, value])
            font = item.font(0)
            font.setBold(True)
            item.setFont(0, font)
            item.setForeground(0, QColor("#6b9ece"))
            self.run_plan_tree.addTopLevelItem(item)
            item.setExpanded(True)
            return item

        session = add_parent("Session", f"{self.library}/{self.cell}")
        session.addChild(QTreeWidgetItem(["Environment", "SimENV"]))
        session.addChild(QTreeWidgetItem(["Simulator", get_simulator_label(self._current_simulator)]))
        mach = self.machine_combo.currentData() if hasattr(self, "machine_combo") else "local"
        if mach == "remote":
            user = self.ssh_user_edit.text().strip() if hasattr(self, "ssh_user_edit") else ""
            host = self.ssh_host_edit.text().strip() if hasattr(self, "ssh_host_edit") else ""
            mach_str = f"Remote (SSH: {user}@{host})" if user and host else "Remote (SSH)"
        else:
            mach_str = "Local"
        session.addChild(QTreeWidgetItem(["Machine", mach_str]))
        session.addChild(QTreeWidgetItem(["Threads", str(self._sim_thread_count())]))
        session.addChild(QTreeWidgetItem(["Accuracy", self._sim_accuracy]))
        session.addChild(QTreeWidgetItem([
            "Tolerance Override",
            self._sim_tolerance_override or "Preset",
        ]))
        session.addChild(QTreeWidgetItem(["Method", self._sim_method]))
        session.addChild(QTreeWidgetItem(["Save", self._sim_save_mode_label()]))
        session.addChild(QTreeWidgetItem([
            "Auto MaxStep",
            "On" if self._sim_adaptive_maxstep else "Off",
        ]))
        session.addChild(QTreeWidgetItem([
            "Save Internal Points",
            "On" if self._sim_save_adaptive_points else "Off",
        ]))
        session.addChild(QTreeWidgetItem(["KLU", "On" if self._sim_prefer_klu else "Off"]))
        session.addChild(QTreeWidgetItem(["Compat Diagnostics", "On" if self._sim_verbose_compat else "Off"]))
        session.addChild(QTreeWidgetItem(["Dump Folder", self._resolved_sim_dump_dir()]))
        session.addChild(QTreeWidgetItem(["PDK", self._selected_pdk_name(infer=False) or "None selected"]))

        shared_models = self._collect_model_table_directives() if hasattr(self, "model_table") else []
        model_parent = add_parent("Model Setup", f"{self._model_setup_name}: {len(shared_models)} shared directive(s)")
        for directive in shared_models:
            model_parent.addChild(QTreeWidgetItem([directive.kind, directive.spice_line()]))
        validation_errors = self._model_validation_errors()
        validation_parent = add_parent("Validation", "PASS" if not validation_errors else f"{len(validation_errors)} issue(s)")
        for err in validation_errors[:12]:
            validation_parent.addChild(QTreeWidgetItem(["Model", err]))
        bindings = self._collect_model_bindings() if hasattr(self, "model_binding_table") else []
        binding_parent = add_parent("Device Bindings", f"{len([b for b in bindings if b.enabled])} enabled")
        for binding in bindings:
            if binding.enabled:
                suffix = f" @ {binding.corner}" if binding.corner else ""
                binding_parent.addChild(QTreeWidgetItem([binding.instance, f"{binding.model}{suffix}"]))

        tests = add_parent("Tests", f"{len(self._analysis_tabs)} analysis setup(s)")
        for name, widget in self._analysis_tabs.items():
            tests.addChild(QTreeWidgetItem([name, self._analysis_spice_line(name, widget)]))

        variables = self.var_widget.get_variables() if hasattr(self, "var_widget") else {}
        var_parent = add_parent("Variables", f"{len(variables)} variable(s)")
        for name, value in variables.items():
            var_parent.addChild(QTreeWidgetItem([name, value]))

        sweep_specs = self.sweep_widget.get_sweep_specs() if hasattr(self, "sweep_widget") else []
        try:
            sweep_count = len(self.sweep_widget.expanded_points()) if sweep_specs else 1
        except Exception:
            sweep_count = 0
        sweep_parent = add_parent("Variable Sweeps", f"{len(sweep_specs)} enabled, {sweep_count} run point(s)")
        for spec in sweep_specs:
            sweep_parent.addChild(QTreeWidgetItem([
                spec["variable"],
                f"{spec['start']} to {spec['stop']} step {spec['step']}",
            ]))

        corners = self.get_corner_data() if hasattr(self, "corner_table") else []
        corner_parent = add_parent("Corners", f"{len(corners)} enabled")
        for corner in corners:
            item = QTreeWidgetItem([
                corner["name"],
                f"{corner['process']}, {corner['temp']} C, VDD={corner['vdd']}",
            ])
            for directive in self._resolved_model_directives(
                corner.get("process", ""),
                corner.get("name", ""),
                self._selected_pdk_name(),
            ):
                item.addChild(QTreeWidgetItem(["Model", directive.spice_line()]))
            corner_parent.addChild(item)

        outputs = self._output_save_lines() if hasattr(self, "outputs_widget") else []
        output_parent = add_parent("Outputs", f"{len(outputs)} saved expression(s)")
        for line in outputs:
            output_parent.addChild(QTreeWidgetItem(["Save", line.replace(".SAVE ", "")]))

        measures = self.measurement_widget.get_measure_lines() if hasattr(self, "measurement_widget") else []
        measure_parent = add_parent("Measurements", f"{len(measures)} measurement(s)")
        for line in measures:
            measure_parent.addChild(QTreeWidgetItem(["Measure", line]))

        specs = self.spec_widget.get_specs() if hasattr(self, "spec_widget") else []
        spec_parent = add_parent("Specs", f"{len([s for s in specs if s.enabled])} enabled")
        for spec in specs:
            if not spec.enabled:
                continue
            limits = []
            if spec.min_value:
                limits.append(f">= {spec.min_value}")
            if spec.max_value:
                limits.append(f"<= {spec.max_value}")
            spec_parent.addChild(QTreeWidgetItem([spec.name, f"{spec.metric} {spec.expression} {' and '.join(limits)}".strip()]))

        for i in range(self.run_plan_tree.topLevelItemCount()):
            self.run_plan_tree.topLevelItem(i).setExpanded(True)
        self._refresh_workflow_status()

    def _model_validation_errors(self) -> list[str]:
        errors: list[str] = []
        pdk_name = self._selected_pdk_name()
        corners = self.get_corner_data() if hasattr(self, "corner_table") else []
        if not corners:
            directives = self._resolved_model_directives("", "", pdk_name)
            errors.extend(validate_model_directives(directives))
        else:
            for corner in corners:
                directives = self._resolved_model_directives(
                    corner.get("process", ""),
                    corner.get("name", ""),
                    pdk_name,
                )
                for err in validate_model_directives(directives):
                    errors.append(f"{corner.get('name', 'corner')}: {err}")
        entries = self._model_catalog_entries() if hasattr(self, "model_table") else []
        instance_names = {item["instance"] for item in self._schematic_model_instances()}
        errors.extend(validate_model_bindings(
            self._collect_model_bindings(),
            entries,
            instance_names,
        ))
        return errors

    def get_corner_data(self) -> list[dict]:
        """Get corner configuration data."""
        corners = []
        for r in range(self.corner_table.rowCount()):
            name_item = self.corner_table.item(r, 0)
            temp_item = self.corner_table.item(r, 1)
            vdd_item = self.corner_table.item(r, 2)
            proc_item = self.corner_table.item(r, 3)
            chk = self.corner_table.cellWidget(r, 4)

            if name_item and chk and chk.isChecked():
                corners.append({
                    "name": name_item.text().strip(),
                    "temp": temp_item.text().strip() if temp_item else "25",
                    "vdd": vdd_item.text().strip() if vdd_item else "1.8",
                    "process": proc_item.text().strip() if proc_item else "tt",
                })
        return corners

    def _build_results_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        lbl_view = QLabel("Corner / Variable Matrix:")
        lbl_view.setObjectName("adePanelLabel")
        toolbar.addWidget(lbl_view)

        self.btn_plot_all_results = QPushButton("📈 Plot Selected")
        self.btn_plot_all_results.setToolTip("Open SigView plot for selected result row")
        self.btn_plot_all_results.clicked.connect(self._on_results_plot_selected)
        toolbar.addWidget(self.btn_plot_all_results)

        self.btn_export_results_csv = QPushButton("💾 Export CSV")
        self.btn_export_results_csv.setToolTip("Export Corner Results Matrix to CSV")
        self.btn_export_results_csv.clicked.connect(self._export_corner_matrix_to_csv)
        toolbar.addWidget(self.btn_export_results_csv)

        toolbar.addWidget(QLabel("Filter:"))
        self.results_filter_edit = QLineEdit()
        self.results_filter_edit.setPlaceholderText("corner, sweep, status, signal...")
        self.results_filter_edit.textChanged.connect(lambda _text: self._apply_results_filter())
        toolbar.addWidget(self.results_filter_edit)

        toolbar.addWidget(QLabel("Sort:"))
        self.results_sort_combo = QComboBox()
        self.results_sort_combo.addItems(["Run", "Corner", "Status", "Signals", "Spec Margin", "Spec Value"])
        self.results_sort_combo.currentTextChanged.connect(lambda _text: self._sort_results_rows())
        toolbar.addWidget(self.results_sort_combo)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.corner_matrix_table = QTableWidget(0, 0)
        self.corner_matrix_table.verticalHeader().setVisible(True)
        self.corner_matrix_table.setMinimumHeight(180)
        self.corner_matrix_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.corner_matrix_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.corner_matrix_table.customContextMenuRequested.connect(self._on_corner_matrix_context_menu)
        self.corner_matrix_table.itemDoubleClicked.connect(self._select_corner_matrix_cell)
        matrix_header = self.corner_matrix_table.horizontalHeader()
        matrix_header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        matrix_header.customContextMenuRequested.connect(self._on_corner_matrix_header_menu)
        layout.addWidget(self.corner_matrix_table)

        self.results_table = QTableWidget(0, 7)
        self.results_table.setHorizontalHeaderLabels([
            "Corner / Run",
            "Process",
            "Temp",
            "VDD",
            "Analysis",
            "Measurements / Outputs",
            "Status"
        ])
        header = self.results_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Interactive)

        self.results_table.setColumnWidth(0, 140)
        self.results_table.setColumnWidth(1, 80)
        self.results_table.setColumnWidth(2, 70)
        self.results_table.setColumnWidth(3, 70)
        self.results_table.setColumnWidth(4, 130)
        self.results_table.setColumnWidth(6, 90)

        self.results_table.verticalHeader().setVisible(False)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.results_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results_table.customContextMenuRequested.connect(self._on_results_context_menu)
        self.results_table.itemDoubleClicked.connect(self._on_result_double_click)

        layout.addWidget(self.results_table)
        self.main_tabs.addTab(widget, "Results")

    def _refresh_corner_matrix(self):
        if not hasattr(self, "corner_matrix_table"):
            return
        corners = sorted({corner for corner, _sweep in self._corner_sweep_result_rows.keys()})
        if not corners:
            corners = sorted(self._corner_result_rows.keys())
        sweeps = sorted({sweep for _corner, sweep in self._corner_sweep_result_rows.keys()})
        if not sweeps and corners:
            sweeps = ["Single"]
        self.corner_matrix_table.setRowCount(len(sweeps))
        self.corner_matrix_table.setColumnCount(len(corners))
        self.corner_matrix_table.setHorizontalHeaderLabels(corners)
        self.corner_matrix_table.setVerticalHeaderLabels(sweeps)
        self.corner_matrix_table.clearContents()
        self.corner_matrix_table.setToolTip("Columns are corners. Rows are variable sweep points. Each cell summarizes matching run results.")
        for col, corner in enumerate(corners):
            for row_idx, sweep in enumerate(sweeps):
                rows = self._corner_sweep_result_rows.get((corner, sweep), [])
                ok = 0
                plottable = 0
                for result_row in rows:
                    item = self.results_table.item(result_row, 6)
                    if item and "PASS" in item.text():
                        ok += 1
                    if self._result_waveforms_by_row.get(result_row) or self._result_all_waveforms_by_row.get(result_row):
                        plottable += 1
                if rows:
                    text = f"{ok}/{len(rows)} PASS"
                    if plottable:
                        text += f"\n{plottable} plot"
                else:
                    text = "-"
                cell = QTableWidgetItem(text)
                cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                cell.setData(Qt.ItemDataRole.UserRole, {"corner": corner, "sweep": sweep, "rows": rows})
                if not rows:
                    cell.setForeground(QColor("#7f8c99"))
                elif ok == len(rows):
                    cell.setForeground(QColor("#74c69d"))
                    cell.setBackground(QColor("#173524"))
                elif ok:
                    cell.setForeground(QColor("#ffd166"))
                    cell.setBackground(QColor("#3a3117"))
                else:
                    cell.setForeground(QColor("#ff8fa3"))
                    cell.setBackground(QColor("#401820"))
                self.corner_matrix_table.setItem(row_idx, col, cell)
        self.corner_matrix_table.resizeColumnsToContents()
        self.corner_matrix_table.resizeRowsToContents()
        self._apply_results_filter()

    def _result_row_record(self, row: int) -> dict:
        waveforms = self._result_waveforms_by_row.get(row, {})
        all_waveforms = self._result_all_waveforms_by_row.get(row, {})
        run = self.results_table.item(row, 0).text() if self.results_table.item(row, 0) else ""
        corner = self._results_corner_from_run_name(run) or "Single"
        return {
            "values": [
                self.results_table.item(row, col).text() if self.results_table.item(row, col) else ""
                for col in range(self.results_table.columnCount())
            ],
            "waveforms": dict(waveforms or {}),
            "all_waveforms": dict(all_waveforms or {}),
            "specs": list(self._spec_results_by_row.get(row, [])),
            "corner": corner,
            "sweep": self._results_sweep_from_run_name(run, corner),
            "signal_count": self._count_plottable_signals(all_waveforms or waveforms),
            "spec_margin": self._worst_spec_margin(row),
            "spec_value": self._first_spec_value(row),
        }

    def _first_spec_value(self, row: int) -> float:
        for result in self._spec_results_by_row.get(row, []):
            value = result.get("value")
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                return float(value)
        return math.inf

    def _worst_spec_margin(self, row: int) -> float:
        margins: list[float] = []
        for result in self._spec_results_by_row.get(row, []):
            value = result.get("value")
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                continue
            min_val = result.get("min")
            max_val = result.get("max")
            if isinstance(min_val, (int, float)):
                margins.append(float(value) - float(min_val))
            if isinstance(max_val, (int, float)):
                margins.append(float(max_val) - float(value))
        return min(margins) if margins else math.inf

    def _sort_results_rows(self):
        if not hasattr(self, "results_table") or self.results_table.rowCount() <= 1:
            return
        records = [
            self._result_row_record(row)
            for row in range(self.results_table.rowCount())
            if row not in self._result_section_rows
        ]
        key_name = self.results_sort_combo.currentText() if hasattr(self, "results_sort_combo") else "Run"
        if key_name == "Corner":
            records.sort(key=lambda item: (item["corner"].lower(), item["sweep"].lower(), item["values"][0].lower()))
        elif key_name == "Status":
            records.sort(key=lambda item: (0 if "FAIL" in item["values"][6] else 1, item["corner"].lower(), item["values"][0].lower()))
        elif key_name == "Signals":
            records.sort(key=lambda item: (-int(item["signal_count"]), item["values"][0].lower()))
        elif key_name == "Spec Margin":
            records.sort(key=lambda item: (float(item["spec_margin"]), item["values"][0].lower()))
        elif key_name == "Spec Value":
            records.sort(key=lambda item: (float(item["spec_value"]), item["values"][0].lower()))
        else:
            records.sort(key=lambda item: item["values"][0].lower())

        self.results_table.blockSignals(True)
        self.results_table.setRowCount(0)
        self._result_section_rows.clear()
        self._result_section_corners.clear()
        self._corner_result_rows.clear()
        self._corner_sweep_result_rows.clear()
        self._result_waveforms_by_row.clear()
        self._result_all_waveforms_by_row.clear()
        self._spec_results_by_row.clear()
        for record in records:
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)
            for col, value in enumerate(record["values"]):
                item = QTableWidgetItem(value)
                if col == 6:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if "PASS" in value:
                        item.setForeground(QColor("#74c69d"))
                        item.setBackground(QColor("#1b4332"))
                    else:
                        item.setForeground(QColor("#ff8fa3"))
                        item.setBackground(QColor("#4a0e17"))
                self.results_table.setItem(row, col, item)
            if record["waveforms"]:
                self._result_waveforms_by_row[row] = record["waveforms"]
            if record["all_waveforms"]:
                self._result_all_waveforms_by_row[row] = record["all_waveforms"]
            if record["specs"]:
                self._spec_results_by_row[row] = record["specs"]
            self._corner_result_rows.setdefault(record["corner"], []).append(row)
            self._corner_sweep_result_rows.setdefault((record["corner"], record["sweep"]), []).append(row)
        self.results_table.blockSignals(False)
        self._refresh_corner_matrix()
        self._refresh_results_baseline_markers()
        self._apply_results_filter()

    def _set_result_baseline(self, run_name: str) -> None:
        self._baseline_run_name = str(run_name or "").strip()
        self._refresh_results_baseline_markers()
        self._save_simenv_view_silent()
        if self._baseline_run_name:
            self.statusBar().showMessage(f"Baseline set: {self._baseline_run_name}", 4000)

    def _clear_result_baseline(self) -> None:
        self._baseline_run_name = ""
        self._refresh_results_baseline_markers()
        self._save_simenv_view_silent()
        self.statusBar().showMessage("Baseline cleared", 3000)

    def _refresh_results_baseline_markers(self) -> None:
        if not hasattr(self, "results_table"):
            return
        baseline = str(self._baseline_run_name or "").strip()
        for row in range(self.results_table.rowCount()):
            if row in self._result_section_rows:
                continue
            item = self.results_table.item(row, 0)
            if not item:
                continue
            if baseline and item.text().strip() == baseline:
                item.setToolTip("Baseline run")
                item.setBackground(QColor("#453d1b"))
                item.setForeground(QColor("#ffd166"))
            else:
                item.setToolTip("")
                item.setBackground(QColor())
                item.setForeground(QColor())

    def _apply_results_filter(self):
        if not hasattr(self, "results_table"):
            return
        query = self.results_filter_edit.text().strip().lower() if hasattr(self, "results_filter_edit") else ""
        for row in range(self.results_table.rowCount()):
            if not query:
                self.results_table.setRowHidden(row, False)
                continue
            parts = [
                self.results_table.item(row, col).text() if self.results_table.item(row, col) else ""
                for col in range(self.results_table.columnCount())
            ]
            waveforms = self._result_all_waveforms_by_row.get(row) or self._result_waveforms_by_row.get(row, {})
            parts.extend(str(name) for name in waveforms.keys())
            self.results_table.setRowHidden(row, query not in " ".join(parts).lower())

    def _corner_matrix_value(self, corner: str, result_col: int) -> str:
        rows = self._corner_result_rows.get(corner, [])
        if rows:
            item = self.results_table.item(rows[-1], result_col)
            return item.text() if item else ""
        return ""

    def _corner_from_matrix_pos(self, pos) -> str:
        if not hasattr(self, "corner_matrix_table"):
            return ""
        col = self.corner_matrix_table.columnAt(pos.x())
        if col < 0:
            col = self.corner_matrix_table.currentColumn()
        item = self.corner_matrix_table.horizontalHeaderItem(col) if col >= 0 else None
        return item.text() if item else ""

    def _on_corner_matrix_header_menu(self, pos):
        col = self.corner_matrix_table.horizontalHeader().logicalIndexAt(pos)
        item = self.corner_matrix_table.horizontalHeaderItem(col) if col >= 0 else None
        self._show_corner_matrix_menu(item.text() if item else "", pos, on_header=True)

    def _on_corner_matrix_context_menu(self, pos):
        item = self.corner_matrix_table.item(
            self.corner_matrix_table.rowAt(pos.y()),
            self.corner_matrix_table.columnAt(pos.x()),
        )
        data = item.data(Qt.ItemDataRole.UserRole) if item else {}
        self._show_corner_matrix_menu(
            self._corner_from_matrix_pos(pos),
            pos,
            on_header=False,
            cell_data=data if isinstance(data, dict) else {},
        )

    def _show_corner_matrix_menu(self, corner: str, pos, on_header: bool, cell_data: dict | None = None):
        if not corner:
            return
        cell_data = cell_data or {}
        rows = list(cell_data.get("rows", []) or self._corner_result_rows.get(corner, []))
        sweep = str(cell_data.get("sweep", "") or "").strip()
        menu = QMenu(self)
        title_text = f"Cell: {corner} / {sweep}" if sweep else f"Corner: {corner}"
        title = QAction(title_text, self)
        title.setEnabled(False)
        menu.addAction(title)
        menu.addSeparator()

        if not on_header and sweep:
            act_run_cell = QAction("Run This Cell", self)
            act_run_cell.triggered.connect(lambda: self._run_matrix_cell(corner, sweep))
            menu.addAction(act_run_cell)

            act_select_cell = QAction("Select Cell Runs", self)
            act_select_cell.setEnabled(bool(rows))
            act_select_cell.triggered.connect(lambda: self._select_result_rows(rows))
            menu.addAction(act_select_cell)

            act_plot_cell = QAction("Plot Cell", self)
            act_plot_cell.setEnabled(any(self._result_waveforms_by_row.get(r) or self._result_all_waveforms_by_row.get(r) for r in rows))
            act_plot_cell.triggered.connect(lambda: self._plot_result_rows(rows))
            menu.addAction(act_plot_cell)
            menu.addSeparator()

        act_main = QAction("Main Form...", self)
        act_main.setEnabled(bool(rows))
        act_main.triggered.connect(lambda: self._show_corner_main_form(corner))
        menu.addAction(act_main)

        act_plot = QAction("Plot All", self)
        act_plot.setEnabled(any(self._result_waveforms_by_row.get(r) or self._result_all_waveforms_by_row.get(r) for r in rows))
        act_plot.triggered.connect(lambda: self._plot_corner_results(corner))
        menu.addAction(act_plot)

        act_plot_outputs = QAction("Plot Selected Outputs", self)
        act_plot_outputs.setEnabled(any(self._result_waveforms_by_row.get(r) for r in rows))
        act_plot_outputs.triggered.connect(lambda: self._plot_corner_results(corner, selected_only=True))
        menu.addAction(act_plot_outputs)

        signal_menu = menu.addMenu("Plot Signal")
        signals = self._corner_signal_names(corner)
        signal_menu.setEnabled(bool(signals))
        for signal in signals[:80]:
            action = QAction(signal, self)
            action.triggered.connect(lambda _checked=False, sig=signal: self._plot_corner_results(corner, signals=[sig]))
            signal_menu.addAction(action)
        if len(signals) > 80:
            more = QAction(f"... {len(signals) - 80} more signal(s)", self)
            more.setEnabled(False)
            signal_menu.addAction(more)

        act_select = QAction("Select Runs", self)
        act_select.setEnabled(bool(rows))
        act_select.triggered.connect(lambda: self._select_corner_result_rows(corner))
        menu.addAction(act_select)

        menu.addSeparator()
        act_export = QAction("Export Corner Matrix CSV...", self)
        act_export.triggered.connect(self._export_corner_matrix_to_csv)
        menu.addAction(act_export)

        widget = self.corner_matrix_table.horizontalHeader() if on_header else self.corner_matrix_table.viewport()
        menu.exec(widget.mapToGlobal(pos))

    def _run_matrix_cell(self, corner: str, sweep: str):
        key = (str(corner or "Single").strip() or "Single", str(sweep or "Single").strip() or "Single")
        self._disabled_run_cells.discard(key)
        self._run_selected_cells_once = {key}
        self._on_run()

    def _select_corner_result_rows(self, corner: str):
        rows = self._corner_result_rows.get(corner, [])
        if not rows:
            return
        self._select_result_rows(rows)

    def _select_result_rows(self, rows: list[int]):
        if not rows:
            return
        self.results_table.clearSelection()
        for row in rows:
            self.results_table.selectRow(row)
        self.results_table.scrollToItem(self.results_table.item(rows[0], 0))

    def _select_corner_matrix_cell(self, item: QTableWidgetItem):
        data = item.data(Qt.ItemDataRole.UserRole) if item else {}
        rows = data.get("rows", []) if isinstance(data, dict) else []
        self._select_result_rows(rows)

    def _plot_result_rows(self, rows: list[int]):
        merged: dict = {}
        for row in rows:
            waveforms = self._result_all_waveforms_by_row.get(row) or self._result_waveforms_by_row.get(row, {})
            if waveforms:
                run = self.results_table.item(row, 0).text() if self.results_table.item(row, 0) else f"run_{row}"
                self._merge_corner_waveforms(merged, run, waveforms)
        if not merged:
            self.statusBar().showMessage("No plottable waveforms for selected matrix cell", 5000)
            return
        self._last_sigview_waveforms = dict(merged)
        self._show_waveforms(self._sigview_payload_for_waveforms(merged))

    def _corner_signal_names(self, corner: str) -> list[str]:
        names: set[str] = set()
        for row in self._corner_result_rows.get(corner, []):
            waveforms = self._result_all_waveforms_by_row.get(row) or self._result_waveforms_by_row.get(row, {})
            names.update(self._plottable_signal_names(waveforms))
        return sorted(names, key=lambda s: s.lower())

    def _plot_corner_results(self, corner: str, selected_only: bool = False, signals: list[str] | None = None):
        merged: dict = {}
        for row in self._corner_result_rows.get(corner, []):
            waveforms = self._result_waveforms_by_row.get(row, {}) if selected_only else (
                self._result_all_waveforms_by_row.get(row) or self._result_waveforms_by_row.get(row, {})
            )
            if signals:
                waveforms = self._waveforms_for_signals(waveforms, signals)
            if waveforms:
                run = self.results_table.item(row, 0).text() if self.results_table.item(row, 0) else corner
                self._merge_corner_waveforms(merged, run, waveforms)
        if not merged:
            self.statusBar().showMessage(f"No plottable waveforms for {corner}", 5000)
            return
        self._last_sigview_waveforms = dict(merged)
        self._show_waveforms(self._sigview_payload_for_waveforms(merged))
        self.statusBar().showMessage(f"Plotted all waveforms for {corner}", 4000)

    def _show_corner_main_form(self, corner: str):
        rows = self._corner_result_rows.get(corner, [])
        if not rows:
            self.statusBar().showMessage(f"No result rows for {corner}", 5000)
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Corner Main Form - {corner}")
        dlg.resize(760, 420)
        layout = QVBoxLayout(dlg)
        title = QLabel(self._results_corner_section_title(corner))
        title.setObjectName("adePanelTitle")
        layout.addWidget(title)
        table = QTableWidget(len(rows), 5)
        table.setHorizontalHeaderLabels(["Run", "Analysis", "Measurements / Outputs", "Status", "Signals"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        for idx, row in enumerate(rows):
            waveforms = self._result_all_waveforms_by_row.get(row) or self._result_waveforms_by_row.get(row, {})
            values = [
                self.results_table.item(row, 0).text() if self.results_table.item(row, 0) else "",
                self.results_table.item(row, 4).text() if self.results_table.item(row, 4) else "",
                self.results_table.item(row, 5).text() if self.results_table.item(row, 5) else "",
                self.results_table.item(row, 6).text() if self.results_table.item(row, 6) else "",
                str(len(self._plottable_signal_names(waveforms))),
            ]
            for col, value in enumerate(values):
                table.setItem(idx, col, QTableWidgetItem(value))
        layout.addWidget(table)
        buttons = QHBoxLayout()
        plot = QPushButton("Plot All")
        plot.clicked.connect(lambda _checked=False: self._plot_corner_results(corner))
        buttons.addWidget(plot)
        select = QPushButton("Select Runs")
        select.clicked.connect(lambda _checked=False: self._select_corner_result_rows(corner))
        buttons.addWidget(select)
        close = QPushButton("Close")
        close.clicked.connect(dlg.accept)
        buttons.addWidget(close)
        buttons.addStretch()
        layout.addLayout(buttons)
        dlg.exec()

    def _show_results_tab(self):
        if not hasattr(self, "main_tabs"):
            return
        for idx in range(self.main_tabs.count()):
            if self.main_tabs.tabText(idx) == "Results":
                self.main_tabs.setCurrentIndex(idx)
                return

    def _export_results_to_csv(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Export Corner Results Matrix", "", "CSV Files (*.csv);;All Files (*)")
        if not filename:
            return
        self._export_results_rows_to_csv(filename)

    def _export_results_rows_to_csv(self, filename: str):
        try:
            with open(filename, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["Run", "Process", "Temp", "VDD", "Analysis", "Measurements / Outputs", "Status"])
                for r in range(self.results_table.rowCount()):
                    if r in self._result_section_rows:
                        item = self.results_table.item(r, 0)
                        writer.writerow([item.text() if item else "Corner Header"])
                        continue
                    row_data = []
                    for c in range(7):
                        item = self.results_table.item(r, c)
                        row_data.append(item.text() if item else "")
                    writer.writerow(row_data)
            self.statusBar().showMessage(f"Exported Corner Matrix to {filename}", 5000)
        except Exception as exc:
            QMessageBox.critical(self, "Export CSV", f"Could not export CSV:\n{exc}")

    def _export_corner_matrix_to_csv(self, filename: str = ""):
        if not filename:
            filename, _ = QFileDialog.getSaveFileName(self, "Export Corner Matrix", "", "CSV Files (*.csv);;All Files (*)")
            if not filename:
                return
        try:
            headers = ["Variable Sweep"] + [self.corner_matrix_table.horizontalHeaderItem(c).text() for c in range(self.corner_matrix_table.columnCount())]
            with open(filename, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(headers)
                for r in range(self.corner_matrix_table.rowCount()):
                    row_name = self.corner_matrix_table.verticalHeaderItem(r).text()
                    writer.writerow([row_name] + [
                        self.corner_matrix_table.item(r, c).text() if self.corner_matrix_table.item(r, c) else ""
                        for c in range(self.corner_matrix_table.columnCount())
                    ])
            self.statusBar().showMessage(f"Exported Corner Matrix to {filename}", 5000)
        except Exception as exc:
            QMessageBox.critical(self, "Export Corner Matrix", f"Could not export CSV:\n{exc}")

    def _export_spec_report_to_csv(self, filename: str = ""):
        if not filename:
            filename, _ = QFileDialog.getSaveFileName(self, "Export Spec Report", "", "CSV Files (*.csv);;All Files (*)")
            if not filename:
                return
        try:
            with open(filename, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["Run", "Corner", "Spec", "Expression", "Metric", "Value", "Min", "Max", "Passed"])
                for row, results in sorted(self._spec_results_by_row.items()):
                    run = self.results_table.item(row, 0).text() if self.results_table.item(row, 0) else ""
                    corner = self._results_corner_from_run_name(run) or "Single"
                    for result in results:
                        writer.writerow([
                            run,
                            corner,
                            result.get("name", ""),
                            result.get("expression", ""),
                            result.get("metric", ""),
                            result.get("value", ""),
                            result.get("min", ""),
                            result.get("max", ""),
                            "PASS" if result.get("passed") else "FAIL",
                        ])
            self.statusBar().showMessage(f"Exported Spec Report to {filename}", 5000)
        except Exception as exc:
            QMessageBox.critical(self, "Export Spec Report", f"Could not export CSV:\n{exc}")

    def _output_save_lines(self) -> list[str]:
        mode = str(self._sim_save_mode or "all").lower()
        if mode == "none":
            return []
        if mode == "all":
            lines = [".SAVE ALL"]
            if hasattr(self, "outputs_widget"):
                for spec in self._checked_output_specs():
                    expr = str(spec.get("expression", "")).strip()
                    if re.match(r"(?i)^I\([^)]*\)$", expr):
                        lines.append(f".SAVE {expr}")
            return lines
        return self.outputs_widget.get_save_lines() if hasattr(self, "outputs_widget") else []

    def _on_analysis_dblclick(self, item, col):
        name = item.data(0, Qt.ItemDataRole.UserRole)
        if name:
            self._add_analysis(name)

    def _add_selected_analysis(self):
        item = self.analysis_tree.currentItem()
        if item:
            name = item.data(0, Qt.ItemDataRole.UserRole)
            if name:
                self._add_analysis(name)

    def _selected_analysis_name(self) -> str:
        item = self.analysis_tree.currentItem()
        if item is None:
            return ""
        name = item.data(0, Qt.ItemDataRole.UserRole)
        return str(name or "")

    def _ensure_selected_analysis_for_run(self) -> bool:
        """Treat a selected analysis tree item as the intended run test."""
        if self._analysis_tabs:
            return True
        name = self._selected_analysis_name()
        if name and name in ANALYSES:
            self._add_analysis(name)
            self._log(f"Using selected test for run: {name}")
            return True
        return False

    def _analysis_validation_errors(self) -> list[str]:
        errors: list[str] = []
        for name, widget in self._analysis_tabs.items():
            for message in widget.validation_errors():
                errors.append(f"{name}: {message}")
        if hasattr(self, "sweep_widget"):
            for message in self.sweep_widget.validation_errors():
                errors.append(f"Variable Sweep: {message}")
        return errors

    def _add_analysis(self, name: str):
        if name in self._analysis_tabs:
            # Focus existing tab
            self._show_analysis_setup(name)
            return
        widget = AnalysisSetupWidget(name)
        self._connect_analysis_widget(widget)
        self._analysis_tabs[name] = widget
        self.analysis_setup_tabs.addTab(widget, name)
        self.analysis_setup_tabs.setCurrentWidget(widget)
        self._show_main_tab("Analyses")
        self._log(f"Added test: {name}")
        self._refresh_run_plan()

    def _connect_analysis_widget(self, widget: AnalysisSetupWidget):
        def changed():
            self._refresh_run_plan()
            self._save_simenv_view_silent()
        widget.pick_output_requested.connect(lambda field: self._start_schematic_output_pick("voltage", field))
        for field in getattr(widget, "_fields", {}).values():
            if isinstance(field, QCheckBox):
                field.stateChanged.connect(lambda _state, fn=changed: fn())
            elif isinstance(field, QComboBox):
                field.currentTextChanged.connect(lambda _text, fn=changed: fn())
            elif isinstance(field, QLineEdit):
                field.editingFinished.connect(changed)

    def _remove_analysis(self, name: str):
        if name not in self._analysis_tabs:
            return
        for i in range(self.analysis_setup_tabs.count()):
            if self.analysis_setup_tabs.tabText(i) == name:
                self.analysis_setup_tabs.removeTab(i)
                break
        self._analysis_tabs.pop(name, None)
        self._log(f"Disabled test: {name}")
        self._refresh_run_plan()

    def _show_analysis_setup(self, name: str):
        for i in range(self.analysis_setup_tabs.count()):
            if self.analysis_setup_tabs.tabText(i) == name:
                self.analysis_setup_tabs.setCurrentIndex(i)
                for idx in range(self.main_tabs.count()):
                    if self.main_tabs.tabText(idx) == "Analyses":
                        self.main_tabs.setCurrentIndex(idx)
                        break
                return

    def _show_main_tab(self, name: str):
        for idx in range(self.main_tabs.count()):
            if self.main_tabs.tabText(idx) == name:
                self.main_tabs.setCurrentIndex(idx)
                break

    # ── Menus & Toolbar ───────────────────────────────────────

    def _create_menus(self):
        menubar = self.menuBar()
        menubar.clear()
        session_menu = menubar.addMenu("&Session")
        act_save_view = QAction("Save State", self)
        act_save_view.setShortcut(QKeySequence("Ctrl+S"))
        act_save_view.triggered.connect(self._on_save_view)
        session_menu.addAction(act_save_view)

        act_save = QAction("Save State As...", self)
        act_save.triggered.connect(self._on_save_setup)
        session_menu.addAction(act_save)

        act_load = QAction("Load State...", self)
        act_load.triggered.connect(self._on_load_setup)
        session_menu.addAction(act_load)
        session_menu.addSeparator()
        act_save_preset = QAction("Save Named Preset...", self)
        act_save_preset.triggered.connect(self._on_save_named_preset)
        session_menu.addAction(act_save_preset)
        act_load_preset = QAction("Load Named Preset...", self)
        act_load_preset.triggered.connect(self._on_load_named_preset)
        session_menu.addAction(act_load_preset)
        session_menu.addSeparator()
        act_close = QAction("Close", self)
        act_close.triggered.connect(self.close)
        session_menu.addAction(act_close)

        setup_menu = menubar.addMenu("&Setup")
        for title, tab_name in (
            ("Variables...", "Setup"),
            ("Outputs...", "Setup"),
            ("Measurements...", "Setup"),
            ("Stimuli...", "Setup"),
            ("Convergence Aids...", "Setup"),
            ("Corners...", "Corners"),
        ):
            action = QAction(title, self)
            action.triggered.connect(lambda _checked=False, name=tab_name: self._show_main_tab(name))
            setup_menu.addAction(action)

        analyses_menu = menubar.addMenu("&Analyses")
        act_choose = QAction("Choose...", self)
        act_choose.triggered.connect(lambda: self._show_main_tab("Analyses"))
        analyses_menu.addAction(act_choose)
        analyses_menu.addSeparator()
        categories: dict[str, QMenu] = {}
        for name, info in ANALYSES.items():
            category = info["category"]
            menu = categories.get(category)
            if menu is None:
                menu = analyses_menu.addMenu(category)
                categories[category] = menu
            action = QAction(name, self)
            action.triggered.connect(lambda _checked=False, analysis=name: self._add_analysis(analysis))
            menu.addAction(action)

        simulation_menu = menubar.addMenu("&Simulation")
        act_run = QAction("Netlist and Run", self)
        act_run.setShortcut("F5")
        act_run.triggered.connect(self._on_run)
        simulation_menu.addAction(act_run)

        act_stop = QAction("Stop", self)
        act_stop.triggered.connect(self._on_stop_simulation)
        simulation_menu.addAction(act_stop)

        act_netlist = QAction("Create Netlist", self)
        act_netlist.triggered.connect(self._on_view_netlist)
        simulation_menu.addAction(act_netlist)
        simulation_menu.addSeparator()
        act_dump = QAction("Simulation Dump Settings...", self)
        act_dump.triggered.connect(self._on_set_sim_dump_dir)
        simulation_menu.addAction(act_dump)
        act_open_dump = QAction("Open Dump Folder", self)
        act_open_dump.triggered.connect(self._on_open_sim_dump_dir)
        simulation_menu.addAction(act_open_dump)

        results_menu = menubar.addMenu("&Results")
        act_results = QAction("Results Browser...", self)
        act_results.triggered.connect(lambda: self._show_main_tab("Results"))
        results_menu.addAction(act_results)
        act_sigview = QAction("Direct Plot...", self)
        act_sigview.triggered.connect(self._on_open_waveform)
        results_menu.addAction(act_sigview)
        act_calc = QAction("Calculator...", self)
        act_calc.triggered.connect(self._on_open_waveform_calculator)
        results_menu.addAction(act_calc)
        act_export = QAction("Export Corner Matrix CSV...", self)
        act_export.triggered.connect(self._export_corner_matrix_to_csv)
        results_menu.addAction(act_export)
        act_spec_export = QAction("Export Spec Report CSV...", self)
        act_spec_export.triggered.connect(self._export_spec_report_to_csv)
        results_menu.addAction(act_spec_export)
        act_compare = QAction("Compare Selected Runs...", self)
        act_compare.triggered.connect(self._compare_selected_result_runs)
        results_menu.addAction(act_compare)

        tools_menu = menubar.addMenu("&Tools")
        act_sim_mgr = QAction("Simulator Manager...", self)
        act_sim_mgr.triggered.connect(self._on_open_simulator_manager)
        tools_menu.addAction(act_sim_mgr)

        window_menu = menubar.addMenu("&Window")
        for tab_name in ("Setup", "Analyses", "Corners", "Run Plan", "Results"):
            action = QAction(tab_name, self)
            action.triggered.connect(lambda _checked=False, name=tab_name: self._show_main_tab(name))
            window_menu.addAction(action)

    def _create_toolbar(self):
        tb = QToolBar("SimENV")
        tb.setIconSize(QSize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        tb.setMovable(False)
        tb.setFloatable(False)

        def set_toolbar_emoji(action: QAction, emoji: str):
            label = action.text()
            action.setIconText(emoji)
            action.setToolTip(label)
            action.setStatusTip(label)
            button = tb.widgetForAction(action)
            if button is not None:
                button.setText(emoji)
                button.setToolTip(label)
                font = button.font()
                font.setPointSize(18)
                button.setFont(font)
                button.setMinimumSize(34, 30)

        act_save = QAction("Save", self)
        act_save.setIcon(QIcon())
        act_save.setToolTip("Save SimENV view")
        act_save.triggered.connect(self._on_save_view)
        tb.addAction(act_save)
        set_toolbar_emoji(act_save, "💾")

        tb.addSeparator()

        act_run = QAction("Run Plan", self)
        act_run.setIcon(QIcon())
        act_run.triggered.connect(self._on_run)
        tb.addAction(act_run)
        set_toolbar_emoji(act_run, "▶")

        self.act_stop_sim = QAction("Stop", self)
        self.act_stop_sim.setIcon(QIcon())
        self.act_stop_sim.setToolTip("Stop the running simulation")
        self.act_stop_sim.setEnabled(False)
        self.act_stop_sim.triggered.connect(self._on_stop_simulation)
        tb.addAction(self.act_stop_sim)
        set_toolbar_emoji(self.act_stop_sim, "■")

        act_netlist = QAction("Netlist", self)
        act_netlist.setIcon(QIcon())
        act_netlist.triggered.connect(self._on_view_netlist)
        tb.addAction(act_netlist)
        set_toolbar_emoji(act_netlist, "📄")

        act_wave = QAction("SigView", self)
        act_wave.setIcon(QIcon())
        act_wave.triggered.connect(self._on_open_waveform)
        tb.addAction(act_wave)
        set_toolbar_emoji(act_wave, "📈")

        act_calc = QAction("Calculator", self)
        act_calc.setIcon(QIcon())
        act_calc.setToolTip("Open latest waveforms in SigView calculator")
        act_calc.triggered.connect(self._on_open_waveform_calculator)
        tb.addAction(act_calc)
        set_toolbar_emoji(act_calc, "∑")

        tb.addSeparator()
        tb.addWidget(QLabel(" Sim: "))
        self.toolbar_sim_label = QLabel(self._current_simulator)
        self.toolbar_sim_label.setStyleSheet("color:#6b9ece;font-weight:bold;background:transparent;padding:0 4px;")
        tb.addWidget(self.toolbar_sim_label)

        self.addToolBar(tb)

    def _create_status_bar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.status_label = QLabel(f"{self.library}/{self.cell}")
        self.status_label.setStyleSheet("color:#ffffff;padding:0 8px;")
        sb.addWidget(self.status_label)

    # ── Netlist Generation ────────────────────────────────────

    def _build_full_netlist(self, variable_overrides: dict[str, str] | None = None) -> str:
        gen = NetlistGenerator(self.db)
        gen.set_target_simulator(self._current_simulator)

        # Configure directives from SimENV
        directives = NetlistDirectives()
        corner_data = self.get_corner_data()
        gen.set_model_bindings(self._active_model_binding_map(corner_data[0]["name"] if corner_data else ""))
        process = corner_data[0]["process"] if corner_data else ""
        self._configure_pdk_model_directives(
            directives,
            self._selected_pdk_name(),
            process,
            corner_data[0]["name"] if corner_data else "",
        )

        # Design variables as .PARAM
        variables = self.var_widget.get_variables()
        if variables:
            directives.params.update(variables)
        if variable_overrides:
            directives.params.update(variable_overrides)

        # Measurements
        directives.measures = self.measurement_widget.get_measure_lines()

        # Convergence helpers
        directives.nodesets = self.convergence_widget.get_nodeset_lines()
        directives.ics = self.convergence_widget.get_ic_lines()

        gen._directives = directives

        # Generate base netlist
        base = gen.generate(self.library, self.cell)

        # Remove .END and append analyses
        lines = base.rstrip().split("\n")
        while lines and (lines[-1].strip() == ".END" or lines[-1].strip() == ""):
            lines.pop()

        # Stimulus definitions
        stimulus_lines = self.stimulus_widget.get_stimulus_lines()
        if stimulus_lines:
            lines.append("")
            lines.append("* Stimulus")
            lines.extend(stimulus_lines)

        lines.append("")
        lines.append(f"* Accuracy: {self._sim_accuracy}")
        lines.append(self._accuracy_options_line())

        # Analyses
        for name, widget in self._analysis_tabs.items():
            lines.append("")
            lines.append(f"* Analysis: {name}")
            lines.append(self._analysis_spice_line(name, widget))

        # Parametric sweeps
        sweep_lines = self.sweep_widget.get_sweep_lines()
        if sweep_lines:
            lines.append("")
            lines.append("* Parametric Sweeps")
            lines.extend(sweep_lines)

        # Outputs
        save_lines = self._output_save_lines()
        if save_lines:
            lines.append("")
            lines.append("* Outputs")
            lines.extend(save_lines)

        # Output expressions
        expr_lines = self.outputs_widget.get_expression_lines()
        if expr_lines:
            lines.append("")
            lines.append("* Output Expressions")
            lines.extend(expr_lines)

        lines.append("")
        lines.append(".END")
        lines.append("")
        return "\n".join(lines)

    def _build_corner_netlists(self, variable_overrides: dict[str, str] | None = None) -> list[tuple[str, str]]:
        """Generate netlists for each enabled corner.

        Returns list of (corner_name, netlist) tuples.
        """
        corners = self.get_corner_data()
        if not corners:
            return [("default", self._build_full_netlist(variable_overrides))]

        netlists = []
        for corner in corners:
            gen = NetlistGenerator(self.db)
            gen.set_target_simulator(self._current_simulator)
            gen.set_model_bindings(self._active_model_binding_map(corner["name"]))

            directives = NetlistDirectives()
            self._configure_pdk_model_directives(
                directives,
                self._selected_pdk_name(),
                corner["process"],
                corner["name"],
            )
            variables = self.var_widget.get_variables()
            if variables:
                directives.params.update(variables)
            if variable_overrides:
                directives.params.update(variable_overrides)

            # Add corner-specific parameters
            directives.params["CORNER_TEMP"] = corner["temp"]
            directives.params["CORNER_VDD"] = corner["vdd"]
            directives.temp = float(corner["temp"])

            directives.measures = self.measurement_widget.get_measure_lines()
            directives.nodesets = self.convergence_widget.get_nodeset_lines()
            directives.ics = self.convergence_widget.get_ic_lines()

            gen._directives = directives

            base = gen.generate(self.library, self.cell)
            lines = base.rstrip().split("\n")
            while lines and (lines[-1].strip() == ".END" or lines[-1].strip() == ""):
                lines.pop()

            stimulus_lines = self.stimulus_widget.get_stimulus_lines()
            if stimulus_lines:
                lines.append("")
                lines.append("* Stimulus")
                lines.extend(stimulus_lines)

            lines.append("")
            lines.append(f"* Accuracy: {self._sim_accuracy}")
            lines.append(self._accuracy_options_line())

            for name, widget in self._analysis_tabs.items():
                lines.append("")
                lines.append(f"* Analysis: {name}")
                lines.append(self._analysis_spice_line(name, widget))

            # Parametric sweeps
            sweep_lines = self.sweep_widget.get_sweep_lines()
            if sweep_lines:
                lines.append("")
                lines.append("* Parametric Sweeps")
                lines.extend(sweep_lines)

            save_lines = self._output_save_lines()
            if save_lines:
                lines.append("")
                lines.append("* Outputs")
                lines.extend(save_lines)

            expr_lines = self.outputs_widget.get_expression_lines()
            if expr_lines:
                lines.append("")
                lines.append("* Output Expressions")
                lines.extend(expr_lines)

            lines.append("")
            lines.append(".END")
            lines.append("")

            netlists.append((corner["name"], "\n".join(lines)))

        return netlists

    def _active_variable_sweep_points(self) -> list[tuple[str, dict[str, str]]]:
        if not hasattr(self, "sweep_widget"):
            return [("", {})]
        return self.sweep_widget.expanded_points()

    def _safe_sim_name_suffix(self, text: str) -> str:
        suffix = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(text or "").strip())
        suffix = suffix.strip("._-")
        return suffix[:80] or "run"

    # ── Actions ───────────────────────────────────────────────

    def _on_view_netlist(self):
        self._refresh_run_plan()
        try:
            sweep_points = self._active_variable_sweep_points()
            sweep_label, overrides = sweep_points[0]
            netlist = self._build_full_netlist(overrides)
            if sweep_label and len(sweep_points) > 1:
                netlist = f"* Previewing first variable sweep point: {sweep_label}\n" + netlist
            self.log_view.setPlainText(netlist)
            self._log("Netlist generated")
        except Exception as exc:
            details = traceback.format_exc()
            self.log_view.setPlainText(details)
            self._log(f"Netlist generation failed: {exc}")
            QMessageBox.critical(
                self,
                "Netlist Generation Failed",
                f"Could not generate netlist for {self.library}/{self.cell}.\n\n{exc}",
            )

    def _on_run(self):
        if self._sim_thread is not None and self._sim_thread.isRunning():
            QMessageBox.information(self, "Simulation Running", "A simulation is already running in the background. Use Stop to cancel it.")
            return

        self._refresh_run_plan()
        self._last_sigview_waveforms = {}
        self._last_sigview_payload = {}
        self._sim_merged_waveforms = {}
        self._clear_schematic_dc_annotations_for_run()
        if not self._ensure_selected_analysis_for_run():
            QMessageBox.warning(self, "No Test", "Add at least one SimENV test first.")
            return
        validation_errors = self._analysis_validation_errors()
        if validation_errors:
            QMessageBox.warning(
                self,
                "Invalid Analysis Setup",
                "Fix the analysis setup before running:\n\n" + "\n".join(validation_errors[:8]),
            )
            self.statusBar().showMessage("Analysis setup has invalid fields", 5000)
            return
        model_errors = self._model_validation_errors()
        if model_errors:
            QMessageBox.warning(
                self,
                "Invalid Model Setup",
                "Fix the model setup before running:\n\n" + "\n".join(model_errors[:10]),
            )
            self.statusBar().showMessage("Model setup has invalid fields", 5000)
            return

        corner_mode = self.corner_mode_combo.currentText()
        sim_label = get_simulator_label(self._current_simulator)
        bridge = self._build_bridge()
        if not bridge.is_available():
            ready = ensure_simulator_available(
                self,
                str(getattr(self.db, "workspace", "")),
                self._current_simulator,
                logger=self._log,
            )
            if ready:
                bridge = self._build_bridge()
        if not bridge.is_available():
            self._log(f"{sim_label} not found at: {bridge.exe_path}")
            self._log("Netlist generated but simulation skipped.")
            self.statusBar().showMessage(f"{self._current_simulator} not found")
            return

        try:
            sweep_points = self._active_variable_sweep_points()
        except Exception as exc:
            QMessageBox.warning(self, "Invalid Variable Sweep", str(exc))
            self.statusBar().showMessage("Variable sweep setup has invalid fields", 5000)
            return

        if corner_mode == "Single":
            try:
                jobs = []
                for sweep_label, overrides in sweep_points:
                    if not self._run_cell_enabled("Single", sweep_label or "Single"):
                        continue
                    netlist = self._build_full_netlist(overrides)
                    run_name = sweep_label or "Single"
                    sim_suffix = self._safe_sim_name_suffix(sweep_label) if sweep_label else "single"
                    jobs.append((run_name, netlist, f"simenv_{self.cell}_{sim_suffix}"))
            except Exception as exc:
                details = traceback.format_exc()
                self.log_view.setPlainText(details)
                self._log(f"Netlist generation failed: {exc}")
                QMessageBox.critical(
                    self,
                    "Netlist Generation Failed",
                    f"Could not generate netlist for {self.library}/{self.cell}.\n\n{exc}",
                )
                return
            self.log_view.setPlainText(jobs[0][1] if jobs else "")
            sweep_note = f" with {len(sweep_points)} variable sweep point(s)" if len(sweep_points) > 1 else ""
            self._log(f"Starting {sim_label} simulation{sweep_note} in background...")
            self._start_simulation_worker(jobs, bridge)

        elif corner_mode in ("All Corners", "Selected"):
            try:
                jobs = []
                for sweep_label, overrides in sweep_points:
                    netlists = self._build_corner_netlists(overrides)
                    for corner_name, netlist in netlists:
                        if not self._run_cell_enabled(corner_name, sweep_label or "Single"):
                            continue
                        run_name = corner_name if not sweep_label else f"{corner_name} | {sweep_label}"
                        sim_suffix = self._safe_sim_name_suffix(run_name)
                        jobs.append((run_name, netlist, f"simenv_{self.cell}_{sim_suffix}"))
            except Exception as exc:
                details = traceback.format_exc()
                self.log_view.setPlainText(details)
                self._log(f"Corner netlist generation failed: {exc}")
                QMessageBox.critical(
                    self,
                    "Netlist Generation Failed",
                    f"Could not generate corner netlists for {self.library}/{self.cell}.\n\n{exc}",
                )
                return
            self.log_view.setPlainText(jobs[0][1] if jobs else "")
            self._log(f"Starting {sim_label} multi-corner/sweep simulation ({len(jobs)} run(s)) in background...")
            self._start_simulation_worker(jobs, bridge)

    def _on_stop_simulation(self):
        if self._sim_thread is None or not self._sim_thread.isRunning():
            self.statusBar().showMessage("No simulation is running", 3000)
            return
        self._sim_cancel_requested = True
        if hasattr(self, "act_stop_sim"):
            self.act_stop_sim.setEnabled(False)
        self._log("Stop requested. Terminating active simulation...")
        self.statusBar().showMessage("Stopping simulation...")
        if self._sim_worker is not None:
            self._sim_worker.cancel()

    def _start_simulation_worker(self, jobs: list[tuple[str, str, str]], bridge: SimulatorBridge):
        if not jobs:
            self._run_selected_cells_once = set()
            return
        self._write_pdk_lock_for_jobs(jobs)
        self._mark_jobs_pending(jobs)
        self._run_selected_cells_once = set()
        self._sim_jobs_total = len(jobs)
        self._sim_jobs_done = 0
        self._sim_merged_waveforms = {}
        self._sim_cancel_requested = False
        self._show_simulation_monitor(f"{get_simulator_label(self._current_simulator)} - {len(jobs)} run(s)")
        if hasattr(self, "act_stop_sim"):
            self.act_stop_sim.setEnabled(True)
        self.statusBar().showMessage(f"Simulating in background... 0/{self._sim_jobs_total}")

        self._sim_thread = QThread(self)
        self._sim_worker = SimEnvSimulationWorker(
            self._current_simulator,
            bridge.exe_path,
            bridge.work_dir,
            jobs,
            threads=self._sim_thread_count(),
            timeout=self._sim_timeout_seconds(),
            workspace=str(getattr(self.db, "workspace", "")),
            compare_references=True,
            sim_env=bridge.sim_env,
            ssh_host=bridge.ssh_host,
            ssh_user=bridge.ssh_user,
            ssh_key=bridge.ssh_key,
            remote_gspice=bridge.remote_gspice,
            save_mode=bridge.save_mode,
            adaptive_maxstep=bridge.adaptive_maxstep,
            verbose_compat=bridge.verbose_compat,
        )
        self._sim_worker.moveToThread(self._sim_thread)

        self._sim_thread.started.connect(self._sim_worker.run)
        self._sim_worker.progress.connect(self._on_simulation_progress)
        self._sim_worker.result_ready.connect(self._on_simulation_result_ready)
        self._sim_worker.failed.connect(self._on_simulation_worker_failed)
        self._sim_worker.finished.connect(self._on_simulation_worker_finished)
        self._sim_worker.finished.connect(self._sim_thread.quit)
        self._sim_thread.finished.connect(self._sim_worker.deleteLater)
        self._sim_thread.finished.connect(self._sim_thread.deleteLater)
        self._sim_thread.finished.connect(self._clear_simulation_worker_refs)
        self._sim_thread.start()

    def _write_pdk_lock_for_jobs(self, jobs: list[tuple[str, str, str]]) -> str:
        pdk_name = self._selected_pdk_name()
        registry = self._ensure_pdk_registry()
        if not pdk_name or not registry:
            return ""
        used_corners = sorted({
            self._results_corner_from_run_name(run_name) or run_name
            for run_name, _netlist, _sim_name in jobs
        })
        used_devices = sorted({
            getattr(device, "name", "")
            for device in self._used_pdk_devices(pdk_name)
            if getattr(device, "name", "")
        })
        lock = registry.create_lock(pdk_name, used_devices=used_devices, used_corners=used_corners)
        if not lock:
            return ""

        path = self._pdk_lock_path()
        try:
            if path.exists():
                previous = PDKLock.load(str(path))
                changed = [
                    label for label, old, new in (
                        ("PDK", previous.pdk_name, lock.pdk_name),
                        ("models", previous.model_files_hash, lock.model_files_hash),
                        ("devices", previous.device_catalog_hash, lock.device_catalog_hash),
                        ("manifest", previous.pdk_manifest_hash, lock.pdk_manifest_hash),
                    )
                    if old != new
                ]
                if changed:
                    self._log(f"PDK lock changed since previous run: {', '.join(changed)}")
            path.parent.mkdir(parents=True, exist_ok=True)
            lock.save(str(path))
            self._log(f"PDK lock written: {path}")
            self._refresh_pdk_model_overview()
            return str(path)
        except Exception as exc:
            self._log(f"Could not write PDK lock: {exc}")
            return ""

    def _pdk_lock_path(self) -> Path:
        workspace = Path(str(getattr(self.db, "workspace", "")) or ".")
        design = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{self.library}_{self.cell}").strip("_") or "design"
        return workspace / "runs" / "simenv" / f"{design}.pdk.lock"

    def _on_simulation_progress(self, message: str):
        self._log(message)
        match = re.match(r"Running\s+(.+?)\.\.\.$", str(message).strip())
        if match:
            self._mark_run_cell_status(match.group(1), "Running")
        if self._sim_log_window is not None:
            self._sim_log_window.append_message(message)
        if "%" in str(message):
            self.statusBar().showMessage(str(message))
        else:
            self.statusBar().showMessage(
                f"Simulating in background... {self._sim_jobs_done}/{self._sim_jobs_total}"
            )

    def _on_simulation_result_ready(self, run_name: str, result):
        self._sim_jobs_done += 1
        plot_waveforms = self._prepare_sigview_waveforms(result, run_name)
        self._handle_simulation_result(result, run_name, plot_waveforms)
        row_passed = bool(getattr(result, "success", False))
        row = self._latest_result_row_for_run(run_name)
        if row >= 0:
            status_item = self.results_table.item(row, 6)
            row_passed = bool(status_item and "PASS" in status_item.text())
        self._mark_run_cell_status(run_name, "PASS" if row_passed else "FAIL")
        if result.success and plot_waveforms:
            if self._sim_jobs_total == 1:
                all_waveforms = dict(getattr(result, "waveforms", {}) or plot_waveforms)
                self._last_sigview_waveforms = all_waveforms
                self._last_sigview_payload = self._sigview_payload_for_waveforms(all_waveforms)
                signal_count = self._count_plottable_signals(self._last_sigview_waveforms)
                self._log(f"SigView ready: {signal_count} waveform signal(s)")
                if signal_count:
                    self._show_waveforms(self._last_sigview_payload)
            else:
                self._merge_corner_waveforms(self._sim_merged_waveforms, run_name, plot_waveforms)
        elif self._sim_jobs_total == 1:
            self._last_sigview_waveforms = {}
            self._last_sigview_payload = {}
        self.statusBar().showMessage(
            f"Simulating in background... {self._sim_jobs_done}/{self._sim_jobs_total}"
        )

    def _on_simulation_worker_failed(self, details: str):
        self._log("Background simulation worker failed.")
        self.log_view.append(details)
        if self._sim_log_window is not None:
            self._sim_log_window.append_message("Simulation worker failed.")
            self._sim_log_window.append_message(details)
        self.statusBar().showMessage("Simulation worker failed", 5000)

    def _on_simulation_worker_finished(self):
        if self._sim_merged_waveforms:
            self._last_sigview_waveforms = dict(self._sim_merged_waveforms)
            self._last_sigview_payload = self._sigview_payload_for_waveforms(self._sim_merged_waveforms)
            self._show_waveforms(self._last_sigview_payload)
        if self._sim_cancel_requested:
            self.statusBar().showMessage("Simulation stopped", 5000)
            self._log("Background simulation stopped.")
            if self._sim_log_window is not None:
                self._sim_log_window.append_message("Simulation stopped.")
        else:
            self._show_results_tab()
            self.statusBar().showMessage("Simulation finished", 5000)
            self._log("Background simulation finished.")
            if self._sim_log_window is not None:
                self._sim_log_window.append_message("Simulation finished.")

    def _clear_simulation_worker_refs(self):
        if hasattr(self, "act_stop_sim"):
            self.act_stop_sim.setEnabled(False)
        self._sim_worker = None
        self._sim_thread = None

    def _show_simulation_monitor(self, title: str):
        if self._sim_log_window is None:
            self._sim_log_window = SimulationMonitorWindow(self)
        self._sim_log_window.reset_for_run(title)
        self._sim_log_window.show()
        self._sim_log_window.raise_()
        self._sim_log_window.activateWindow()

    def _prepare_sigview_waveforms(self, result, run_name: str) -> dict:
        """Return the waveform subset that SimENV should plot in SigView."""
        waveforms = getattr(result, "waveforms", {}) or {}
        if not getattr(result, "success", False) or not waveforms:
            return {}

        if self.outputs_widget.chk_save_all_nodes.isChecked():
            return dict(waveforms)

        requested = self._checked_output_specs()
        if not requested:
            return {}

        if any(not self._match_waveform_for_expression(spec.get("expression", ""), waveforms) for spec in requested):
            return dict(waveforms)

        direct_requested = self._selected_direct_trace_names(waveforms)
        if not direct_requested:
            return dict(waveforms)

        x_var = self._x_var_for_waveforms(waveforms)
        filtered = {}
        if x_var:
            filtered[x_var] = waveforms.get(x_var, [])

        available_by_key = {
            self._trace_key(name): name
            for name in waveforms.keys()
            if name != x_var and not str(name).startswith("_")
        }

        missing = []
        for trace_name in direct_requested:
            match = available_by_key.get(self._trace_key(trace_name))
            if match:
                filtered[match] = waveforms[match]
            else:
                missing.append(trace_name)

        if missing:
            self._log(
                f"[{run_name}] Requested output(s) not found in simulator results: "
                + ", ".join(missing[:6])
            )

        if self._count_plottable_signals(filtered):
            self._write_selected_waveform_artifact(result, filtered)
            return filtered
        return {}

    def _checked_output_specs(self) -> list[dict]:
        specs: list[dict] = []
        table = self.outputs_widget.table
        for row in range(table.rowCount()):
            chk = table.cellWidget(row, 2)
            if isinstance(chk, QCheckBox) and not chk.isChecked():
                continue
            sig_item = table.item(row, 0)
            expr_item = table.item(row, 1)
            signal = sig_item.text().strip() if sig_item else ""
            expr = expr_item.text().strip() if expr_item else ""
            if not expr:
                continue
            specs.append({
                "signal": signal or expr,
                "expression": expr,
                "plot": True,
            })
        return specs

    def _selected_direct_trace_names(self, waveforms: dict) -> list[str]:
        requested: list[str] = []
        seen: set[str] = set()
        for spec in self._checked_output_specs():
            match = self._match_waveform_for_expression(spec.get("expression", ""), waveforms)
            if not match:
                continue
            key = self._trace_key(match)
            if key in seen:
                continue
            seen.add(key)
            requested.append(match)
        return requested

    def _match_waveform_for_expression(self, expression: str, waveforms: dict) -> str:
        expr = str(expression or "").strip()
        if not expr or not waveforms:
            return ""
        x_var = self._x_var_for_waveforms(waveforms)
        available = {
            self._trace_key(name): name
            for name in waveforms.keys()
            if name != x_var and not str(name).startswith("_")
        }
        direct_key = self._trace_key(expr)
        if direct_key in available:
            return available[direct_key]
        return ""

    @staticmethod
    def _trace_key(name: str) -> str:
        return re.sub(r"\s+", "", str(name or "")).lower()

    def _x_var_for_waveforms(self, waveforms: dict) -> str:
        for candidate in ("time", "frequency", "v-sweep", "sweep"):
            if candidate in waveforms:
                return candidate
        keys = [k for k in waveforms.keys() if not str(k).startswith("_")]
        return keys[0] if keys else ""

    def _write_selected_waveform_artifact(self, result, waveforms: dict) -> None:
        """Write the selected SimENV plot set and point run manifests to it."""
        run_dir = str(getattr(result, "run_dir", "") or "")
        if not run_dir:
            artifacts = getattr(result, "artifacts", {}) or {}
            manifest = artifacts.get("manifest", "")
            if manifest:
                run_dir = os.path.dirname(manifest)
        if not run_dir:
            return

        selected_path = os.path.join(run_dir, "selected_waveforms.raw")
        if not self._write_waveform_raw(selected_path, waveforms):
            return

        artifacts = getattr(result, "artifacts", None)
        if isinstance(artifacts, dict):
            if "raw" in artifacts and artifacts.get("raw") != selected_path:
                artifacts.setdefault("all_raw", artifacts.get("raw"))
            artifacts["selected_raw"] = selected_path
            artifacts["waveforms"] = selected_path

        self._update_run_manifest_for_selected_waveforms(result, waveforms)

    def _write_waveform_raw(self, path: str, waveforms: dict) -> bool:
        names = [str(k) for k in waveforms.keys() if not str(k).startswith("_")]
        if not names:
            return False
        x_var = self._x_var_for_waveforms(waveforms)
        if x_var in names:
            names.remove(x_var)
            names.insert(0, x_var)
        n_points = max((len(waveforms.get(name, [])) for name in names), default=0)
        if n_points <= 1:
            return False
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", newline="\n", encoding="utf-8") as fh:
                fh.write("Title: Lumen selected waveform RAW\n")
                fh.write("Plotname: Transient Analysis\n")
                fh.write("Flags: real\n")
                fh.write(f"No. Variables: {len(names)}\n")
                fh.write(f"No. Points: {n_points}\n")
                fh.write("Variables:\n")
                for idx, name in enumerate(names):
                    unit = "time" if idx == 0 else "voltage"
                    fh.write(f"{idx}\t{name}\t{unit}\n")
                fh.write("Values:\n")
                for idx in range(n_points):
                    row = []
                    for name in names:
                        values = waveforms.get(name, [])
                        if idx >= len(values):
                            row.append("0")
                            continue
                        try:
                            row.append(f"{float(values[idx]):.16g}")
                        except (TypeError, ValueError):
                            row.append("0")
                    fh.write(" ".join(row) + "\n")
            return True
        except OSError:
            return False

    @staticmethod
    def _extract_scalar_val(values) -> float | None:
        """Return a representative scalar from OP or waveform data."""
        if values is None:
            return None
        if isinstance(values, (int, float)):
            val = float(values)
            return val if math.isfinite(val) else None
        if isinstance(values, (list, tuple)):
            for raw in reversed(values):
                try:
                    val = float(raw)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(val):
                    return val
            return None
        try:
            val = float(values)
        except (TypeError, ValueError):
            return None
        return val if math.isfinite(val) else None

    @staticmethod
    def _format_engineering_val(val: float, unit: str = "") -> str:
        if not math.isfinite(val):
            return "NaN"
        abs_val = abs(val)
        if abs_val == 0:
            return f"0 {unit}".strip()
        elif abs_val >= 1e9:
            return f"{val / 1e9:.3g} G{unit}".strip()
        elif abs_val >= 1e6:
            return f"{val / 1e6:.3g} M{unit}".strip()
        elif abs_val >= 1e3:
            return f"{val / 1e3:.3g} k{unit}".strip()
        elif abs_val >= 1:
            return f"{val:.3g} {unit}".strip()
        elif abs_val >= 1e-3:
            return f"{val * 1e3:.3g} m{unit}".strip()
        elif abs_val >= 1e-6:
            return f"{val * 1e6:.3g} u{unit}".strip()
        elif abs_val >= 1e-9:
            return f"{val * 1e9:.3g} n{unit}".strip()
        elif abs_val >= 1e-12:
            return f"{val * 1e12:.3g} f{unit}".strip()
        else:
            return f"{val:.3e} {unit}".strip()

    def _handle_simulation_result(self, result, run_name: str, plot_waveforms: dict | None = None):
        """Handle simulation result and update industry-style Corner Results Matrix."""
        plot_waveforms = plot_waveforms or {}
        self._attach_model_provenance(result)
        self._ensure_results_corner_section(run_name)
        r = self.results_table.rowCount()
        self.results_table.insertRow(r)

        corner_name = self._results_corner_from_run_name(run_name)
        proc_str = "TT"
        temp_str = "27 °C"
        vdd_str = "1.0 V"

        for entry in self.get_corner_data() if hasattr(self, "corner_table") else []:
            if str(entry.get("name", "")).strip() == corner_name:
                proc_str = str(entry.get("process", "TT")).strip().upper()
                temp_str = f"{entry.get('temp', '27')} °C"
                vdd_str = f"{entry.get('vdd', '1.0')} V"
                break

        analyses_str = ", ".join(self._analysis_tabs.keys()) or "Transient"
        stored_waveforms = dict(plot_waveforms or (getattr(result, "waveforms", {}) or {})) if result.success else {}

        meas_parts = []
        if stored_waveforms:
            for sig_name, vals in stored_waveforms.items():
                if str(sig_name).startswith("_"):
                    continue
                last_val = self._extract_scalar_val(vals)
                if last_val is not None:
                    unit = "Hz" if "freq" in str(sig_name).lower() else ("V" if str(sig_name).lower().startswith("v") or "out" in str(sig_name).lower() else "")
                    meas_parts.append(f"{sig_name}: {self._format_engineering_val(last_val, unit)}")

        signal_count = self._count_plottable_signals(stored_waveforms)
        spec_results = evaluate_specs(self.spec_widget.get_specs(), stored_waveforms) if hasattr(self, "spec_widget") else []
        if spec_results:
            self._spec_results_by_row[r] = spec_results
        if meas_parts:
            meas_str = " | ".join(meas_parts[:6])
            if len(meas_parts) > 6:
                meas_str += f" (+{len(meas_parts) - 6} more)"
        elif signal_count:
            meas_str = f"{signal_count} signal(s) available"
        else:
            meas_str = "None"
        if spec_results:
            spec_pass = sum(1 for item in spec_results if item.get("passed"))
            spec_text = f"Specs {spec_pass}/{len(spec_results)} PASS"
            meas_str = f"{meas_str} | {spec_text}" if meas_str != "None" else spec_text

        # 0: Corner / Run Name
        self.results_table.setItem(r, 0, QTableWidgetItem(run_name))
        # 1: Process
        self.results_table.setItem(r, 1, QTableWidgetItem(proc_str))
        # 2: Temp
        self.results_table.setItem(r, 2, QTableWidgetItem(temp_str))
        # 3: VDD
        self.results_table.setItem(r, 3, QTableWidgetItem(vdd_str))
        # 4: Analysis
        self.results_table.setItem(r, 4, QTableWidgetItem(f"[{self._current_simulator}] {analyses_str}"))
        # 5: Measurements / Outputs
        self.results_table.setItem(r, 5, QTableWidgetItem(meas_str))

        # 6: Status Pill Badge (Green PASS / Red FAIL)
        specs_pass = all(item.get("passed") for item in spec_results) if spec_results else True
        row_passed = bool(result.success) and specs_pass
        status_text = "✓ PASS" if row_passed else "✗ FAIL"
        status_item = QTableWidgetItem(status_text)
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if row_passed:
            status_item.setForeground(QColor("#74c69d"))
            status_item.setBackground(QColor("#1b4332"))
        else:
            status_item.setForeground(QColor("#ff8fa3"))
            status_item.setBackground(QColor("#4a0e17"))
        self.results_table.setItem(r, 6, status_item)

        # 7: Action Pill Button
        btn_plot = QPushButton("📈 Plot")
        btn_plot.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #38bdf8;
                border: 1px solid #334155;
                border-radius: 3px;
                padding: 2px 6px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0284c7;
                color: #ffffff;
            }
        """)
        btn_plot.clicked.connect(lambda _chk=False, row_idx=r: self._plot_result_row(row_idx))
        btn_plot.deleteLater()

        if stored_waveforms:
            self._result_waveforms_by_row[r] = stored_waveforms
        if result.success and getattr(result, "waveforms", None):
            self._result_all_waveforms_by_row[r] = dict(getattr(result, "waveforms", {}) or {})
        matrix_corner = corner_name or "Single"
        self._corner_result_rows.setdefault(matrix_corner, []).append(r)
        sweep_label = self._results_sweep_from_run_name(run_name, matrix_corner)
        self._corner_sweep_result_rows.setdefault((matrix_corner, sweep_label), []).append(r)
        self._refresh_corner_matrix()
        self._refresh_results_baseline_markers()
        elapsed = SimulatorBridge._format_elapsed(float(getattr(result, "elapsed_time", 0.0) or 0.0))
        return_code = int(getattr(result, "return_code", 0) or 0)
        if result.success:
            self._log(f"[{run_name}] Simulation completed successfully in {elapsed} (exit {return_code})")
            if plot_waveforms:
                self._log(
                    f"[{run_name}] Selected waveforms available for SigView: "
                    f"{self._count_plottable_signals(plot_waveforms)} signal(s)"
                )
            elif result.waveforms:
                self._log(
                    f"[{run_name}] Simulator produced {self._count_plottable_signals(result.waveforms)} node signal(s), "
                    "but no SimENV Outputs are selected for plotting."
                )
            if getattr(result, "netlist_path", ""):
                self._log(f"[{run_name}] Input deck: {result.netlist_path}")
                self._log(f"[{run_name}] Dump folder: {os.path.dirname(result.netlist_path)}")
            if result.output_path:
                self._log(f"[{run_name}] Output: {result.output_path}")
            else:
                self._log(f"[{run_name}] Output: no RAW file generated")
            artifacts = getattr(result, "artifacts", {}) or {}
            for kind, path in artifacts.items():
                self._log(f"[{run_name}] {str(kind).upper()} data: {path}")
            if result.log:
                self.log_view.append(f"\n{result.log}")
        else:
            self._log(f"[{run_name}] Simulation FAILED after {elapsed} (exit {return_code})")
            if result.log:
                self.log_view.append(f"\n{result.log}")
            for e in result.errors:
                self._log(f"  {e}")

        self.statusBar().showMessage(("Done" if result.success else "Failed") + f" in {elapsed}", 5000)

    def _attach_model_provenance(self, result) -> None:
        netlist_path = str(getattr(result, "netlist_path", "") or "")
        artifacts = getattr(result, "artifacts", None)
        if not isinstance(artifacts, dict) or not netlist_path:
            return
        model_lines: list[str] = []
        try:
            with open(netlist_path, "r", encoding="utf-8", errors="replace") as handle:
                for raw in handle:
                    line = raw.strip()
                    upper = line.upper()
                    if upper.startswith((".LIB ", ".INCLUDE ", ".INC ", ".GSDI ")):
                        model_lines.append(line)
        except OSError:
            return
        if not model_lines:
            return
        artifacts["model_directives"] = "\n".join(model_lines)
        manifest = artifacts.get("manifest", "")
        if not manifest or not os.path.isfile(manifest):
            return
        try:
            with open(manifest, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            payload.setdefault("artifacts", {})["model_directives"] = artifacts["model_directives"]
            payload["model_directives"] = model_lines
            with open(manifest, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, indent=2)
        except (OSError, json.JSONDecodeError):
            return

    def _ensure_results_corner_section(self, run_name: str):
        """Insert a industry-style section header before corner result rows."""
        corner = self._results_corner_from_run_name(run_name)
        if not corner or corner.lower() == "single":
            return
        if corner in self._result_section_corners:
            return

        last_row = self.results_table.rowCount() - 1
        if last_row in self._result_section_rows:
            item = self.results_table.item(last_row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == corner:
                return

        row = self.results_table.rowCount()
        self.results_table.insertRow(row)
        self.results_table.setSpan(row, 0, 1, self.results_table.columnCount())
        item = QTableWidgetItem(self._results_corner_section_title(corner))
        item.setData(Qt.ItemDataRole.UserRole, corner)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        item.setForeground(QColor("#d7e7ef"))
        item.setBackground(QColor("#1d303e"))
        self.results_table.setItem(row, 0, item)
        self._result_section_rows.add(row)
        self._result_section_corners.add(corner)
        self.results_table.setRowHeight(row, 24)

    def _results_corner_from_run_name(self, run_name: str) -> str:
        name = str(run_name or "").strip()
        if not name or name.lower() == "single":
            return ""
        corner_names = {
            str(entry.get("name", "")).strip()
            for entry in self.get_corner_data() if hasattr(self, "corner_table")
            if str(entry.get("name", "")).strip()
        }
        if name in corner_names:
            return name
        if " | " in name:
            prefix = name.split(" | ", 1)[0].strip()
            if prefix in corner_names:
                return prefix
        if corner_names:
            return ""
        return name if "=" not in name else ""

    def _results_sweep_from_run_name(self, run_name: str, corner_name: str = "") -> str:
        name = str(run_name or "").strip()
        corner = str(corner_name or "").strip()
        if " | " in name:
            prefix, suffix = [part.strip() for part in name.split(" | ", 1)]
            if corner and prefix == corner:
                return suffix or "Single"
        if name and name != corner and "=" in name:
            return name
        return "Single"

    def _results_corner_section_title(self, corner_name: str) -> str:
        corner = str(corner_name or "").strip()
        for entry in self.get_corner_data() if hasattr(self, "corner_table") else []:
            if str(entry.get("name", "")).strip() != corner:
                continue
            details = []
            process = str(entry.get("process", "")).strip()
            temp = str(entry.get("temp", "")).strip()
            vdd = str(entry.get("vdd", "")).strip()
            if process:
                details.append(f"process={process}")
            if temp:
                details.append(f"temp={temp} C")
            if vdd:
                details.append(f"VDD={vdd}")
            suffix = f" ({', '.join(details)})" if details else ""
            return f"Corner: {corner}{suffix}"
        return f"Corner: {corner}"

    def _on_results_context_menu(self, pos):
        row = self.results_table.rowAt(pos.y())
        if row < 0:
            menu = QMenu(self)
            title = QAction("Results", self)
            title.setEnabled(False)
            menu.addAction(title)
            menu.addSeparator()
            act_export = QAction("Export Matrix CSV...", self)
            act_export.triggered.connect(self._export_corner_matrix_to_csv)
            menu.addAction(act_export)
            act_clear_baseline = QAction("Clear Baseline", self)
            act_clear_baseline.setEnabled(bool(self._baseline_run_name))
            act_clear_baseline.triggered.connect(self._clear_result_baseline)
            menu.addAction(act_clear_baseline)
            act_dump = QAction("Open Dump Folder", self)
            act_dump.triggered.connect(self._on_open_sim_dump_dir)
            menu.addAction(act_dump)
            menu.exec(self.results_table.viewport().mapToGlobal(pos))
            return
        if row in self._result_section_rows:
            item = self.results_table.item(row, 0)
            corner = item.data(Qt.ItemDataRole.UserRole) if item else ""
            menu = QMenu(self)
            title = QAction(f"Corner: {corner}", self)
            title.setEnabled(False)
            menu.addAction(title)
            menu.exec(self.results_table.viewport().mapToGlobal(pos))
            return
        self.results_table.selectRow(row)
        waveforms = self._result_waveforms_by_row.get(row, {})
        run_item = self.results_table.item(row, 0)
        status_item = self.results_table.item(row, 6)
        run_name = run_item.text() if run_item else f"Run {row + 1}"
        status = status_item.text() if status_item else ""

        menu = QMenu(self)
        title = QAction(run_name, self)
        title.setEnabled(False)
        menu.addAction(title)
        menu.addSeparator()

        act_plot = QAction("Plot", self)
        act_plot.setEnabled(bool(waveforms))
        act_plot.triggered.connect(lambda: self._plot_result_row(row))
        menu.addAction(act_plot)

        act_calc = QAction("Plot In SigView Calculator", self)
        act_calc.setEnabled(bool(waveforms))
        act_calc.triggered.connect(lambda: self._plot_result_row(row, calculator=True))
        menu.addAction(act_calc)

        signal_menu = menu.addMenu("Plot Signal")
        signal_names = self._plottable_signal_names(waveforms)
        signal_menu.setEnabled(bool(signal_names))
        for signal in signal_names[:80]:
            action = QAction(signal, self)
            action.triggered.connect(lambda _checked=False, sig=signal: self._plot_result_row(row, signals=[sig]))
            signal_menu.addAction(action)
        if len(signal_names) > 80:
            more = QAction(f"... {len(signal_names) - 80} more signal(s)", self)
            more.setEnabled(False)
            signal_menu.addAction(more)

        menu.addSeparator()
        act_export = QAction("Export Matrix CSV...", self)
        act_export.triggered.connect(self._export_corner_matrix_to_csv)
        menu.addAction(act_export)
        act_compare = QAction("Compare Selected Runs...", self)
        act_compare.triggered.connect(self._compare_selected_result_runs)
        menu.addAction(act_compare)
        act_baseline = QAction("Set As Baseline", self)
        act_baseline.triggered.connect(lambda: self._set_result_baseline(run_name))
        menu.addAction(act_baseline)
        act_clear_baseline = QAction("Clear Baseline", self)
        act_clear_baseline.setEnabled(bool(self._baseline_run_name))
        act_clear_baseline.triggered.connect(self._clear_result_baseline)
        menu.addAction(act_clear_baseline)

        annotate_menu = menu.addMenu("Annotate Schematic")
        act_annotate_nodes = QAction("DC Node Voltages", self)
        act_annotate_nodes.triggered.connect(self._on_results_annotate_dc_node_voltages)
        annotate_menu.addAction(act_annotate_nodes)

        act_annotate_op = QAction("DC Operating Point...", self)
        act_annotate_op.triggered.connect(self._on_results_annotate_dc_operating_point)
        annotate_menu.addAction(act_annotate_op)

        act_clear_annotations = QAction("Clear DC Annotations", self)
        act_clear_annotations.triggered.connect(self._on_results_clear_schematic_dc_annotations)
        annotate_menu.addAction(act_clear_annotations)

        menu.addSeparator()
        act_details = QAction("Main Form...", self)
        act_details.triggered.connect(lambda: self._show_result_main_form(row))
        menu.addAction(act_details)

        act_dump = QAction("Open Dump Folder", self)
        act_dump.triggered.connect(self._on_open_sim_dump_dir)
        menu.addAction(act_dump)

        if not waveforms:
            disabled = QAction("No plottable waveforms for this run", self)
            disabled.setEnabled(False)
            menu.addSeparator()
            menu.addAction(disabled)

        self.statusBar().showMessage(f"Results row: {run_name} {status}".strip(), 3000)
        menu.exec(self.results_table.viewport().mapToGlobal(pos))

    def _selected_results_row(self) -> int:
        if not hasattr(self, "results_table"):
            return -1
        row = self.results_table.currentRow()
        if row >= 0 and row not in self._result_section_rows:
            return row
        for candidate in range(self.results_table.rowCount() - 1, -1, -1):
            if candidate not in self._result_section_rows:
                return candidate
        return -1

    def _latest_result_row_for_run(self, run_name: str) -> int:
        if not hasattr(self, "results_table"):
            return -1
        for row in range(self.results_table.rowCount() - 1, -1, -1):
            if row in self._result_section_rows:
                continue
            item = self.results_table.item(row, 0)
            if item and item.text() == run_name:
                return row
        return -1

    def _selected_result_data_rows(self) -> list[int]:
        if not hasattr(self, "results_table"):
            return []
        rows = {
            idx.row()
            for idx in self.results_table.selectionModel().selectedRows()
            if idx.row() not in self._result_section_rows
        }
        current = self.results_table.currentRow()
        if current >= 0 and current not in self._result_section_rows:
            rows.add(current)
        return sorted(rows)

    def _selected_results_waveforms(self) -> tuple[int, dict]:
        row = self._selected_results_row()
        if row < 0:
            return -1, {}
        waveforms = self._result_all_waveforms_by_row.get(row) or self._result_waveforms_by_row.get(row, {})
        return row, dict(waveforms or {})

    def _on_results_plot_selected(self):
        row, waveforms = self._selected_results_waveforms()
        if row < 0 or not waveforms:
            self.statusBar().showMessage("No SimENV results are available to plot", 5000)
            return
        self._plot_result_row(row, calculator=False)

    def _on_results_calculator_selected(self):
        row, waveforms = self._selected_results_waveforms()
        if row < 0 or not waveforms:
            self.statusBar().showMessage("No SimENV results are available for the calculator", 5000)
            return
        self._plot_result_row(row, calculator=True)

    def _on_results_direct_plot_signal(self):
        row, waveforms = self._selected_results_waveforms()
        signals = self._plottable_signal_names(waveforms)
        if row < 0 or not signals:
            self.statusBar().showMessage("No plottable signals in the selected SimENV result", 5000)
            return
        signal, ok = QInputDialog.getItem(
            self,
            "Direct Plot Signal",
            "Signal:",
            signals,
            0,
            False,
        )
        if not ok or not signal:
            return
        self._plot_result_row(row, signals=[signal])
        self.statusBar().showMessage(f"Direct plotted {signal}", 4000)

    def _comparison_rows_for_results(self, left: int, right: int) -> list[list[str]]:
        left_wave = self._result_all_waveforms_by_row.get(left) or self._result_waveforms_by_row.get(left, {})
        right_wave = self._result_all_waveforms_by_row.get(right) or self._result_waveforms_by_row.get(right, {})
        rows: list[list[str]] = []
        for signal in sorted(set(left_wave.keys()) & set(right_wave.keys()), key=str.lower):
            if str(signal).startswith("_"):
                continue
            left_val = self._extract_scalar_val(left_wave.get(signal))
            right_val = self._extract_scalar_val(right_wave.get(signal))
            if left_val is None or right_val is None:
                continue
            delta = right_val - left_val
            pct = "" if left_val == 0 else f"{(delta / left_val) * 100:.4g}%"
            rows.append([
                str(signal),
                self._format_engineering_val(left_val, ""),
                self._format_engineering_val(right_val, ""),
                self._format_engineering_val(delta, ""),
                pct,
            ])
        return rows

    def _compare_selected_result_runs(self):
        rows = self._selected_result_data_rows()
        if len(rows) < 2:
            QMessageBox.information(self, "Compare Runs", "Select two result rows to compare.")
            return
        left, right = rows[:2]
        left_name = self.results_table.item(left, 0).text() if self.results_table.item(left, 0) else f"Run {left + 1}"
        right_name = self.results_table.item(right, 0).text() if self.results_table.item(right, 0) else f"Run {right + 1}"
        compare_rows = self._comparison_rows_for_results(left, right)
        if not compare_rows:
            QMessageBox.information(self, "Compare Runs", "The selected runs do not share scalar waveform values.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Compare Runs - {left_name} vs {right_name}")
        dlg.resize(760, 440)
        layout = QVBoxLayout(dlg)
        title = QLabel(f"{left_name}  vs  {right_name}")
        title.setObjectName("adePanelTitle")
        layout.addWidget(title)
        table = QTableWidget(len(compare_rows), 5)
        table.setHorizontalHeaderLabels(["Signal", left_name, right_name, "Delta", "Delta %"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 5):
            table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        for r, values in enumerate(compare_rows):
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                if c >= 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(r, c, item)
        layout.addWidget(table)
        buttons = QHBoxLayout()
        export = QPushButton("Export CSV")
        export.clicked.connect(lambda _checked=False: self._export_run_comparison_csv(left, right))
        buttons.addWidget(export)
        close = QPushButton("Close")
        close.clicked.connect(dlg.accept)
        buttons.addWidget(close)
        buttons.addStretch()
        layout.addLayout(buttons)
        dlg.exec()

    def _export_run_comparison_csv(self, left: int, right: int):
        filename, _ = QFileDialog.getSaveFileName(self, "Export Run Comparison", "", "CSV Files (*.csv);;All Files (*)")
        if not filename:
            return
        left_name = self.results_table.item(left, 0).text() if self.results_table.item(left, 0) else f"Run {left + 1}"
        right_name = self.results_table.item(right, 0).text() if self.results_table.item(right, 0) else f"Run {right + 1}"
        try:
            with open(filename, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["Signal", left_name, right_name, "Delta", "Delta %"])
                writer.writerows(self._comparison_rows_for_results(left, right))
            self.statusBar().showMessage(f"Exported Run Comparison to {filename}", 5000)
        except Exception as exc:
            QMessageBox.critical(self, "Export Run Comparison", f"Could not export CSV:\n{exc}")

    def _on_results_main_form_selected(self):
        row = self._selected_results_row()
        if row < 0:
            self.statusBar().showMessage("No SimENV results are available", 5000)
            return
        self._show_result_main_form(row)

    def _on_results_annotate_dc_node_voltages(self):
        self._annotate_schematic_from_results("all_node_voltages", {})

    def _on_results_annotate_dc_operating_point(self):
        editor, editor_win = self._ensure_schematic_editor_for_results_annotation()
        if editor is None or editor_win is None:
            return
        inst = editor.selected_instance()
        inst_name = str(getattr(inst, "instance_name", "") or "").strip() if inst is not None else ""
        if not inst_name:
            choices = sorted(
                {
                    str(getattr(item, "instance_name", "") or "").strip()
                    for item in getattr(editor, "instances", [])
                    if str(getattr(item, "instance_name", "") or "").strip()
                },
                key=lambda value: value.lower(),
            )
            if not choices:
                QMessageBox.information(self, "Annotate DC Operating Point", "No schematic instances are available to annotate.")
                return
            inst_name, ok = QInputDialog.getItem(
                self,
                "Annotate DC Operating Point",
                "Instance:",
                choices,
                0,
                False,
            )
            if not ok or not inst_name:
                return
        self._annotate_schematic_from_results("operating_point", {"instance": inst_name})

    def _on_results_clear_schematic_dc_annotations(self):
        editor, editor_win = self._ensure_schematic_editor_for_results_annotation()
        if editor is None:
            return
        if hasattr(editor, "clear_dc_annotations"):
            editor.clear_dc_annotations()
            editor.redraw()
        if editor_win is not None and hasattr(editor_win, "statusBar"):
            editor_win.statusBar().showMessage("Cleared schematic DC annotations", 4000)

    def _ensure_schematic_editor_for_results_annotation(self):
        editor, editor_win = self._ensure_schematic_editor_for_pick()
        if editor is None:
            QMessageBox.information(
                self,
                "Results Annotation",
                "Open the matching schematic view before annotating results.",
            )
            return None, None
        if editor_win is None or not hasattr(editor_win, "_on_dc_annotation_requested"):
            QMessageBox.information(
                self,
                "Results Annotation",
                "The matching schematic window does not support DC result annotations.",
            )
            return None, None
        return editor, editor_win

    def _annotate_schematic_from_results(self, kind: str, payload: dict):
        row, waveforms = self._selected_results_waveforms()
        if row < 0 or not waveforms:
            self.statusBar().showMessage("No SimENV result is available for schematic annotation", 5000)
            return
        editor, editor_win = self._ensure_schematic_editor_for_results_annotation()
        if editor is None or editor_win is None:
            return
        try:
            self._last_sigview_waveforms = dict(waveforms)
            if kind == "all_node_voltages":
                voltages = editor_win._dc_node_voltage_map(waveforms)
                if not voltages:
                    QMessageBox.information(
                        self,
                        "Annotate DC Node Voltages",
                        "No node voltages from the selected SimENV result match the schematic nets.",
                    )
                    return
                editor.annotate_all_dc_node_voltages(voltages)
                editor.redraw()
                editor_win.statusBar().showMessage(
                    f"Annotated {len(voltages)} DC node voltage(s) from selected SimENV result",
                    5000,
                )
            elif kind == "operating_point":
                inst_name = str((payload or {}).get("instance", "")).strip()
                pin_voltages = editor_win._dc_pin_voltages_for_instance(waveforms, inst_name)
                if not pin_voltages:
                    QMessageBox.information(
                        self,
                        "Annotate DC Operating Point",
                        f"No terminal voltages from the selected SimENV result match '{inst_name}'.",
                    )
                    return
                editor.annotate_dc_operating_point(inst_name, pin_voltages)
                editor.redraw()
                editor_win.statusBar().showMessage(
                    f"Annotated DC OP for {inst_name} from selected SimENV result",
                    5000,
                )
            if hasattr(editor_win, "raise_"):
                editor_win.raise_()
                editor_win.activateWindow()
        except Exception as exc:
            QMessageBox.warning(self, "Results Annotation", f"Could not annotate schematic results:\n{exc}")

    def _plottable_signal_names(self, waveforms: dict) -> list[str]:
        if not waveforms:
            return []
        x_var = self._x_var_for_waveforms(waveforms)
        return sorted([
            str(name)
            for name in waveforms.keys()
            if str(name) != x_var and not str(name).startswith("_")
        ], key=lambda s: s.lower())

    def _get_attached_sigview(self, create: bool = True):
        viewer = self._attached_sigview
        if viewer is not None:
            try:
                if not viewer.isVisible():
                    viewer.show()
                return viewer
            except RuntimeError:
                self._attached_sigview = None
        if not create:
            return None
        from lumen.gui.waveform_viewer import SigViewWindow
        viewer = SigViewWindow()
        viewer.attach_to_simenv()
        viewer.send_to_simenv_output.connect(self._on_sigview_output_request)
        viewer.send_to_simenv_measurement.connect(self._on_sigview_measurement_request)
        viewer.destroyed.connect(lambda *_args: setattr(self, "_attached_sigview", None))
        viewer.show()
        self._attached_sigview = viewer
        self._waveform_viewers.append(viewer)
        return viewer

    def _sigview_payload_for_waveforms(
        self,
        waveforms: dict,
        explicit_signals: list[str] | None = None,
        focus_expression: str = "",
        show_calculator: bool = False,
    ) -> dict:
        visible_signals: list[str] | None = None
        derived_expressions: list[dict] = []

        if explicit_signals:
            visible_signals = []
            seen: set[str] = set()
            for name in explicit_signals:
                match = self._match_waveform_for_expression(name, waveforms) or (name if name in waveforms else "")
                if not match:
                    continue
                key = self._trace_key(match)
                if key in seen:
                    continue
                seen.add(key)
                visible_signals.append(match)
        else:
            checked = self._checked_output_specs()
            if checked:
                visible_signals = []
                for spec in checked:
                    expr = spec.get("expression", "")
                    match = self._match_waveform_for_expression(expr, waveforms)
                    if match:
                        if self._trace_key(match) not in {self._trace_key(x) for x in visible_signals}:
                            visible_signals.append(match)
                    else:
                        derived_expressions.append({
                            "name": spec.get("signal", "") or expr,
                            "expression": expr,
                            "visible": True,
                        })
                if not visible_signals and not derived_expressions:
                    visible_signals = None

        return {
            "waveforms": dict(waveforms or {}),
            "x_var": self._x_var_for_waveforms(waveforms or {}),
            "visible_signals": visible_signals,
            "derived_expressions": derived_expressions,
            "focus_expression": str(focus_expression or "").strip(),
            "show_calculator": bool(show_calculator),
            "preserve_user_expressions": True,
        }

    def _plot_result_row(self, row: int, calculator: bool = False, signals: list[str] | None = None):
        waveforms = self._result_all_waveforms_by_row.get(row) or self._result_waveforms_by_row.get(row, {})
        if not waveforms:
            self.main_tabs.setCurrentWidget(self.results_table.parentWidget())
            self.statusBar().showMessage("Selected run has no plottable waveform data", 5000)
            return
        payload = self._sigview_payload_for_waveforms(waveforms, explicit_signals=signals or [], show_calculator=calculator)
        self._last_sigview_waveforms = dict(waveforms)
        self._last_sigview_payload = payload
        self._show_waveforms(payload, calculator=calculator)

    def _waveforms_for_signals(self, waveforms: dict, signals: list[str]) -> dict:
        if not signals:
            return dict(waveforms)
        x_var = self._x_var_for_waveforms(waveforms)
        selected = {}
        if x_var and x_var in waveforms:
            selected[x_var] = waveforms[x_var]
        for signal in signals:
            if signal in waveforms:
                selected[signal] = waveforms[signal]
        return selected

    def _show_result_main_form(self, row: int):
        if row in self._result_section_rows:
            item = self.results_table.item(row, 0)
            corner = item.data(Qt.ItemDataRole.UserRole) if item else ""
            QMessageBox.information(self, "Corner Results", f"Corner section: {corner}")
            return
        run = self.results_table.item(row, 0).text() if self.results_table.item(row, 0) else f"Run {row + 1}"
        analysis = self.results_table.item(row, 4).text() if self.results_table.item(row, 4) else ""
        status = self.results_table.item(row, 6).text() if self.results_table.item(row, 6) else ""
        waveforms = self._result_all_waveforms_by_row.get(row) or self._result_waveforms_by_row.get(row, {})
        signals = self._plottable_signal_names(waveforms)
        QMessageBox.information(
            self,
            "Results Main Form",
            "\n".join([
                f"Run: {run}",
                f"Analysis: {analysis}",
                f"Status: {status}",
                f"Waveforms: {len(signals)} signal(s)",
                "",
                "Right-click this row and choose Plot, Plot In SigView Calculator, or Plot Signal.",
            ]),
        )

    def _show_waveforms(self, waveforms, calculator: bool = False):
        viewer = self._get_attached_sigview(create=True)
        payload = waveforms if isinstance(waveforms, dict) else {"waveforms": dict(waveforms or {})}
        if "waveforms" not in payload:
            payload = self._sigview_payload_for_waveforms(payload, show_calculator=calculator)
        else:
            payload = dict(payload)
            if calculator:
                payload["show_calculator"] = True
        viewer.load_simenv_session(payload)
        viewer.show()
        viewer.raise_()
        viewer.activateWindow()

    def _on_open_waveform(self):
        selected = self.results_table.currentRow() if hasattr(self, "results_table") else -1
        if selected in self._result_waveforms_by_row or selected in self._result_all_waveforms_by_row:
            self._plot_result_row(selected, calculator=False)
            self.statusBar().showMessage("Opened selected run in SigView", 4000)
            return

        if self._last_sigview_waveforms:
            payload = self._sigview_payload_for_waveforms(self._last_sigview_waveforms)
            self._last_sigview_payload = payload
            self._show_waveforms(payload)
            self.statusBar().showMessage("Opened latest waveforms in SigView", 4000)
            return

        if hasattr(self, "main_tabs"):
            self.main_tabs.setCurrentWidget(self.results_table.parentWidget())
        self.statusBar().showMessage("No waveforms yet. Run simulation, then right-click a Results row and choose Plot.", 7000)

    def _on_open_waveform_calculator(self):
        selected = self.results_table.currentRow() if hasattr(self, "results_table") else -1
        if selected in self._result_waveforms_by_row or selected in self._result_all_waveforms_by_row:
            self._plot_result_row(selected, calculator=True)
            self.statusBar().showMessage("Opened selected run in SigView calculator", 4000)
            return

        if self._last_sigview_waveforms:
            payload = self._sigview_payload_for_waveforms(self._last_sigview_waveforms, show_calculator=True)
            self._last_sigview_payload = payload
            self._show_waveforms(payload, calculator=True)
            self.statusBar().showMessage("Opened latest waveforms in SigView calculator", 4000)
            return

        if hasattr(self, "main_tabs"):
            self.main_tabs.setCurrentWidget(self.results_table.parentWidget())
        self.statusBar().showMessage("No waveforms yet. Run simulation, then right-click a Results row and choose Plot In SigView Calculator.", 7000)

    def _on_result_double_click(self, item):
        row = item.row()
        if row in self._result_section_rows:
            return
        waveforms = self._result_all_waveforms_by_row.get(row) or self._result_waveforms_by_row.get(row)
        if not waveforms:
            QMessageBox.information(self, "SigView", "This run does not have plottable waveform data.")
            return
        self._plot_result_row(row, calculator=False)

    def _count_plottable_signals(self, waveforms: dict) -> int:
        if not waveforms:
            return 0
        x_var = ""
        for candidate in ("time", "frequency", "v-sweep", "sweep"):
            if candidate in waveforms:
                x_var = candidate
                break
        if not x_var:
            keys = [k for k in waveforms.keys() if not str(k).startswith("_")]
            x_var = keys[0] if keys else ""
        return len([k for k in waveforms.keys() if k != x_var and not str(k).startswith("_")])

    def _merge_corner_waveforms(self, merged: dict, corner_name: str, waveforms: dict) -> None:
        x_var = ""
        for candidate in ("time", "frequency", "v-sweep", "sweep"):
            if candidate in waveforms:
                x_var = candidate
                break
        if not x_var:
            keys = [k for k in waveforms.keys() if not str(k).startswith("_")]
            x_var = keys[0] if keys else ""

        if x_var and x_var not in merged:
            merged[x_var] = waveforms.get(x_var, [])

        for sig, vals in waveforms.items():
            if sig == x_var or str(sig).startswith("_"):
                continue
            merged[f"{corner_name}.{sig}"] = vals

    def _on_set_sim_dump_dir(self):
        dlg = SimulationDumpSettingsDialog(
            current_dir=self._resolved_sim_dump_dir(),
            default_dir=self._default_sim_dump_dir(),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._set_sim_dump_dir(dlg.selected_path())

    def _set_sim_dump_dir(self, path: str):
        self._sim_dump_dir = str(Path(path).expanduser().resolve())
        os.makedirs(self._sim_dump_dir, exist_ok=True)
        self._log(f"Simulation dump folder set to: {self._sim_dump_dir}")
        self.statusBar().showMessage(f"Sim dump folder: {self._sim_dump_dir}", 5000)
        self._refresh_run_plan()
        self._save_simenv_view_silent()

    def _on_open_sim_dump_dir(self):
        folder = self._resolved_sim_dump_dir()
        os.makedirs(folder, exist_ok=True)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(folder)):
            QMessageBox.warning(self, "Open Dump Folder", f"Could not open:\n{folder}")

    def _on_open_simulator_manager(self):
        win = SimulatorManagerWindow(str(getattr(self.db, "workspace", "")), ciw=self.ciw, parent=self)
        win.show()
        self._sim_manager_window = win

    def _log(self, msg):
        self.log_view.append(f"→ {msg}")
        if self.ciw:
            self.ciw.log(f"[SimENV] {msg}")

    def closeEvent(self, event):
        parent = self.parent()
        if self.property("embeddedSimEnv") and hasattr(parent, "workspace_tabs"):
            index = parent.workspace_tabs.indexOf(self)
            if index >= 0:
                parent.workspace_tabs.removeTab(index)
            if getattr(parent, "_simenv_tab", None) is self:
                parent._simenv_tab = None
        event.accept()

    def _table_text(self, table: QTableWidget, row: int, col: int, default: str = "") -> str:
        item = table.item(row, col)
        return item.text().strip() if item else default

    def _set_table_text(self, table: QTableWidget, row: int, col: int, value) -> None:
        table.setItem(row, col, QTableWidgetItem(str(value)))

    def _collect_simenv_setup(self) -> dict:
        """Collect the complete SimENV state for database save/export."""
        setup = {
            "type": "simenv",
            "version": "2.0",
            "library": self.library,
            "cell": self.cell,
            "view": "simenv",
            "simulator": self._current_simulator,
            "baseline_run": self._baseline_run_name,
            "expression_history": list(self._expression_history[-25:]),
            "sim_dump_dir": self._resolved_sim_dump_dir(),
            "threads": self._sim_thread_count(),
            "timeout": self._sim_timeout_seconds(),
            "accuracy": self._sim_accuracy,
            "tolerance_override": self._sim_tolerance_override,
            "method": self._sim_method,
            "save_mode": self._sim_save_mode,
            "adaptive_maxstep": self._sim_adaptive_maxstep,
            "save_adaptive_points": self._sim_save_adaptive_points,
            "prefer_klu": self._sim_prefer_klu,
            "verbose_compat": self._sim_verbose_compat,
            "pdk": self._selected_pdk_name(infer=False),
            "model_setup_name": self._model_setup_name,
            "model_setups": [
                directive.to_dict() for directive in self._collect_model_table_directives()
            ],
            "model_bindings": [
                binding.to_dict() for binding in self._collect_model_bindings()
            ],
            "disabled_run_cells": [
                {"corner": corner, "sweep": sweep}
                for corner, sweep in sorted(self._disabled_run_cells)
            ],
            "corner_mode": self.corner_mode_combo.currentText() if hasattr(self, "corner_mode_combo") else "Single",
            "machine": self.machine_combo.currentData() if hasattr(self, "machine_combo") else "local",
            "ssh_host": self.ssh_host_edit.text() if hasattr(self, "ssh_host_edit") else "",
            "ssh_user": self.ssh_user_edit.text() if hasattr(self, "ssh_user_edit") else "",
            "ssh_key": self.ssh_key_edit.text() if hasattr(self, "ssh_key_edit") else "",
            "remote_gspice": self.remote_gspice_edit.text() if hasattr(self, "remote_gspice_edit") else "gspice",
            "analyses": {},
            "variables": [],
            "outputs": [],
            "output_options": {
                "save_all_nodes": self.outputs_widget.chk_save_all_nodes.isChecked(),
                "save_all_currents": self.outputs_widget.chk_save_all_currents.isChecked(),
            },
            "measurements": [],
            "specs": [],
            "corners": [],
            "stimuli": [],
            "convergence": {"nodesets": [], "ics": []},
            "sweeps": [],
        }

        for name, widget in self._analysis_tabs.items():
            setup["analyses"][name] = widget.get_values()

        for r in range(self.var_widget.table.rowCount()):
            name = self._table_text(self.var_widget.table, r, 0)
            value = self._table_text(self.var_widget.table, r, 1)
            desc = self._table_text(self.var_widget.table, r, 2)
            if name:
                setup["variables"].append({"name": name, "value": value, "description": desc})

        for r in range(self.outputs_widget.table.rowCount()):
            sig = self._table_text(self.outputs_widget.table, r, 0)
            expr = self._table_text(self.outputs_widget.table, r, 1)
            chk = self.outputs_widget.table.cellWidget(r, 2)
            if sig or expr:
                setup["outputs"].append({
                    "signal": sig,
                    "expression": expr,
                    "plot": bool(chk.isChecked()) if isinstance(chk, QCheckBox) else True,
                })

        for r in range(self.measurement_widget.table.rowCount()):
            type_widget = self.measurement_widget.table.cellWidget(r, 1)
            setup["measurements"].append({
                "name": self._table_text(self.measurement_widget.table, r, 0),
                "type": type_widget.currentText() if isinstance(type_widget, QComboBox) else "AVG",
                "expression": self._table_text(self.measurement_widget.table, r, 2),
                "target": self._table_text(self.measurement_widget.table, r, 3),
                "from": self._table_text(self.measurement_widget.table, r, 4),
                "to": self._table_text(self.measurement_widget.table, r, 5),
            })

        if hasattr(self, "spec_widget"):
            setup["specs"] = [spec.to_dict() for spec in self.spec_widget.get_specs()]

        for r in range(self.corner_table.rowCount()):
            chk = self.corner_table.cellWidget(r, 4)
            setup["corners"].append({
                "name": self._table_text(self.corner_table, r, 0, "corner"),
                "temp": self._table_text(self.corner_table, r, 1, "25"),
                "vdd": self._table_text(self.corner_table, r, 2, "1.8"),
                "process": self._table_text(self.corner_table, r, 3, "tt"),
                "enabled": bool(chk.isChecked()) if isinstance(chk, QCheckBox) else True,
                "model_directives": [
                    directive.to_dict()
                    for directive in self._corner_model_directives.get(
                        self._table_text(self.corner_table, r, 0, "corner"),
                        [],
                    )
                ],
            })

        for r in range(self.stimulus_widget.table.rowCount()):
            type_widget = self.stimulus_widget.table.cellWidget(r, 3)
            setup["stimuli"].append({
                "name": self._table_text(self.stimulus_widget.table, r, 0),
                "plus": self._table_text(self.stimulus_widget.table, r, 1),
                "minus": self._table_text(self.stimulus_widget.table, r, 2),
                "type": type_widget.currentText() if isinstance(type_widget, QComboBox) else "DC",
                "parameters": self._table_text(self.stimulus_widget.table, r, 4),
            })

        for table_name, table in (
            ("nodesets", self.convergence_widget.nodeset_table),
            ("ics", self.convergence_widget.ic_table),
        ):
            for r in range(table.rowCount()):
                node = self._table_text(table, r, 0)
                value = self._table_text(table, r, 1)
                if node:
                    setup["convergence"][table_name].append({"node": node, "value": value})

        for r in range(self.sweep_widget.sweep_table.rowCount()):
            chk = self.sweep_widget.sweep_table.cellWidget(r, 4)
            var = self._table_text(self.sweep_widget.sweep_table, r, 0)
            if var:
                setup["sweeps"].append({
                    "variable": var,
                    "start": self._table_text(self.sweep_widget.sweep_table, r, 1),
                    "stop": self._table_text(self.sweep_widget.sweep_table, r, 2),
                    "step": self._table_text(self.sweep_widget.sweep_table, r, 3),
                    "enabled": bool(chk.isChecked()) if isinstance(chk, QCheckBox) else True,
                })

        return setup

    def _apply_simenv_setup(self, setup: dict) -> None:
        """Apply a saved/imported SimENV setup to the current window."""
        if not isinstance(setup, dict):
            return

        was_suspended = getattr(self, "_simenv_autosave_suspended", False)
        self._simenv_autosave_suspended = True
        sim = normalize_simulator_name(setup.get("simulator", "GSPICE"))
        idx = self.sim_combo.findData(sim)
        if idx >= 0:
            self.sim_combo.setCurrentIndex(idx)
        self._current_simulator = self.sim_combo.currentData() or sim
        self._baseline_run_name = str(setup.get("baseline_run", "") or "").strip()
        self._expression_history = [
            str(item).strip()
            for item in setup.get("expression_history", []) or []
            if str(item).strip()
        ][-25:]
        self._sim_dump_dir = str(setup.get("sim_dump_dir") or self._default_sim_dump_dir())
        try:
            self._sim_threads = max(1, min(16, int(setup.get("threads", 1) or 1)))
        except (TypeError, ValueError):
            self._sim_threads = 1
        if hasattr(self, "thread_spin"):
            self.thread_spin.blockSignals(True)
            self.thread_spin.setValue(self._sim_threads)
            self.thread_spin.blockSignals(False)

        try:
            self._sim_timeout = max(0, min(86400, int(setup.get("timeout", self._sim_timeout) or 0)))
        except (TypeError, ValueError):
            self._sim_timeout = 0
        if hasattr(self, "timeout_spin"):
            self.timeout_spin.blockSignals(True)
            self.timeout_spin.setValue(self._sim_timeout)
            self.timeout_spin.blockSignals(False)

        accuracy = str(setup.get("accuracy") or self._sim_accuracy or "High")
        self._sim_accuracy = accuracy if accuracy in self._accuracy_presets() else "High"
        if hasattr(self, "accuracy_combo"):
            self.accuracy_combo.blockSignals(True)
            self.accuracy_combo.setCurrentText(self._sim_accuracy)
            self.accuracy_combo.blockSignals(False)

        self._sim_tolerance_override = str(setup.get("tolerance_override") or "").strip()
        if hasattr(self, "tolerance_override_edit"):
            self.tolerance_override_edit.blockSignals(True)
            self.tolerance_override_edit.setText(self._sim_tolerance_override)
            self.tolerance_override_edit.blockSignals(False)

        method = str(setup.get("method") or self._sim_method or "Auto")
        allowed_methods = {"Auto", "Backward Euler", "Trapezoidal", "Gear2"}
        self._sim_method = method if method in allowed_methods else "Auto"
        if hasattr(self, "method_combo"):
            self.method_combo.blockSignals(True)
            self.method_combo.setCurrentText(self._sim_method)
            self.method_combo.blockSignals(False)

        save_mode = str(setup.get("save_mode") or self._sim_save_mode or "all").lower()
        self._sim_save_mode = save_mode if save_mode in {"all", "selected", "none"} else "all"
        if hasattr(self, "save_mode_combo"):
            self.save_mode_combo.blockSignals(True)
            self.save_mode_combo.setCurrentText(self._sim_save_mode_label())
            self.save_mode_combo.blockSignals(False)

        self._sim_adaptive_maxstep = bool(setup.get("adaptive_maxstep", self._sim_adaptive_maxstep))
        if hasattr(self, "adaptive_maxstep_check"):
            self.adaptive_maxstep_check.blockSignals(True)
            self.adaptive_maxstep_check.setChecked(self._sim_adaptive_maxstep)
            self.adaptive_maxstep_check.blockSignals(False)

        self._sim_save_adaptive_points = bool(setup.get(
            "save_adaptive_points",
            self._sim_save_adaptive_points,
        ))
        if hasattr(self, "save_adaptive_points_check"):
            self.save_adaptive_points_check.blockSignals(True)
            self.save_adaptive_points_check.setChecked(self._sim_save_adaptive_points)
            self.save_adaptive_points_check.blockSignals(False)

        self._sim_prefer_klu = bool(setup.get("prefer_klu", self._sim_prefer_klu))
        if hasattr(self, "klu_check"):
            self.klu_check.blockSignals(True)
            self.klu_check.setChecked(self._sim_prefer_klu)
            self.klu_check.blockSignals(False)
        try:
            SimulatorRuntimeManager(str(getattr(self.db, "workspace", ""))).set_gspice_prefer_klu(
                self._sim_prefer_klu
            )
        except Exception:
            pass

        self._sim_verbose_compat = bool(setup.get("verbose_compat", self._sim_verbose_compat))
        if hasattr(self, "compat_diag_check"):
            self.compat_diag_check.blockSignals(True)
            self.compat_diag_check.setChecked(self._sim_verbose_compat)
            self.compat_diag_check.blockSignals(False)

        if hasattr(self, "pdk_combo"):
            pdk = setup.get("pdk", "")
            self._pending_simenv_pdk = str(pdk or "")
            idx = self.pdk_combo.findData(pdk)
            if idx >= 0:
                self.pdk_combo.setCurrentIndex(idx)

        self._global_model_directives = [
            ModelDirective.from_dict(item)
            for item in setup.get("model_setups", []) or []
            if isinstance(item, dict)
        ]
        if not self._global_model_directives and str(setup.get("version", "")).strip() not in {"2.0", ""}:
            self._log("Migrated older SimENV setup: corners without model directives will use shared/IHP fallback models.")
        self._model_setup_name = str(setup.get("model_setup_name") or self._model_setup_name or "default")
        if hasattr(self, "model_setup_name_edit"):
            self.model_setup_name_edit.blockSignals(True)
            self.model_setup_name_edit.setText(self._model_setup_name)
            self.model_setup_name_edit.blockSignals(False)
        if hasattr(self, "model_table"):
            self.model_table.blockSignals(True)
            self.model_table.setRowCount(0)
            for directive in self._global_model_directives:
                self._add_model_directive_row(directive.kind, directive.path, directive.section)
            self.model_table.blockSignals(False)
            self._refresh_model_catalog()

        self._model_bindings = [
            DeviceModelBinding.from_dict(item)
            for item in setup.get("model_bindings", []) or []
            if isinstance(item, dict)
        ]
        if hasattr(self, "model_binding_table"):
            self.model_binding_table.blockSignals(True)
            self.model_binding_table.setRowCount(0)
            for binding in self._model_bindings:
                self._add_model_binding_row(
                    binding.instance,
                    binding.device,
                    binding.model,
                    binding.corner,
                    binding.enabled,
                )
            self.model_binding_table.blockSignals(False)

        self._disabled_run_cells = {
            (
                str(item.get("corner", "")).strip(),
                str(item.get("sweep", "")).strip() or "Single",
            )
            for item in setup.get("disabled_run_cells", []) or []
            if isinstance(item, dict) and str(item.get("corner", "")).strip()
        }
        self._refresh_corner_run_matrix_preview()

        mode = setup.get("corner_mode", "Single")
        idx = self.corner_mode_combo.findText(mode)
        if idx >= 0:
            self.corner_mode_combo.setCurrentIndex(idx)

        if hasattr(self, "machine_combo"):
            mach = setup.get("machine", "local")
            idx = self.machine_combo.findData(mach)
            if idx >= 0:
                self.machine_combo.setCurrentIndex(idx)
        if hasattr(self, "ssh_host_edit"):
            self.ssh_host_edit.setText(str(setup.get("ssh_host", "")))
        if hasattr(self, "ssh_user_edit"):
            self.ssh_user_edit.setText(str(setup.get("ssh_user", "")))
        if hasattr(self, "ssh_key_edit"):
            self.ssh_key_edit.setText(str(setup.get("ssh_key", "")))
        if hasattr(self, "remote_gspice_edit"):
            self.remote_gspice_edit.setText(str(setup.get("remote_gspice", "gspice")))
        self._on_machine_changed()

        self.var_widget.table.setRowCount(0)
        variables = setup.get("variables", [])
        if isinstance(variables, dict):
            variables = [{"name": k, "value": v, "description": ""} for k, v in variables.items()]
        for entry in variables if isinstance(variables, list) else []:
            if not isinstance(entry, dict):
                continue
            self.var_widget._add_row()
            r = self.var_widget.table.rowCount() - 1
            self._set_table_text(self.var_widget.table, r, 0, entry.get("name", ""))
            self._set_table_text(self.var_widget.table, r, 1, entry.get("value", ""))
            self._set_table_text(self.var_widget.table, r, 2, entry.get("description", ""))

        self.analysis_setup_tabs.clear()
        self._analysis_tabs.clear()
        for name, values in setup.get("analyses", {}).items():
            if name not in ANALYSES:
                continue
            self._add_analysis(name)
            widget = self._analysis_tabs.get(name)
            if not widget or not isinstance(values, dict):
                continue
            widget.set_values(values)

        self.outputs_widget.table.setRowCount(0)
        output_options = setup.get("output_options", {})
        self.outputs_widget.chk_save_all_nodes.setChecked(bool(output_options.get("save_all_nodes", False)))
        self.outputs_widget.chk_save_all_currents.setChecked(bool(output_options.get("save_all_currents", False)))
        for output in setup.get("outputs", []):
            if not isinstance(output, dict):
                continue
            self.outputs_widget._add_entry(output.get("signal", "sig"), output.get("expression", "V(node)"))
            r = self.outputs_widget.table.rowCount() - 1
            chk = self.outputs_widget.table.cellWidget(r, 2)
            if isinstance(chk, QCheckBox):
                chk.setChecked(bool(output.get("plot", True)))

        self.measurement_widget.table.setRowCount(0)
        for meas in setup.get("measurements", []):
            if not isinstance(meas, dict):
                continue
            self.measurement_widget._add_row()
            r = self.measurement_widget.table.rowCount() - 1
            self._set_table_text(self.measurement_widget.table, r, 0, meas.get("name", f"meas_{r}"))
            type_widget = self.measurement_widget.table.cellWidget(r, 1)
            if isinstance(type_widget, QComboBox):
                idx = type_widget.findText(meas.get("type", "AVG"))
                if idx >= 0:
                    type_widget.setCurrentIndex(idx)
            self._set_table_text(self.measurement_widget.table, r, 2, meas.get("expression", "V(out)"))
            self._set_table_text(self.measurement_widget.table, r, 3, meas.get("target", ""))
            self._set_table_text(self.measurement_widget.table, r, 4, meas.get("from", ""))
            self._set_table_text(self.measurement_widget.table, r, 5, meas.get("to", ""))

        if hasattr(self, "spec_widget"):
            self.spec_widget.table.setRowCount(0)
            for item in setup.get("specs", []):
                if not isinstance(item, dict):
                    continue
                spec = SpecLimit.from_dict(item)
                self.spec_widget._add_row()
                r = self.spec_widget.table.rowCount() - 1
                self._set_table_text(self.spec_widget.table, r, 0, spec.name)
                self._set_table_text(self.spec_widget.table, r, 1, spec.expression)
                metric_widget = self.spec_widget.table.cellWidget(r, 2)
                if isinstance(metric_widget, QComboBox):
                    idx = metric_widget.findText(spec.metric)
                    if idx >= 0:
                        metric_widget.setCurrentIndex(idx)
                self._set_table_text(self.spec_widget.table, r, 3, spec.min_value)
                self._set_table_text(self.spec_widget.table, r, 4, spec.max_value)
                enabled_widget = self.spec_widget.table.cellWidget(r, 5)
                if isinstance(enabled_widget, QCheckBox):
                    enabled_widget.setChecked(spec.enabled)

        if "corners" in setup:
            self.corner_table.setRowCount(0)
            self._corner_model_directives.clear()
            for corner in setup.get("corners", []):
                if not isinstance(corner, dict):
                    continue
                self._add_corner(
                    corner.get("name", "corner"),
                    str(corner.get("temp", "25")),
                    str(corner.get("vdd", "1.8")),
                    corner.get("process", "tt"),
                )
                chk = self.corner_table.cellWidget(self.corner_table.rowCount() - 1, 4)
                if isinstance(chk, QCheckBox):
                    chk.setChecked(bool(corner.get("enabled", True)))
                name = str(corner.get("name", "corner"))
                model_directives = [
                    ModelDirective.from_dict(item)
                    for item in corner.get("model_directives", []) or []
                    if isinstance(item, dict)
                ]
                if model_directives:
                    self._corner_model_directives[name] = model_directives
            self._refresh_corner_model_buttons()
            self._sync_corner_inspector()

        self.stimulus_widget.table.setRowCount(0)
        for stim in setup.get("stimuli", []):
            if not isinstance(stim, dict):
                continue
            self.stimulus_widget._add_row()
            r = self.stimulus_widget.table.rowCount() - 1
            self._set_table_text(self.stimulus_widget.table, r, 0, stim.get("name", "V1"))
            self._set_table_text(self.stimulus_widget.table, r, 1, stim.get("plus", "net1"))
            self._set_table_text(self.stimulus_widget.table, r, 2, stim.get("minus", "0"))
            type_widget = self.stimulus_widget.table.cellWidget(r, 3)
            if isinstance(type_widget, QComboBox):
                idx = type_widget.findText(stim.get("type", "DC"))
                if idx >= 0:
                    type_widget.setCurrentIndex(idx)
            self._set_table_text(self.stimulus_widget.table, r, 4, stim.get("parameters", "1.8"))

        convergence = setup.get("convergence", {})
        self.convergence_widget.nodeset_table.setRowCount(0)
        self.convergence_widget.ic_table.setRowCount(0)
        for table, entries in (
            (self.convergence_widget.nodeset_table, convergence.get("nodesets", []) if isinstance(convergence, dict) else []),
            (self.convergence_widget.ic_table, convergence.get("ics", []) if isinstance(convergence, dict) else []),
        ):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                self.convergence_widget._add_row(table)
                r = table.rowCount() - 1
                self._set_table_text(table, r, 0, entry.get("node", "node"))
                self._set_table_text(table, r, 1, entry.get("value", "0"))

        self.sweep_widget.sweep_table.setRowCount(0)
        for sweep in setup.get("sweeps", []):
            if not isinstance(sweep, dict):
                continue
            self.sweep_widget._add_sweep()
            r = self.sweep_widget.sweep_table.rowCount() - 1
            self._set_table_text(self.sweep_widget.sweep_table, r, 0, sweep.get("variable", "var"))
            self._set_table_text(self.sweep_widget.sweep_table, r, 1, sweep.get("start", "0"))
            self._set_table_text(self.sweep_widget.sweep_table, r, 2, sweep.get("stop", "1.8"))
            self._set_table_text(self.sweep_widget.sweep_table, r, 3, sweep.get("step", "0.1"))
            chk = self.sweep_widget.sweep_table.cellWidget(r, 4)
            if isinstance(chk, QCheckBox):
                chk.setChecked(bool(sweep.get("enabled", True)))

        if hasattr(self, "toolbar_sim_label"):
            self.toolbar_sim_label.setText(self._current_simulator)
        self._update_pdk_badge()
        self._refresh_corner_run_matrix_preview()
        self._refresh_run_plan()
        self._simenv_autosave_suspended = was_suspended

    def _load_simenv_view(self) -> None:
        data = self.db.load_view(self.library, self.cell, "simenv")
        if not data:
            self._auto_apply_attached_pdk_setup()
            return
        try:
            self._apply_simenv_setup(data)
            self.session_badge.setText("Session: saved view")
            self._update_pdk_badge()
            self.statusBar().showMessage("Loaded saved SimENV view", 3000)
        except Exception as exc:
            self._simenv_autosave_suspended = False
            self._log(f"Could not load saved SimENV view: {exc}")

    def _on_save_view(self):
        """Save SimENV as the cell's database view."""
        try:
            data = self._collect_simenv_setup()
            self.db.save_view(self.library, self.cell, "simenv", data)
            self.session_badge.setText("Session: saved view")
            self.statusBar().showMessage(f"Saved {self.library}/{self.cell}/simenv", 3000)
            self._log(f"Saved SimENV view: {self.library}/{self.cell}/simenv")
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Save SimENV Failed",
                f"Could not save {self.library}/{self.cell}/simenv.\n\n{exc}",
            )

    def _on_save_setup(self):
        """Save SimENV Setup as JSON template."""

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Simulation Cockpit Setup", "", "Simulation Cockpit Setup (*.simenv.json);;Legacy Setup (*.cockpit.json)"
        )
        if not path:
            return
        if not path.endswith((".simenv.json", ".cockpit.json")):
            path += ".simenv.json"

        setup = self._collect_simenv_setup()

        with open(path, "w") as f:
            json.dump(setup, f, indent=2)
        self._log(f"Exported SimENV setup to {path}")

    def _on_load_setup(self):
        """Load SimENV Setup from JSON template."""

        path, _ = QFileDialog.getOpenFileName(
            self, "Import Simulation Cockpit Setup", "", "Simulation Cockpit Setup (*.simenv.json);;Legacy Setup (*.cockpit.json)"
        )
        if not path:
            return

        with open(path) as f:
            setup = json.load(f)

        try:
            self._apply_simenv_setup(setup)
            self._log(f"Imported SimENV setup from {path}")
        except Exception as exc:
            self._simenv_autosave_suspended = False
            QMessageBox.critical(self, "Import SimENV Setup", f"Could not import setup:\n{exc}")

    def _preset_store_path(self) -> Path:
        return Path(getattr(self.db, "workspace", ".")) / ".simenv_presets.json"

    def _preset_kind_options(self) -> list[str]:
        return ["Full Setup", "Model Setup", "Corner Setup", "Output/Spec Setup"]

    def _preset_kind_key(self, label: str) -> str:
        mapping = {
            "Full Setup": "full",
            "Model Setup": "models",
            "Corner Setup": "corners",
            "Output/Spec Setup": "outputs",
        }
        return mapping.get(str(label or ""), "full")

    def _preset_display_name(self, name: str, entry: dict) -> str:
        kind = str(entry.get("kind", "full") if isinstance(entry, dict) else "full")
        labels = {
            "full": "Full",
            "models": "Models",
            "corners": "Corners",
            "outputs": "Outputs",
        }
        return f"{labels.get(kind, 'Full')}: {name}"

    def _collect_named_preset(self, kind: str) -> dict:
        setup = self._collect_simenv_setup()
        if kind == "models":
            data = {
                "model_setup_name": setup.get("model_setup_name", "default"),
                "model_setups": setup.get("model_setups", []),
                "model_bindings": setup.get("model_bindings", []),
            }
        elif kind == "corners":
            data = {
                "corner_mode": setup.get("corner_mode", "Single"),
                "corners": setup.get("corners", []),
                "disabled_run_cells": setup.get("disabled_run_cells", []),
            }
        elif kind == "outputs":
            data = {
                "outputs": setup.get("outputs", []),
                "output_options": setup.get("output_options", {}),
                "measurements": setup.get("measurements", []),
                "specs": setup.get("specs", []),
            }
        else:
            kind = "full"
            data = setup
        return {"type": "simenv_preset", "version": "2.1", "kind": kind, "data": data}

    def _apply_named_preset(self, entry: dict) -> str:
        if not isinstance(entry, dict):
            return "Full"
        if "kind" not in entry:
            self._apply_simenv_setup(entry)
            return "Full"
        kind = str(entry.get("kind") or "full")
        data = entry.get("data", {})
        if not isinstance(data, dict):
            data = {}
        if kind == "full":
            self._apply_simenv_setup(data)
            return "Full"

        setup = self._collect_simenv_setup()
        if kind == "models":
            setup.update({
                "model_setup_name": data.get("model_setup_name", "default"),
                "model_setups": data.get("model_setups", []),
                "model_bindings": data.get("model_bindings", []),
            })
            label = "Model"
        elif kind == "corners":
            setup.update({
                "corner_mode": data.get("corner_mode", setup.get("corner_mode", "Single")),
                "corners": data.get("corners", []),
                "disabled_run_cells": data.get("disabled_run_cells", []),
            })
            label = "Corner"
        elif kind == "outputs":
            setup.update({
                "outputs": data.get("outputs", []),
                "output_options": data.get("output_options", {}),
                "measurements": data.get("measurements", []),
                "specs": data.get("specs", []),
            })
            label = "Output/Spec"
        else:
            self._apply_simenv_setup(data)
            return "Full"
        self._apply_simenv_setup(setup)
        return label

    def _load_preset_store(self) -> dict:
        path = self._preset_store_path()
        if not path.exists():
            return {}
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_preset_store(self, store: dict) -> None:
        path = self._preset_store_path()
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(store, fh, indent=2)

    def _on_save_named_preset(self):
        kind_label, ok = QInputDialog.getItem(
            self,
            "Save Named Preset",
            "Preset type:",
            self._preset_kind_options(),
            0,
            False,
        )
        if not ok:
            return
        name, ok = QInputDialog.getText(self, "Save Named Preset", "Preset name:")
        name = str(name or "").strip()
        if not ok or not name:
            return
        kind = self._preset_kind_key(kind_label)
        store = self._load_preset_store()
        store[name] = self._collect_named_preset(kind)
        self._save_preset_store(store)
        self.statusBar().showMessage(f"Saved {kind_label}: {name}", 4000)
        self._log(f"Saved {kind_label}: {name}")

    def _on_load_named_preset(self):
        store = self._load_preset_store()
        names = sorted(store.keys(), key=str.lower)
        if not names:
            QMessageBox.information(self, "Load Named Preset", "No SimENV presets have been saved yet.")
            return
        display_to_name = {
            self._preset_display_name(name, store.get(name, {})): name
            for name in names
        }
        choice, ok = QInputDialog.getItem(
            self,
            "Load Named Preset",
            "Preset:",
            sorted(display_to_name.keys(), key=str.lower),
            0,
            False,
        )
        if not ok or not choice:
            return
        name = display_to_name[str(choice)]
        try:
            label = self._apply_named_preset(store[str(name)])
            self.statusBar().showMessage(f"Loaded {label} preset: {name}", 4000)
            self._log(f"Loaded {label} preset: {name}")
        except Exception as exc:
            self._simenv_autosave_suspended = False
            QMessageBox.critical(self, "Load Named Preset", f"Could not load preset:\n{exc}")

