"""
Lumen Circuit Studio - SimENV Window
Tabbed simulation environment supporting GSPICE, Ngspice, and Xyce analyses.
"""
import os
import re
import traceback
import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QLineEdit, QLabel, QPushButton, QGroupBox, QFormLayout,
    QCheckBox, QSpinBox, QDoubleSpinBox, QTextEdit, QSplitter,
    QStatusBar, QToolBar, QMessageBox, QTreeWidget, QTreeWidgetItem,
    QDialog, QDialogButtonBox, QGridLayout, QScrollArea, QFrame,
    QFileDialog, QInputDialog, QProgressBar
)
from PyQt6.QtWidgets import QAbstractItemView, QMenu
from PyQt6.QtCore import Qt, QSize, QUrl, QObject, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QFont, QColor, QKeySequence, QDesktopServices

from lumen.core.database import LibraryDatabase
from lumen.core.netlist import NetlistGenerator, NetlistDirectives
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
from lumen.gui.branding import apply_window_branding
from lumen.gui.icons import editor_icon
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
        ("BiasOP", True, "Run from the DC operating point, Cadence-style"),
        ("Sweep", "DEC", "DEC/OCT/LIN"), ("Points", "100", "Points per decade"),
        ("Fstart", "1", "Start freq (Hz)"), ("Fstop", "10G", "Stop freq (Hz)")]},
    "Noise": {"cmd": ".NOISE", "category": "Standard", "params": [
        ("Output", "V(out)", "Output node"), ("Source", "V1", "Input source"),
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
        ("ContinuationSteps", "", "Optional continuation step count"),
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
        ("Fund", "1G", "Fund freq"), ("Output", "V(out)", "Output"),
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
                form.addRow(f"{name}:", widget)
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

    progress = pyqtSignal(str)
    result_ready = pyqtSignal(str, object)
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, simulator: str, exe_path: str, work_dir: str,
                 jobs: list[tuple[str, str, str]], threads: int = 1,
                 timeout: int = 0, workspace: str = "", compare_references: bool = True,
                 sim_env: str = "local", ssh_host: str = "", ssh_user: str = "",
                 ssh_key: str = "", remote_gspice: str = "",
                 save_mode: str = "all", adaptive_maxstep: bool = True):
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
        self._bridge: SimulatorBridge | None = None
        self._cancelled = False

    def run(self):
        try:
            self._bridge = SimulatorBridge(
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
            )
            for run_name, netlist, sim_name in self.jobs:
                if self._cancelled:
                    break
                self.progress.emit(f"Running {run_name}...")
                result = self._bridge.simulate(
                    netlist,
                    sim_name=sim_name,
                    threads=self.threads,
                    timeout=self.timeout,
                    progress_callback=self.progress.emit,
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
                        threads=self.threads,
                        progress_callback=self.progress.emit,
                    )
                    report = format_reference_report(comparisons)
                    if report:
                        result.log += "\n" + report + "\n"
                        result.warnings.extend(
                            item.summary_line() for item in comparisons
                        )
                        result.artifacts["reference_comparison"] = report
                self.result_ready.emit(run_name, result)
                if self._cancelled:
                    break
        except Exception:
            self.failed.emit(traceback.format_exc())
        finally:
            self.finished.emit()

    def cancel(self):
        self._cancelled = True
        if self._bridge is not None:
            self._bridge.cancel()


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


class OutputsWidget(QWidget):
    """Output expressions table with support for post-processing expressions."""

    BUILT_IN_EXPRS = [
        "V(node)", "I(source)", "dB20(V(out))", "phase(V(out))",
        "group_delay(V(out))", "V(out)-V(in)", "V(out)/V(in)",
        "abs(V(out))", "real(V(out))", "imag(V(out))",
        "fft(V(out))", "deriv(V(out))", "integ(V(out))",
    ]

    def __init__(self, parent=None, target_provider=None, visualize_hook=None,
                 voltage_pick_hook=None, current_pick_hook=None):
        super().__init__(parent)
        self._target_provider = target_provider
        self._visualize_hook = visualize_hook
        self._voltage_pick_hook = voltage_pick_hook
        self._current_pick_hook = current_pick_hook
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

        # Expression helper
        expr_combo = QComboBox()
        expr_combo.addItems(["--- Quick Expressions ---"] + self.BUILT_IN_EXPRS)
        expr_combo.currentTextChanged.connect(self._on_quick_expr)
        hdr.addWidget(expr_combo)
        self._expr_combo = expr_combo

        layout.addLayout(hdr)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Signal", "Expression", "Plot"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
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
        # Cadence-style terminal-current expression placeholder for post-processing.
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
        return r

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
        if self.chk_save_all_currents.isChecked():
            lines.append(".OPTIONS SAVECURRENTS")
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

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Measurements"))
        add_btn = QPushButton("+ Add")
        add_btn.setFixedWidth(60)
        add_btn.clicked.connect(self._add_row)
        hdr.addWidget(add_btn)
        layout.addLayout(hdr)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Name", "Type", "Expression", "TARG/TRIG", "From", "To"
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
    """Convergence helpers: .NODESET, .IC, .LOADBIAS, .SAVEBIAS with Cadence ADE style UI."""

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

    def _add_row(self, table: QTableWidget, node="node", value="0"):
        r = table.rowCount()
        table.insertRow(r)
        node_item = QTableWidgetItem(node)
        val_item = QTableWidgetItem(value)
        table.setItem(r, 0, node_item)
        table.setItem(r, 1, val_item)
        table.selectRow(r)
        table.editItem(node_item)

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
                node = node_item.text().strip()
                val = val_item.text().strip()
                if node and not node.startswith("*"):
                    lines.append(f".NODESET {node}={val}")
        return lines

    def get_ic_lines(self) -> list[str]:
        lines = []
        for r in range(self.ic_table.rowCount()):
            node_item = self.ic_table.item(r, 0)
            val_item = self.ic_table.item(r, 1)
            if node_item and val_item:
                node = node_item.text().strip()
                val = val_item.text().strip()
                if node and not node.startswith("*"):
                    lines.append(f".IC {node}={val}")
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
        self._result_waveforms_by_row: dict[int, dict] = {}
        self._result_all_waveforms_by_row: dict[int, dict] = {}
        self._result_section_rows: set[int] = set()
        self._result_section_corners: set[str] = set()
        self._sim_thread: QThread | None = None
        self._sim_worker: SimEnvSimulationWorker | None = None
        self._sim_jobs_total = 0
        self._sim_jobs_done = 0
        self._sim_merged_waveforms: dict = {}
        self._sim_cancel_requested = False
        self._sim_log_window: SimulationMonitorWindow | None = None
        self._startup_warnings: list[str] = []
        self._pdk_registry = pdk_registry or self._create_pdk_registry()

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
        self._sim_accuracy = "High"
        self._sim_tolerance_override = ""
        self._sim_method = "Auto"
        self._sim_save_mode = "all"
        self._sim_adaptive_maxstep = True
        self._build_ui()
        self._create_menus()
        self._create_toolbar()
        self._create_status_bar()
        self._load_simenv_view()
        for warning in self._startup_warnings:
            self._log(warning)

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
        if tolerance_override:
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
            "SOLVER=AUTO",
            "TRAN_STAMP_CACHE=1",
            *[f"{key}={value}" for key, value in preset.items()],
        ]
        if self._sim_adaptive_maxstep:
            parts.append("MAXSTEP=AUTO")
        return ".OPTIONS " + " ".join(parts)

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
        has_ic_helpers = False
        convergence_widget = getattr(self, "convergence_widget", None)
        if convergence_widget and hasattr(convergence_widget, "get_ic_lines"):
            try:
                has_ic_helpers = bool(convergence_widget.get_ic_lines())
            except Exception:
                has_ic_helpers = False
        if bool(values.get("UIC", False)) or has_ic_helpers:
            parts.append("UIC")
        return " ".join(parts)

    def _on_accuracy_changed(self, text: str):
        self._sim_accuracy = text if text in self._accuracy_presets() else "High"
        self._log(f"{self._current_simulator} accuracy set to: {self._sim_accuracy}")
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

    def _start_schematic_output_pick(self, kind: str):
        editor, editor_win = self._ensure_schematic_editor_for_pick()
        if editor is None:
            QMessageBox.information(
                self,
                "Pick Output",
                "Open the matching schematic view first, then pick the output again.",
            )
            return

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
                noun = "net for voltage" if kind == "voltage" else "terminal for current"
                editor_win.statusBar().showMessage(f"Pick a {noun} output for SimENV", 7000)
        self._log(f"Pick {'voltage net' if kind == 'voltage' else 'current terminal'} from schematic...")

    def _on_schematic_output_picked(self, kind: str, payload: object):
        if not isinstance(payload, dict):
            return

        if kind == "voltage":
            net = str(payload.get("net", "")).strip()
            if not net:
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

    def _current_waveforms_for_sigview(self) -> dict:
        if self._last_sigview_waveforms:
            return dict(self._last_sigview_waveforms)
        selected = self.results_table.currentRow() if hasattr(self, "results_table") else -1
        if selected in self._result_all_waveforms_by_row:
            return dict(self._result_all_waveforms_by_row[selected])
        if selected in self._result_waveforms_by_row:
            return dict(self._result_waveforms_by_row[selected])
        return {}

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
        self._show_waveforms(payload, calculator=show_calculator)

    def _on_outputs_context_menu(self, pos):
        table = self.outputs_widget.table
        row = table.rowAt(pos.y())
        if row < 0:
            return
        table.selectRow(row)
        sig = self._table_text(table, row, 0, "sig")
        expr = self._table_text(table, row, 1, "")
        menu = QMenu(self)
        title = QAction(sig or expr or "Output", self)
        title.setEnabled(False)
        menu.addAction(title)
        menu.addSeparator()
        act_plot = QAction("Plot In SigView", self)
        act_plot.triggered.connect(lambda: self._show_expression_in_sigview(expr, sig, show_calculator=False))
        menu.addAction(act_plot)
        act_calc = QAction("Send To Calculator", self)
        act_calc.triggered.connect(lambda: self._show_expression_in_sigview(expr, sig, show_calculator=True))
        menu.addAction(act_calc)
        act_meas = QAction("Add Measurement From Output", self)
        act_meas.triggered.connect(lambda: self._add_measurement_from_expression(expr, f"avg_{sig or row}", "AVG"))
        menu.addAction(act_meas)
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
        try:
            data = self._collect_simenv_setup()
            self.db.save_view(self.library, self.cell, "simenv", data)
            self.session_badge.setText("Session: saved view")
            self.statusBar().showMessage(f"Saved {self.library}/{self.cell}/simenv", 3000)
        except Exception as exc:
            self._log(f"Could not autosave SimENV view: {exc}")

    def _infer_pdk_name(self) -> str:
        """Infer the PDK from placed schematic instances or active registry state."""
        if self._pdk_registry:
            try:
                data = self.db.load_view(self.library, self.cell, "schematic") or {}
                for inst in data.get("instances", []):
                    lib_name = inst.get("library", "")
                    if lib_name.startswith("pdk:"):
                        pdk_name = lib_name.split(":", 1)[1]
                        if self._pdk_registry.get_pdk(pdk_name):
                            return pdk_name
            except Exception:
                pass

            try:
                active_name = self._pdk_registry.get_active_name()
                if active_name:
                    return active_name
            except Exception:
                pass
        return ""

    def _selected_pdk_name(self) -> str:
        """Return the SimENV-selected PDK, falling back to schematic/active inference."""
        pdk_name = self.pdk_combo.currentData() if hasattr(self, "pdk_combo") else ""
        return pdk_name or self._infer_pdk_name()

    def _used_pdk_devices(self, pdk_name: str) -> list:
        """Return PDK devices used by this schematic."""
        if not pdk_name or not self._pdk_registry:
            return []
        devices = []
        try:
            data = self.db.load_view(self.library, self.cell, "schematic") or {}
            for inst in data.get("instances", []):
                if inst.get("library") != f"pdk:{pdk_name}":
                    continue
                dev = self._pdk_registry.find_device(inst.get("cell", ""), pdk_name)
                if dev and dev not in devices:
                    devices.append(dev)
        except Exception:
            pass
        return devices

    def _configure_pdk_model_directives(self, directives: NetlistDirectives,
                                        pdk_name: str, process: str = ""):
        """Add Cadence-style model library selections to the netlist."""
        if not pdk_name or not self._pdk_registry:
            return
        pdk = self._pdk_registry.get_pdk(pdk_name)
        if not pdk:
            return

        model_files = list(getattr(pdk, "model_files", []) or [])
        if not model_files:
            return

        used_devices = self._used_pdk_devices(pdk_name)
        added = set()

        def add_lib(path: str, section: str = ""):
            key = ("lib", path, section)
            if path and key not in added:
                directives.libs.append({"path": path, "section": section})
                added.add(key)

        def add_include(path: str):
            key = ("include", path, "")
            if path and key not in added:
                directives.includes.append({"path": path})
                added.add(key)

        if pdk_name == "ihp_sg13g2":
            wanted = self._ihp_model_file_names(used_devices)
            used_wrappers = set()
            sim_folder = "xyce" if self._current_simulator == "Xyce" else "ngspice"
            preferred = sorted(
                model_files,
                key=lambda mf: (
                    0 if f"{os.sep}{sim_folder}{os.sep}" in mf.path.lower() else 1,
                    mf.path.lower(),
                ),
            )
            for mf in preferred:
                filename = os.path.basename(mf.path)
                if filename in used_wrappers:
                    continue
                if filename not in wanted:
                    continue
                section = self._ihp_section_for_file(filename, process or "tt")
                add_lib(mf.path, section)
                used_wrappers.add(filename)
            return

        for mf in model_files:
            suffix = os.path.splitext(mf.path)[1].lower()
            if suffix == ".lib":
                section = self._match_lib_section(getattr(mf, "corners", []), process)
                if section:
                    add_lib(mf.path, section)
                else:
                    add_include(mf.path)
            elif suffix in (".scs", ".spice", ".sp", ".model"):
                add_include(mf.path)

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

    def _build_ui(self):
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.setCentralWidget(splitter)

        splitter.addWidget(self._build_session_header())

        # Session tabs
        self.main_tabs = QTabWidget()
        self.main_tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.main_tabs.currentChanged.connect(lambda _idx: self._refresh_run_plan())
        splitter.addWidget(self.main_tabs)

        self._build_data_view_tab()
        self._build_analyses_tab()
        self._build_corners_tab()
        self._build_run_plan_tab()
        self._build_results_tab()

        # Bottom: log
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Consolas", 9))
        self.log_view.setMaximumHeight(180)
        self.log_view.setStyleSheet("QTextEdit{background:#1a1a1a;color:#b0b0b0;border:1px solid #3c3c3c;border-radius:4px;}")
        splitter.addWidget(self.log_view)
        splitter.setSizes([74, 560, 160])

    def _build_session_header(self):
        header = QFrame()
        header.setObjectName("simenvHeader")
        header.setMaximumHeight(104)
        header.setStyleSheet("""
            QFrame#simenvHeader {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #122232, stop:0.58 #1a2b2f, stop:1 #2d2414);
                border: 1px solid #385060;
                border-radius: 8px;
            }
        """)
        layout = QVBoxLayout(header)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel("SimENV")
        title.setStyleSheet("font-size:22px;font-weight:bold;color:#f2f7fb;background:transparent;")
        subtitle = QLabel(f"Simulation cockpit - {self.library}/{self.cell}")
        subtitle.setStyleSheet("color:#a9c7d8;background:transparent;")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        top_row.addLayout(title_box, stretch=1)

        dump_btn = QPushButton("Dump Settings")
        dump_btn.setIcon(editor_icon("open"))
        dump_btn.setToolTip("Choose where SimENV writes input.sp, logs, RAW waveform files, and run manifests")
        dump_btn.clicked.connect(self._on_set_sim_dump_dir)
        dump_btn.setFixedWidth(126)
        dump_btn.setStyleSheet(
            "QPushButton{color:#e8f2f7;background:#233746;border:1px solid #4b6a82;"
            "border-radius:6px;padding:7px 10px;font-weight:bold;}"
            "QPushButton:hover{background:#2e4658;}"
        )
        top_row.addWidget(dump_btn)

        self.session_badge = QLabel("Session: interactive")
        self.session_badge.setMinimumWidth(128)
        self.session_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.session_badge.setStyleSheet(
            "color:#ffd166;background:#26384a;border:1px solid #4b6a82;"
            "border-radius:10px;padding:6px 12px;font-weight:bold;"
        )
        top_row.addWidget(self.session_badge)
        layout.addLayout(top_row)

        controls_row = QHBoxLayout()
        controls_row.setSpacing(12)

        thread_box = QHBoxLayout()
        thread_box.setSpacing(6)
        thread_label = QLabel("Threads")
        thread_label.setStyleSheet("color:#d7e7ef;background:transparent;font-weight:bold;")
        thread_box.addWidget(thread_label)
        self.thread_spin = QSpinBox()
        self.thread_spin.setRange(1, 16)
        self.thread_spin.setValue(self._sim_threads)
        self.thread_spin.setToolTip("Simulator worker threads. Backends that do not expose a thread option ignore this setting.")
        self.thread_spin.valueChanged.connect(self._on_threads_changed)
        self.thread_spin.setStyleSheet(
            "QSpinBox{color:#f2f7fb;background:#1d303e;border:1px solid #4b6a82;"
            "border-radius:6px;padding:5px;min-width:54px;}"
        )
        thread_box.addWidget(self.thread_spin)
        controls_row.addLayout(thread_box)

        accuracy_box = QHBoxLayout()
        accuracy_box.setSpacing(6)
        accuracy_label = QLabel("Accuracy")
        accuracy_label.setStyleSheet("color:#d7e7ef;background:transparent;font-weight:bold;")
        accuracy_box.addWidget(accuracy_label)
        self.accuracy_combo = QComboBox()
        self.accuracy_combo.addItems(["Low", "Medium", "High", "Very High"])
        self.accuracy_combo.setCurrentText(self._sim_accuracy)
        self.accuracy_combo.setToolTip("Simulation accuracy preset. Higher settings reduce transient timestep error and tighten solver tolerances.")
        self.accuracy_combo.currentTextChanged.connect(self._on_accuracy_changed)
        self.accuracy_combo.setStyleSheet(
            "QComboBox{color:#f2f7fb;background:#1d303e;border:1px solid #4b6a82;"
            "border-radius:6px;padding:5px;min-width:96px;}"
        )
        accuracy_box.addWidget(self.accuracy_combo)
        controls_row.addLayout(accuracy_box)

        tolerance_box = QHBoxLayout()
        tolerance_box.setSpacing(6)
        tolerance_label = QLabel("Tol")
        tolerance_label.setStyleSheet("color:#d7e7ef;background:transparent;font-weight:bold;")
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
        self.tolerance_override_edit.setStyleSheet(
            "QLineEdit{color:#f2f7fb;background:#1d303e;border:1px solid #4b6a82;"
            "border-radius:6px;padding:5px;min-width:76px;max-width:92px;}"
        )
        tolerance_box.addWidget(self.tolerance_override_edit)
        controls_row.addLayout(tolerance_box)

        method_box = QHBoxLayout()
        method_box.setSpacing(6)
        method_label = QLabel("Method")
        method_label.setStyleSheet("color:#d7e7ef;background:transparent;font-weight:bold;")
        method_box.addWidget(method_label)
        self.method_combo = QComboBox()
        self.method_combo.addItems(["Auto", "Backward Euler", "Trapezoidal", "Gear2"])
        self.method_combo.setCurrentText(self._sim_method)
        self.method_combo.setToolTip("Transient integration method. Native GSPICE records the selected method; external backends receive compatible tolerance options.")
        self.method_combo.currentTextChanged.connect(self._on_method_changed)
        self.method_combo.setStyleSheet(
            "QComboBox{color:#f2f7fb;background:#1d303e;border:1px solid #4b6a82;"
            "border-radius:6px;padding:5px;min-width:128px;}"
        )
        method_box.addWidget(self.method_combo)
        controls_row.addLayout(method_box)

        save_box = QHBoxLayout()
        save_box.setSpacing(6)
        save_label = QLabel("Save")
        save_label.setStyleSheet("color:#d7e7ef;background:transparent;font-weight:bold;")
        save_box.addWidget(save_label)
        self.save_mode_combo = QComboBox()
        self.save_mode_combo.addItems(["All", "Selected", "None"])
        self.save_mode_combo.setCurrentText(self._sim_save_mode_label())
        self.save_mode_combo.setToolTip("GSPICE waveform save policy. All matches Cadence-style save-all; Selected writes only output expressions; None writes time only.")
        self.save_mode_combo.currentTextChanged.connect(self._on_save_mode_changed)
        self.save_mode_combo.setStyleSheet(
            "QComboBox{color:#f2f7fb;background:#1d303e;border:1px solid #4b6a82;"
            "border-radius:6px;padding:5px;min-width:92px;}"
        )
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
        self.adaptive_maxstep_check.setStyleSheet(
            "QCheckBox{color:#d7e7ef;background:transparent;font-weight:bold;}"
        )
        controls_row.addWidget(self.adaptive_maxstep_check)
        controls_row.addStretch(1)
        layout.addLayout(controls_row)
        return header

    def _build_data_view_tab(self):
        data_tabs = QTabWidget()
        data_tabs.setDocumentMode(True)

        self.var_widget = DesignVariablesWidget()
        data_tabs.addTab(self.var_widget, "Variables")

        self.outputs_widget = OutputsWidget(
            target_provider=self._collect_output_targets,
            visualize_hook=self._visualize_output_targets,
            voltage_pick_hook=self._start_voltage_pick,
            current_pick_hook=self._start_current_pick,
        )
        self.outputs_widget.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.outputs_widget.table.customContextMenuRequested.connect(self._on_outputs_context_menu)
        data_tabs.addTab(self.outputs_widget, "Outputs")

        self.measurement_widget = MeasurementSetupWidget()
        self.measurement_widget.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.measurement_widget.table.customContextMenuRequested.connect(self._on_measurements_context_menu)
        data_tabs.addTab(self.measurement_widget, "Measurements")

        self.stimulus_widget = StimulusEditorWidget()
        data_tabs.addTab(self.stimulus_widget, "Stimuli")

        self.convergence_widget = ConvergenceHelpersWidget()
        data_tabs.addTab(self.convergence_widget, "Convergence")

        self.sweep_widget = ParametricSweepWidget()
        data_tabs.addTab(self.sweep_widget, "Sweeps")

        self.main_tabs.addTab(data_tabs, "Data View")

    def _build_analyses_tab(self):
        analyses_widget = QWidget()
        layout = QHBoxLayout(analyses_widget)
        layout.setContentsMargins(4, 4, 4, 4)

        # Left: simulator selector + analysis tree
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # Simulator selector
        sim_group = QGroupBox("Simulator")
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
        lbl.setStyleSheet("font-weight:bold;color:#6b9ece;background:transparent;padding:4px;")
        left_layout.addWidget(lbl)

        self.analysis_tree = QTreeWidget()
        self.analysis_tree.setHeaderHidden(True)
        self.analysis_tree.setMinimumWidth(220)
        self.analysis_tree.itemDoubleClicked.connect(self._on_analysis_dblclick)
        left_layout.addWidget(self.analysis_tree)

        add_btn = QPushButton("Add Analysis \u2192")
        add_btn.clicked.connect(self._add_selected_analysis)
        left_layout.addWidget(add_btn)
        layout.addWidget(left_panel)

        # Right: setup tabs for added analyses
        self.analysis_setup_tabs = QTabWidget()
        self.analysis_setup_tabs.setTabsClosable(True)
        self.analysis_setup_tabs.tabCloseRequested.connect(self._on_close_analysis_tab)
        layout.addWidget(self.analysis_setup_tabs, stretch=1)

        self.main_tabs.addTab(analyses_widget, "Tests")

        # Populate initial state
        self._refresh_analysis_tree()

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
        # Update status
        bridge = self._build_bridge()
        avail = bridge.is_available()
        if avail:
            self.sim_status_label.setText("\u2713 Found")
            self.sim_status_label.setStyleSheet("color:#8bc78b;background:transparent;padding:2px;")
        else:
            self.sim_status_label.setText(f"\u2717 Not found: {bridge.exe_path}")
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
                        self.sim_status_label.setText("\u2713 Found")
                        self.sim_status_label.setStyleSheet(
                            "color:#8bc78b;background:transparent;padding:2px;"
                        )
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

    def _on_machine_changed(self, _index=0):
        is_remote = hasattr(self, "machine_combo") and (self.machine_combo.currentData() == "remote")
        if hasattr(self, "remote_ssh_widget"):
            self.remote_ssh_widget.setVisible(is_remote)
        bridge = self._build_bridge()
        if bridge.is_available():
            if is_remote:
                user = self.ssh_user_edit.text().strip() if hasattr(self, "ssh_user_edit") else ""
                host = self.ssh_host_edit.text().strip() if hasattr(self, "ssh_host_edit") else ""
                target_str = f"✓ Remote ({user}@{host})" if user and host else "✓ Remote SSH"
                self.sim_status_label.setText(target_str)
            else:
                self.sim_status_label.setText("✓ Found")
            self.sim_status_label.setStyleSheet("color:#8bc78b;background:transparent;padding:2px;")
        else:
            self.sim_status_label.setText(f"✗ Not found: {bridge.exe_path}")
            self.sim_status_label.setStyleSheet("color:#cc8888;background:transparent;padding:2px;")
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
        self.analysis_setup_tabs.removeTab(index)
        self._analysis_tabs.pop(name, None)
        self._refresh_run_plan()

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

        # PDK selector for corner-aware models
        hdr.addWidget(QLabel("PDK:"))
        self.pdk_combo = QComboBox()
        self.pdk_combo.addItem("None")
        if self._pdk_registry:
            try:
                for pdk in self._pdk_registry.get_all_pdks():
                    self.pdk_combo.addItem(pdk.display_name, pdk.name)
            except Exception as exc:
                self._startup_warnings.append(f"Could not load PDK list: {exc}")
        default_pdk = self._infer_pdk_name()
        if default_pdk:
            idx = self.pdk_combo.findData(default_pdk)
            if idx >= 0:
                self.pdk_combo.setCurrentIndex(idx)
        self.pdk_combo.currentIndexChanged.connect(lambda _idx: self._refresh_run_plan())
        hdr.addWidget(self.pdk_combo)

        # Corner run mode
        hdr.addWidget(QLabel("Run Mode:"))
        self.corner_mode_combo = QComboBox()
        self.corner_mode_combo.addItems(["Single", "All Corners", "Selected"])
        self.corner_mode_combo.currentIndexChanged.connect(lambda _idx: self._refresh_run_plan())
        hdr.addWidget(self.corner_mode_combo)

        layout.addLayout(hdr)

        self.corner_table = QTableWidget(0, 5)
        self.corner_table.setHorizontalHeaderLabels([
            "Name", "Temperature", "Voltage", "Process", "Run"
        ])
        self.corner_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.corner_table.verticalHeader().setVisible(False)
        layout.addWidget(self.corner_table)

        # Add default corners
        for name, temp, vdd, proc in [
            ("TT_25C", "25", "1.8", "tt"),
            ("FF_m40C", "-40", "1.98", "ff"),
            ("SS_125C", "125", "1.62", "ss"),
        ]:
            self._add_corner(name, temp, vdd, proc)

        self.main_tabs.addTab(widget, "Corners")

    def _add_corner_row(self):
        self._add_corner("corner", "25", "1.8", "tt")

    def _add_corner(self, name, temp, vdd, proc):
        r = self.corner_table.rowCount()
        self.corner_table.insertRow(r)
        self.corner_table.setItem(r, 0, QTableWidgetItem(name))
        self.corner_table.setItem(r, 1, QTableWidgetItem(temp))
        self.corner_table.setItem(r, 2, QTableWidgetItem(vdd))
        self.corner_table.setItem(r, 3, QTableWidgetItem(proc))
        chk = QCheckBox()
        chk.setChecked(True)
        self.corner_table.setCellWidget(r, 4, chk)
        self._refresh_run_plan()

    def _build_run_plan_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)

        top = QHBoxLayout()
        title = QLabel("Run Plan")
        title.setStyleSheet("font-size:15px;font-weight:bold;color:#6b9ece;background:transparent;")
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
        session.addChild(QTreeWidgetItem(["Dump Folder", self._resolved_sim_dump_dir()]))
        session.addChild(QTreeWidgetItem(["PDK", self._selected_pdk_name() or "None selected"]))

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
            corner_parent.addChild(QTreeWidgetItem([
                corner["name"],
                f"{corner['process']}, {corner['temp']} C, VDD={corner['vdd']}",
            ]))

        outputs = self._output_save_lines() if hasattr(self, "outputs_widget") else []
        output_parent = add_parent("Outputs", f"{len(outputs)} saved expression(s)")
        for line in outputs:
            output_parent.addChild(QTreeWidgetItem(["Save", line.replace(".SAVE ", "")]))

        measures = self.measurement_widget.get_measure_lines() if hasattr(self, "measurement_widget") else []
        measure_parent = add_parent("Measurements", f"{len(measures)} measurement(s)")
        for line in measures:
            measure_parent.addChild(QTreeWidgetItem(["Measure", line]))

        for i in range(self.run_plan_tree.topLevelItemCount()):
            self.run_plan_tree.topLevelItem(i).setExpanded(True)

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

        self.results_table = QTableWidget(0, 5)
        self.results_table.setHorizontalHeaderLabels(["Run", "Analysis", "Status", "Waveforms", "Time"])
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results_table.customContextMenuRequested.connect(self._on_results_context_menu)
        self.results_table.itemDoubleClicked.connect(self._on_result_double_click)
        layout.addWidget(self.results_table)

        self.main_tabs.addTab(widget, "Results")

    def _output_save_lines(self) -> list[str]:
        mode = str(self._sim_save_mode or "all").lower()
        if mode == "none":
            return []
        if mode == "all":
            lines = [".SAVE ALL"]
            if (
                hasattr(self, "outputs_widget")
                and getattr(self.outputs_widget, "chk_save_all_currents", None) is not None
                and self.outputs_widget.chk_save_all_currents.isChecked()
            ):
                lines.append(".OPTIONS SAVECURRENTS")
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
            for i in range(self.analysis_setup_tabs.count()):
                if self.analysis_setup_tabs.tabText(i) == name:
                    self.analysis_setup_tabs.setCurrentIndex(i)
                    return
        widget = AnalysisSetupWidget(name)
        self._analysis_tabs[name] = widget
        self.analysis_setup_tabs.addTab(widget, name)
        self.analysis_setup_tabs.setCurrentWidget(widget)
        self._log(f"Added test: {name}")
        self._refresh_run_plan()

    # ── Menus & Toolbar ───────────────────────────────────────

    def _create_menus(self):
        menubar = self.menuBar()
        sim_menu = menubar.addMenu("&SimENV")

        act_run = QAction("Run All", self)
        act_run.setShortcut("F5")
        act_run.triggered.connect(self._on_run)
        sim_menu.addAction(act_run)

        act_netlist = QAction("View Netlist", self)
        act_netlist.triggered.connect(self._on_view_netlist)
        sim_menu.addAction(act_netlist)

        act_sigview = QAction("Open SigView", self)
        act_sigview.triggered.connect(self._on_open_waveform)
        sim_menu.addAction(act_sigview)

        act_calc = QAction("Open SigView Calculator", self)
        act_calc.triggered.connect(self._on_open_waveform_calculator)
        sim_menu.addAction(act_calc)

        results_menu = menubar.addMenu("&Results")

        act_results_plot = QAction("Plot Latest/Selected", self)
        act_results_plot.triggered.connect(self._on_results_plot_selected)
        results_menu.addAction(act_results_plot)

        act_results_direct = QAction("Direct Plot Signal...", self)
        act_results_direct.triggered.connect(self._on_results_direct_plot_signal)
        results_menu.addAction(act_results_direct)

        act_results_calc = QAction("Send Latest/Selected To Calculator", self)
        act_results_calc.triggered.connect(self._on_results_calculator_selected)
        results_menu.addAction(act_results_calc)

        results_menu.addSeparator()
        annotate_menu = results_menu.addMenu("Annotate")

        act_annotate_nodes = QAction("DC Node Voltages", self)
        act_annotate_nodes.triggered.connect(self._on_results_annotate_dc_node_voltages)
        annotate_menu.addAction(act_annotate_nodes)

        act_annotate_op = QAction("DC Operating Point...", self)
        act_annotate_op.triggered.connect(self._on_results_annotate_dc_operating_point)
        annotate_menu.addAction(act_annotate_op)

        act_clear_annotations = QAction("Clear Schematic DC Annotations", self)
        act_clear_annotations.triggered.connect(self._on_results_clear_schematic_dc_annotations)
        annotate_menu.addAction(act_clear_annotations)

        results_menu.addSeparator()
        act_results_form = QAction("Main Form...", self)
        act_results_form.triggered.connect(self._on_results_main_form_selected)
        results_menu.addAction(act_results_form)

        act_results_dump = QAction("Open Dump Folder", self)
        act_results_dump.triggered.connect(self._on_open_sim_dump_dir)
        results_menu.addAction(act_results_dump)

        sim_menu.addSeparator()

        act_save_view = QAction("Save", self)
        act_save_view.setShortcut(QKeySequence("Ctrl+S"))
        act_save_view.triggered.connect(self._on_save_view)
        sim_menu.addAction(act_save_view)

        act_save = QAction("Export SimENV Setup...", self)
        act_save.triggered.connect(self._on_save_setup)
        sim_menu.addAction(act_save)

        act_load = QAction("Import SimENV Setup...", self)
        act_load.triggered.connect(self._on_load_setup)
        sim_menu.addAction(act_load)

        act_dump = QAction("Simulation Dump Settings...", self)
        act_dump.triggered.connect(self._on_set_sim_dump_dir)
        sim_menu.addAction(act_dump)
        act_open_dump = QAction("Open Dump Folder", self)
        act_open_dump.triggered.connect(self._on_open_sim_dump_dir)
        sim_menu.addAction(act_open_dump)
        act_sim_mgr = QAction("Simulator Manager...", self)
        act_sim_mgr.triggered.connect(self._on_open_simulator_manager)
        sim_menu.addAction(act_sim_mgr)

        sim_menu.addSeparator()
        act_close = QAction("Close", self)
        act_close.triggered.connect(self.close)
        sim_menu.addAction(act_close)

    def _create_toolbar(self):
        tb = QToolBar("SimENV")
        tb.setIconSize(QSize(18, 18))

        act_save = QAction("Save", self)
        act_save.setIcon(editor_icon("save"))
        act_save.setToolTip("Save SimENV view")
        act_save.triggered.connect(self._on_save_view)
        tb.addAction(act_save)

        tb.addSeparator()

        act_run = QAction("\u25b6 Run Plan", self)
        act_run.setIcon(editor_icon("run"))
        act_run.triggered.connect(self._on_run)
        tb.addAction(act_run)

        self.act_stop_sim = QAction("Stop", self)
        self.act_stop_sim.setIcon(editor_icon("stop"))
        self.act_stop_sim.setToolTip("Stop the running simulation")
        self.act_stop_sim.setEnabled(False)
        self.act_stop_sim.triggered.connect(self._on_stop_simulation)
        tb.addAction(self.act_stop_sim)

        act_netlist = QAction("Netlist", self)
        act_netlist.setIcon(editor_icon("netlist"))
        act_netlist.triggered.connect(self._on_view_netlist)
        tb.addAction(act_netlist)

        act_wave = QAction("SigView", self)
        act_wave.setIcon(editor_icon("wave"))
        act_wave.triggered.connect(self._on_open_waveform)
        tb.addAction(act_wave)

        act_calc = QAction("Calculator", self)
        act_calc.setIcon(editor_icon("wave"))
        act_calc.setToolTip("Open latest waveforms in SigView calculator")
        act_calc.triggered.connect(self._on_open_waveform_calculator)
        tb.addAction(act_calc)

        act_dump = QAction("Dump Settings", self)
        act_dump.setIcon(editor_icon("open"))
        act_dump.setToolTip("Simulation dump settings")
        act_dump.triggered.connect(self._on_set_sim_dump_dir)
        tb.addAction(act_dump)

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
        process = corner_data[0]["process"] if corner_data else ""
        self._configure_pdk_model_directives(
            directives,
            self._selected_pdk_name(),
            process,
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

            directives = NetlistDirectives()
            self._configure_pdk_model_directives(
                directives,
                self._selected_pdk_name(),
                corner["process"],
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
            return
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
            workspace=str(getattr(self.db, "workspace", "")),
            compare_references=True,
            sim_env=bridge.sim_env,
            ssh_host=bridge.ssh_host,
            ssh_user=bridge.ssh_user,
            ssh_key=bridge.ssh_key,
            remote_gspice=bridge.remote_gspice,
            save_mode=bridge.save_mode,
            adaptive_maxstep=bridge.adaptive_maxstep,
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

    def _on_simulation_progress(self, message: str):
        self._log(message)
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
            self.main_tabs.setCurrentIndex(7)  # Switch to Results tab
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

    def _update_run_manifest_for_selected_waveforms(self, result, waveforms: dict) -> None:
        artifacts = getattr(result, "artifacts", {}) or {}
        manifest_path = artifacts.get("manifest", "")
        if not manifest_path:
            return
        try:
            data = {}
            if os.path.isfile(manifest_path):
                with open(manifest_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            if not isinstance(data, dict):
                data = {}
            data.setdefault("format", "lumen-sim-run")
            data.setdefault("version", 1)
            data["artifacts"] = artifacts
            data["plot_signals"] = [k for k in waveforms.keys() if not str(k).startswith("_")]
            data["plot_source"] = "simenv_outputs"
            with open(manifest_path, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(data, fh, indent=2)
        except (OSError, json.JSONDecodeError):
            return

    def _handle_simulation_result(self, result, run_name: str, plot_waveforms: dict | None = None):
        """Handle simulation result and update results table."""
        plot_waveforms = plot_waveforms or {}
        self._ensure_results_corner_section(run_name)
        r = self.results_table.rowCount()
        self.results_table.insertRow(r)
        analyses_str = ", ".join(self._analysis_tabs.keys())
        self.results_table.setItem(r, 0, QTableWidgetItem(run_name))
        self.results_table.setItem(r, 1, QTableWidgetItem(f"[{self._current_simulator}] {analyses_str}"))
        status = "\u2713 Pass" if result.success else "\u2717 Fail"
        status_item = QTableWidgetItem(status)
        status_item.setForeground(QColor("#8bc78b") if result.success else QColor("#cc8888"))
        self.results_table.setItem(r, 2, status_item)
        stored_waveforms = dict(plot_waveforms or (getattr(result, "waveforms", {}) or {})) if result.success else {}
        signal_count = self._count_plottable_signals(stored_waveforms)
        selected_count = self._count_plottable_signals(plot_waveforms)
        if signal_count:
            wf_label = f"{signal_count} signal(s)"
            if selected_count and selected_count != signal_count:
                wf_label = f"{selected_count} selected / {signal_count} total"
        else:
            wf_label = "None"
        self.results_table.setItem(r, 3, QTableWidgetItem(wf_label))
        self.results_table.setItem(r, 4, QTableWidgetItem("--"))
        if stored_waveforms:
            self._result_waveforms_by_row[r] = stored_waveforms
        if result.success and getattr(result, "waveforms", None):
            self._result_all_waveforms_by_row[r] = dict(getattr(result, "waveforms", {}) or {})

        if result.success:
            self._log(f"[{run_name}] Simulation completed successfully")
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
            self._log(f"[{run_name}] Simulation FAILED")
            if result.log:
                self.log_view.append(f"\n{result.log}")
            for e in result.errors:
                self._log(f"  {e}")

        self.statusBar().showMessage("Done" if result.success else "Failed", 5000)

    def _ensure_results_corner_section(self, run_name: str):
        """Insert a Cadence-style section header before corner result rows."""
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
        status_item = self.results_table.item(row, 2)
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
        analysis = self.results_table.item(row, 1).text() if self.results_table.item(row, 1) else ""
        status = self.results_table.item(row, 2).text() if self.results_table.item(row, 2) else ""
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
        if self._last_sigview_waveforms:
            payload = self._sigview_payload_for_waveforms(self._last_sigview_waveforms)
            self._last_sigview_payload = payload
            self._show_waveforms(payload)
            self.statusBar().showMessage("Opened latest waveforms in SigView", 4000)
            return

        selected = self.results_table.currentRow() if hasattr(self, "results_table") else -1
        if selected in self._result_waveforms_by_row or selected in self._result_all_waveforms_by_row:
            self._plot_result_row(selected, calculator=False)
            self.statusBar().showMessage("Opened selected run in SigView", 4000)
            return

        if hasattr(self, "main_tabs"):
            self.main_tabs.setCurrentWidget(self.results_table.parentWidget())
        self.statusBar().showMessage("No waveforms yet. Run simulation, then right-click a Results row and choose Plot.", 7000)

    def _on_open_waveform_calculator(self):
        if self._last_sigview_waveforms:
            payload = self._sigview_payload_for_waveforms(self._last_sigview_waveforms, show_calculator=True)
            self._last_sigview_payload = payload
            self._show_waveforms(payload, calculator=True)
            self.statusBar().showMessage("Opened latest waveforms in SigView calculator", 4000)
            return

        selected = self.results_table.currentRow() if hasattr(self, "results_table") else -1
        if selected in self._result_waveforms_by_row or selected in self._result_all_waveforms_by_row:
            self._plot_result_row(selected, calculator=True)
            self.statusBar().showMessage("Opened selected run in SigView calculator", 4000)
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
            "version": "1.1",
            "library": self.library,
            "cell": self.cell,
            "view": "simenv",
            "simulator": self._current_simulator,
            "sim_dump_dir": self._resolved_sim_dump_dir(),
            "threads": self._sim_thread_count(),
            "accuracy": self._sim_accuracy,
            "tolerance_override": self._sim_tolerance_override,
            "method": self._sim_method,
            "save_mode": self._sim_save_mode,
            "adaptive_maxstep": self._sim_adaptive_maxstep,
            "pdk": self._selected_pdk_name(),
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

        for r in range(self.corner_table.rowCount()):
            chk = self.corner_table.cellWidget(r, 4)
            setup["corners"].append({
                "name": self._table_text(self.corner_table, r, 0, "corner"),
                "temp": self._table_text(self.corner_table, r, 1, "25"),
                "vdd": self._table_text(self.corner_table, r, 2, "1.8"),
                "process": self._table_text(self.corner_table, r, 3, "tt"),
                "enabled": bool(chk.isChecked()) if isinstance(chk, QCheckBox) else True,
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

        sim = normalize_simulator_name(setup.get("simulator", "GSPICE"))
        idx = self.sim_combo.findData(sim)
        if idx >= 0:
            self.sim_combo.setCurrentIndex(idx)
        self._current_simulator = self.sim_combo.currentData() or sim
        self._sim_dump_dir = str(setup.get("sim_dump_dir") or self._default_sim_dump_dir())
        try:
            self._sim_threads = max(1, min(16, int(setup.get("threads", 1) or 1)))
        except (TypeError, ValueError):
            self._sim_threads = 1
        if hasattr(self, "thread_spin"):
            self.thread_spin.blockSignals(True)
            self.thread_spin.setValue(self._sim_threads)
            self.thread_spin.blockSignals(False)

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

        if hasattr(self, "pdk_combo"):
            pdk = setup.get("pdk", "")
            idx = self.pdk_combo.findData(pdk)
            if idx >= 0:
                self.pdk_combo.setCurrentIndex(idx)

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

        if "corners" in setup:
            self.corner_table.setRowCount(0)
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
        self._refresh_run_plan()

    def _load_simenv_view(self) -> None:
        data = self.db.load_view(self.library, self.cell, "simenv")
        if not data:
            return
        try:
            self._apply_simenv_setup(data)
            self.session_badge.setText("Session: saved view")
            self.statusBar().showMessage("Loaded saved SimENV view", 3000)
        except Exception as exc:
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
            self, "Export SimENV Setup", "", "SimENV Setup (*.simenv.json);;Legacy Setup (*.ade.json)"
        )
        if not path:
            return
        if not path.endswith((".simenv.json", ".ade.json")):
            path += ".simenv.json"

        setup = self._collect_simenv_setup()

        with open(path, "w") as f:
            json.dump(setup, f, indent=2)
        self._log(f"Exported SimENV setup to {path}")

    def _on_load_setup(self):
        """Load SimENV Setup from JSON template."""

        path, _ = QFileDialog.getOpenFileName(
            self, "Import SimENV Setup", "", "SimENV Setup (*.simenv.json);;Legacy Setup (*.ade.json)"
        )
        if not path:
            return

        with open(path) as f:
            setup = json.load(f)

        self._apply_simenv_setup(setup)
        self._log(f"Imported SimENV setup from {path}")





