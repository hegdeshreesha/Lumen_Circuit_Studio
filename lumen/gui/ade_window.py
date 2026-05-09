"""
Lumen Circuit Studio — ADE (Analog Design Environment) Window
Maestro-style tabbed simulation environment supporting all GSPICE analyses.
"""
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QLineEdit, QLabel, QPushButton, QGroupBox, QFormLayout,
    QCheckBox, QSpinBox, QDoubleSpinBox, QTextEdit, QSplitter,
    QStatusBar, QToolBar, QMessageBox, QTreeWidget, QTreeWidgetItem,
    QDialog, QDialogButtonBox, QGridLayout, QScrollArea, QFrame,
    QFileDialog, QInputDialog
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QAction, QFont, QColor

from lumen.core.database import LibraryDatabase
from lumen.core.netlist import NetlistGenerator, NetlistDirectives
from lumen.core.simulator import SimulatorBridge, SIMULATOR_INFO, get_supported_analyses, get_simulator_label
from lumen.core.pdk import PDKRegistry


# All GSPICE-supported analyses
ANALYSES = {
    "DC Operating Point": {"cmd": ".OP", "category": "Standard", "params": []},
    "Transient": {"cmd": ".TRAN", "category": "Standard", "params": [
        ("Step", "1n", "Time step"), ("Stop", "10u", "Stop time"),
        ("Start", "0", "Start time"), ("UIC", False, "Use initial conditions")]},
    "AC Small-Signal": {"cmd": ".AC", "category": "Standard", "params": [
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
        ("Fund", "1G", "Fundamental freq"), ("Harmonics", "7", "Num harmonics"),
        ("Tstab", "10n", "Stabilization time")]},
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
                else:
                    widget = QLineEdit(str(default))
                    widget.setToolTip(desc)
                    widget.setPlaceholderText(desc)
                form.addRow(f"{name}:", widget)
                self._fields[name] = widget
            layout.addWidget(group)
        else:
            note = QLabel("No parameters — runs with default settings.")
            note.setStyleSheet("color: #808080; background: transparent; padding: 16px;")
            layout.addWidget(note)

        layout.addStretch()

    def get_spice_line(self) -> str:
        """Generate the SPICE analysis statement."""
        cmd = self.info["cmd"]
        parts = [cmd]
        for name, default, desc in self.info["params"]:
            w = self._fields.get(name)
            if w is None:
                continue
            if isinstance(w, QCheckBox):
                if w.isChecked():
                    parts.append(name)
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
            elif isinstance(w, QLineEdit):
                result[name] = w.text().strip()
        return result


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

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Outputs"))
        add_btn = QPushButton("+ Add")
        add_btn.setFixedWidth(60)
        add_btn.clicked.connect(self._add_row)
        hdr.addWidget(add_btn)

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
        layout.addWidget(self.table)

        # Add some defaults
        for sig, expr in [("vout", "V(out)"), ("vin", "V(in)"), ("idd", "I(V0)")]:
            self._add_entry(sig, expr)

    def _on_quick_expr(self, text):
        if text and text != "--- Quick Expressions ---":
            self._add_entry("sig", text)
            self._expr_combo.setCurrentIndex(0)

    def _add_row(self):
        self._add_entry("sig", "V(node)")

    def _add_entry(self, sig: str, expr: str):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(sig))
        self.table.setItem(r, 1, QTableWidgetItem(expr))
        chk = QCheckBox()
        chk.setChecked(True)
        self.table.setCellWidget(r, 2, chk)

    def get_save_lines(self) -> list[str]:
        lines = []
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
    """Parametric sweep configuration widget."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Parametric Sweeps"))
        add_btn = QPushButton("+ Add Sweep")
        add_btn.setFixedWidth(90)
        add_btn.clicked.connect(self._add_sweep)
        hdr.addWidget(add_btn)
        layout.addLayout(hdr)

        self.sweep_table = QTableWidget(0, 5)
        self.sweep_table.setHorizontalHeaderLabels([
            "Variable", "Start", "Stop", "Step", "Nested"
        ])
        self.sweep_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.sweep_table.verticalHeader().setVisible(False)
        layout.addWidget(self.sweep_table)

        # Info label
        info = QLabel("Nested sweeps: enable 'Nested' to sweep this variable within the previous sweep.")
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
        chk.setChecked(False)
        self.sweep_table.setCellWidget(r, 4, chk)

    def get_sweep_lines(self) -> list[str]:
        """Generate .STEP PARAM directives."""
        lines = []
        for r in range(self.sweep_table.rowCount()):
            var_item = self.sweep_table.item(r, 0)
            start_item = self.sweep_table.item(r, 1)
            stop_item = self.sweep_table.item(r, 2)
            step_item = self.sweep_table.item(r, 3)

            if var_item and start_item and stop_item and step_item:
                var = var_item.text().strip()
                start = start_item.text().strip()
                stop = stop_item.text().strip()
                step = step_item.text().strip()
                if var:
                    lines.append(f".STEP PARAM {var} {start} {stop} {step}")
        return lines
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
    """Stimulus source editor for complex sources (PULSE, SIN, PWL, SFFM, EXP)."""

    STIM_TYPES = ["DC", "PULSE", "SIN", "PWL", "SFFM", "EXP"]

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

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Source Name", "Type", "Parameters"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

    def _add_row(self):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem("V1"))

        type_combo = QComboBox()
        type_combo.addItems(self.STIM_TYPES)
        type_combo.currentTextChanged.connect(lambda t, row=r: self._update_params(row, t))
        self.table.setCellWidget(r, 1, type_combo)

        self.table.setItem(r, 2, QTableWidgetItem("DC 1.8"))

    def _update_params(self, row, stim_type):
        defaults = {
            "DC": "DC 1.8",
            "PULSE": "PULSE(0 1.8 1n 1n 1n 5n 10n)",
            "SIN": "SIN(0.9 0.9 1G 1n 0)",
            "PWL": "PWL(0 0 1n 1.8 10n 1.8)",
            "SFFM": "SFFM(1.8 0.1 1G 5 1M)",
            "EXP": "EXP(0 1.8 1n 100n 5n 200n)",
        }
        self.table.setItem(row, 2, QTableWidgetItem(defaults.get(stim_type, "")))

    def get_stimulus_lines(self) -> list[str]:
        lines = []
        for r in range(self.table.rowCount()):
            name_item = self.table.item(r, 0)
            type_widget = self.table.cellWidget(r, 1)
            param_item = self.table.item(r, 2)

            if not name_item or not type_widget or not param_item:
                continue

            name = name_item.text().strip()
            stim_type = type_widget.currentText()
            params = param_item.text().strip()

            if not name or not params:
                continue

            lines.append(f"* Stimulus: {name}")
            lines.append(f"{name} ... {stim_type} {params}")
        return lines


class ConvergenceHelpersWidget(QWidget):
    """Convergence helpers: .NODESET, .IC, .LOADBIAS, .SAVEBIAS."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # NODESET
        nodeset_group = QGroupBox("NODESET (Initial Guess)")
        nodeset_layout = QVBoxLayout(nodeset_group)
        self.nodeset_table = QTableWidget(0, 2)
        self.nodeset_table.setHorizontalHeaderLabels(["Node", "Voltage"])
        self.nodeset_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.nodeset_table.verticalHeader().setVisible(False)
        nodeset_layout.addWidget(self.nodeset_table)
        ns_add = QPushButton("+ Add")
        ns_add.setFixedWidth(60)
        ns_add.clicked.connect(lambda: self._add_row(self.nodeset_table))
        nodeset_layout.addWidget(ns_add)
        layout.addWidget(nodeset_group)

        # IC
        ic_group = QGroupBox("IC (Initial Conditions)")
        ic_layout = QVBoxLayout(ic_group)
        self.ic_table = QTableWidget(0, 2)
        self.ic_table.setHorizontalHeaderLabels(["Node", "Voltage"])
        self.ic_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.ic_table.verticalHeader().setVisible(False)
        ic_layout.addWidget(self.ic_table)
        ic_add = QPushButton("+ Add")
        ic_add.setFixedWidth(60)
        ic_add.clicked.connect(lambda: self._add_row(self.ic_table))
        ic_layout.addWidget(ic_add)
        layout.addWidget(ic_group)

        layout.addStretch()

    def _add_row(self, table):
        r = table.rowCount()
        table.insertRow(r)
        table.setItem(r, 0, QTableWidgetItem("node"))
        table.setItem(r, 1, QTableWidgetItem("0"))

    def get_nodeset_lines(self) -> list[str]:
        lines = []
        for r in range(self.nodeset_table.rowCount()):
            node_item = self.nodeset_table.item(r, 0)
            val_item = self.nodeset_table.item(r, 1)
            if node_item and val_item:
                lines.append(f".NODESET {node_item.text().strip()}={val_item.text().strip()}")
        return lines

    def get_ic_lines(self) -> list[str]:
        lines = []
        for r in range(self.ic_table.rowCount()):
            node_item = self.ic_table.item(r, 0)
            val_item = self.ic_table.item(r, 1)
            if node_item and val_item:
                lines.append(f".IC {node_item.text().strip()}={val_item.text().strip()}")
        return lines


class ADEWindow(QMainWindow):
    """Maestro-style Analog Design Environment window."""

    def __init__(self, db: LibraryDatabase, library: str, cell: str,
                 ciw=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.library = library
        self.cell = cell
        self.ciw = ciw
        self._waveform_viewers = []
        self._pdk_registry = PDKRegistry()

        self.setWindowTitle(f"Lumen ADE — {cell} [{library}]")
        self.setMinimumSize(950, 650)
        self.resize(1100, 750)

        self._analysis_tabs: dict[str, AnalysisSetupWidget] = {}
        self._current_simulator = "GSPICE"
        self._build_ui()
        self._create_menus()
        self._create_toolbar()
        self._create_status_bar()

    def _build_ui(self):
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.setCentralWidget(splitter)

        # Top: main tabs
        self.main_tabs = QTabWidget()
        splitter.addWidget(self.main_tabs)

        # Tab 1: Analyses
        self._build_analyses_tab()
        # Tab 2: Design Variables
        self.var_widget = DesignVariablesWidget()
        self.main_tabs.addTab(self.var_widget, "Variables")
        # Tab 3: Outputs
        self.outputs_widget = OutputsWidget()
        self.main_tabs.addTab(self.outputs_widget, "Outputs")
        # Tab 4: Measurements
        self.measurement_widget = MeasurementSetupWidget()
        self.main_tabs.addTab(self.measurement_widget, "Measurements")
        # Tab 5: Stimulus
        self.stimulus_widget = StimulusEditorWidget()
        self.main_tabs.addTab(self.stimulus_widget, "Stimulus")
        # Tab 6: Convergence
        self.convergence_widget = ConvergenceHelpersWidget()
        self.main_tabs.addTab(self.convergence_widget, "Convergence")
        # Tab 7: Corners
        self._build_corners_tab()
        # Tab 8: Parametric Sweep
        self.sweep_widget = ParametricSweepWidget()
        self.main_tabs.addTab(self.sweep_widget, "Sweeps")
        # Tab 9: Results
        self._build_results_tab()

        # Bottom: log
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Consolas", 9))
        self.log_view.setMaximumHeight(180)
        self.log_view.setStyleSheet("QTextEdit{background:#1a1a1a;color:#b0b0b0;border:1px solid #3c3c3c;border-radius:4px;}")
        splitter.addWidget(self.log_view)
        splitter.setSizes([550, 150])

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
        for key in SIMULATOR_INFO:
            self.sim_combo.addItem(get_simulator_label(key), key)
        self.sim_combo.currentIndexChanged.connect(self._on_simulator_changed)
        sim_form.addWidget(self.sim_combo)

        # Availability indicator
        self.sim_status_label = QLabel()
        self.sim_status_label.setStyleSheet("background:transparent;padding:2px;")
        sim_form.addWidget(self.sim_status_label)
        left_layout.addWidget(sim_group)

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

        self.main_tabs.addTab(analyses_widget, "Analyses")

        # Populate initial state
        self._refresh_analysis_tree()

    def _on_simulator_changed(self, index):
        """Handle simulator selection change."""
        self._current_simulator = self.sim_combo.currentData()
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
        bridge = SimulatorBridge(self._current_simulator)
        avail = bridge.is_available()
        if avail:
            self.sim_status_label.setText("\u2713 Found")
            self.sim_status_label.setStyleSheet("color:#8bc78b;background:transparent;padding:2px;")
        else:
            self.sim_status_label.setText(f"\u2717 Not found: {bridge.exe_path}")
            self.sim_status_label.setStyleSheet("color:#cc8888;background:transparent;padding:2px;")

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
        for pdk in self._pdk_registry.get_all_pdks():
            self.pdk_combo.addItem(pdk.display_name, pdk.name)
        hdr.addWidget(self.pdk_combo)

        # Corner run mode
        hdr.addWidget(QLabel("Run Mode:"))
        self.corner_mode_combo = QComboBox()
        self.corner_mode_combo.addItems(["Single", "All Corners", "Selected"])
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

        self.results_table = QTableWidget(0, 4)
        self.results_table.setHorizontalHeaderLabels(["Run", "Analysis", "Status", "Time"])
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.results_table.verticalHeader().setVisible(False)
        layout.addWidget(self.results_table)

        self.main_tabs.addTab(widget, "Results")

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
        self._log(f"Added analysis: {name}")

    # ── Menus & Toolbar ───────────────────────────────────────

    def _create_menus(self):
        menubar = self.menuBar()
        sim_menu = menubar.addMenu("&Simulation")

        act_run = QAction("Run All", self)
        act_run.setShortcut("F5")
        act_run.triggered.connect(self._on_run)
        sim_menu.addAction(act_run)

        act_netlist = QAction("View Netlist", self)
        act_netlist.triggered.connect(self._on_view_netlist)
        sim_menu.addAction(act_netlist)

        sim_menu.addSeparator()

        act_save = QAction("Save Setup...", self)
        act_save.triggered.connect(self._on_save_setup)
        sim_menu.addAction(act_save)

        act_load = QAction("Load Setup...", self)
        act_load.triggered.connect(self._on_load_setup)
        sim_menu.addAction(act_load)

        sim_menu.addSeparator()
        act_close = QAction("Close", self)
        act_close.triggered.connect(self.close)
        sim_menu.addAction(act_close)

    def _create_toolbar(self):
        tb = QToolBar("ADE")
        tb.setIconSize(QSize(18, 18))

        act_run = QAction("\u25b6 Run", self)
        act_run.triggered.connect(self._on_run)
        tb.addAction(act_run)

        act_netlist = QAction("Netlist", self)
        act_netlist.triggered.connect(self._on_view_netlist)
        tb.addAction(act_netlist)

        act_wave = QAction("Waveform", self)
        act_wave.triggered.connect(self._on_open_waveform)
        tb.addAction(act_wave)

        tb.addSeparator()
        tb.addWidget(QLabel(" Sim: "))
        self.toolbar_sim_label = QLabel("GSPICE")
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

    def _build_full_netlist(self) -> str:
        gen = NetlistGenerator(self.db)

        # Configure PDK model includes
        pdk_name = self.pdk_combo.currentData()
        if pdk_name:
            pdk = self._pdk_registry.get_pdk(pdk_name)
            if pdk and pdk.installed:
                model_path = os.path.join(pdk.install_path, "models")
                if os.path.isdir(model_path):
                    gen.set_pdk_model(model_path)

        # Configure directives from ADE
        directives = NetlistDirectives()

        # Design variables as .PARAM
        variables = self.var_widget.get_variables()
        if variables:
            directives.params.update(variables)

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

        # Analyses
        for name, widget in self._analysis_tabs.items():
            lines.append("")
            lines.append(f"* Analysis: {name}")
            lines.append(widget.get_spice_line())

        # Parametric sweeps
        sweep_lines = self.sweep_widget.get_sweep_lines()
        if sweep_lines:
            lines.append("")
            lines.append("* Parametric Sweeps")
            lines.extend(sweep_lines)

        # Outputs
        save_lines = self.outputs_widget.get_save_lines()
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

    def _build_corner_netlists(self) -> list[tuple[str, str]]:
        """Generate netlists for each enabled corner.

        Returns list of (corner_name, netlist) tuples.
        """
        corners = self.get_corner_data()
        if not corners:
            return [("default", self._build_full_netlist())]

        netlists = []
        for corner in corners:
            gen = NetlistGenerator(self.db)

            # Configure PDK model with corner
            pdk_name = self.pdk_combo.currentData()
            if pdk_name:
                pdk = self._pdk_registry.get_pdk(pdk_name)
                if pdk and pdk.installed:
                    model_path = os.path.join(pdk.install_path, "models")
                    if os.path.isdir(model_path):
                        gen.set_pdk_model(model_path, corner["process"])

            directives = NetlistDirectives()
            variables = self.var_widget.get_variables()
            if variables:
                directives.params.update(variables)

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

            for name, widget in self._analysis_tabs.items():
                lines.append("")
                lines.append(f"* Analysis: {name}")
                lines.append(widget.get_spice_line())

            # Parametric sweeps
            sweep_lines = self.sweep_widget.get_sweep_lines()
            if sweep_lines:
                lines.append("")
                lines.append("* Parametric Sweeps")
                lines.extend(sweep_lines)

            save_lines = self.outputs_widget.get_save_lines()
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

    # ── Actions ───────────────────────────────────────────────

    def _on_view_netlist(self):
        netlist = self._build_full_netlist()
        self.log_view.setPlainText(netlist)
        self._log("Netlist generated")

    def _on_run(self):
        if not self._analysis_tabs:
            QMessageBox.warning(self, "No Analysis", "Add at least one analysis first.")
            return

        corner_mode = self.corner_mode_combo.currentText()

        if corner_mode == "Single":
            netlist = self._build_full_netlist()
            self.log_view.setPlainText(netlist)
            sim_label = get_simulator_label(self._current_simulator)
            self._log(f"Starting {sim_label} simulation...")
            self.statusBar().showMessage("Simulating...")

            bridge = SimulatorBridge(self._current_simulator)
            if not bridge.is_available():
                self._log(f"{sim_label} not found at: {bridge.exe_path}")
                self._log("Netlist generated but simulation skipped.")
                self.statusBar().showMessage(f"{self._current_simulator} not found")
                return

            result = bridge.simulate(netlist, sim_name=f"ade_{self.cell}")
            self._handle_simulation_result(result, "Single")

        elif corner_mode in ("All Corners", "Selected"):
            netlists = self._build_corner_netlists()
            sim_label = get_simulator_label(self._current_simulator)
            self._log(f"Starting {sim_label} multi-corner simulation ({len(netlists)} corners)...")
            self.statusBar().showMessage(f"Simulating {len(netlists)} corners...")

            bridge = SimulatorBridge(self._current_simulator)
            if not bridge.is_available():
                self._log(f"{sim_label} not found at: {bridge.exe_path}")
                self._log("Netlist generated but simulation skipped.")
                self.statusBar().showMessage(f"{self._current_simulator} not found")
                return

            all_waveforms = {}
            for corner_name, netlist in netlists:
                self._log(f"Running corner: {corner_name}")
                result = bridge.simulate(
                    netlist,
                    sim_name=f"ade_{self.cell}_{corner_name}"
                )
                self._handle_simulation_result(result, corner_name)
                if result.success and result.waveforms:
                    for sig, vals in result.waveforms.items():
                        all_waveforms[f"{corner_name}.{sig}"] = vals

            if all_waveforms:
                self._show_waveforms(all_waveforms)

        self.main_tabs.setCurrentIndex(7)  # Switch to Results tab

    def _handle_simulation_result(self, result, run_name: str):
        """Handle simulation result and update results table."""
        r = self.results_table.rowCount()
        self.results_table.insertRow(r)
        analyses_str = ", ".join(self._analysis_tabs.keys())
        self.results_table.setItem(r, 0, QTableWidgetItem(run_name))
        self.results_table.setItem(r, 1, QTableWidgetItem(f"[{self._current_simulator}] {analyses_str}"))
        status = "\u2713 Pass" if result.success else "\u2717 Fail"
        status_item = QTableWidgetItem(status)
        status_item.setForeground(QColor("#8bc78b") if result.success else QColor("#cc8888"))
        self.results_table.setItem(r, 2, status_item)
        self.results_table.setItem(r, 3, QTableWidgetItem("--"))

        if result.success:
            self._log(f"[{run_name}] Simulation completed successfully")
            if result.log:
                self.log_view.append(f"\n{result.log}")
        else:
            self._log(f"[{run_name}] Simulation FAILED")
            for e in result.errors:
                self._log(f"  {e}")

        self.statusBar().showMessage("Done" if result.success else "Failed", 5000)

    def _show_waveforms(self, waveforms):
        from lumen.gui.waveform_viewer import WaveformViewerWindow
        v = WaveformViewerWindow()
        v.load_results(waveforms)
        v.show()
        self._waveform_viewers.append(v)

    def _on_open_waveform(self):
        from lumen.gui.waveform_viewer import WaveformViewerWindow
        v = WaveformViewerWindow()
        v.show()
        self._waveform_viewers.append(v)

    def _log(self, msg):
        self.log_view.append(f"→ {msg}")
        if self.ciw:
            self.ciw.log(f"[ADE] {msg}")

    def _on_save_setup(self):
        """Save ADE setup as JSON template."""
        import json
        from pathlib import Path

        path, _ = QFileDialog.getSaveFileName(
            self, "Save ADE Setup", "", "ADE Setup (*.ade.json)"
        )
        if not path:
            return

        setup = {
            "version": "1.0",
            "simulator": self._current_simulator,
            "analyses": {},
            "variables": self.var_widget.get_variables(),
            "outputs": [],
            "measurements": [],
            "corners": self.get_corner_data(),
            "corner_mode": self.corner_mode_combo.currentText(),
        }

        for name, widget in self._analysis_tabs.items():
            setup["analyses"][name] = widget.get_values()

        for r in range(self.outputs_widget.table.rowCount()):
            sig_item = self.outputs_widget.table.item(r, 0)
            expr_item = self.outputs_widget.table.item(r, 1)
            if sig_item and expr_item:
                setup["outputs"].append({
                    "signal": sig_item.text(),
                    "expression": expr_item.text()
                })

        for r in range(self.measurement_widget.table.rowCount()):
            name_item = self.measurement_widget.table.item(r, 0)
            type_widget = self.measurement_widget.table.cellWidget(r, 1)
            expr_item = self.measurement_widget.table.item(r, 2)
            if name_item and type_widget and expr_item:
                setup["measurements"].append({
                    "name": name_item.text(),
                    "type": type_widget.currentText(),
                    "expression": expr_item.text()
                })

        with open(path, "w") as f:
            json.dump(setup, f, indent=2)
        self._log(f"Saved ADE setup to {path}")

    def _on_load_setup(self):
        """Load ADE setup from JSON template."""
        import json

        path, _ = QFileDialog.getOpenFileName(
            self, "Load ADE Setup", "", "ADE Setup (*.ade.json)"
        )
        if not path:
            return

        with open(path) as f:
            setup = json.load(f)

        # Load simulator
        sim = setup.get("simulator", "GSPICE")
        idx = self.sim_combo.findData(sim)
        if idx >= 0:
            self.sim_combo.setCurrentIndex(idx)

        # Load variables
        for name, value in setup.get("variables", {}).items():
            self.var_widget._add_row()
            r = self.var_widget.table.rowCount() - 1
            self.var_widget.table.setItem(r, 0, QTableWidgetItem(name))
            self.var_widget.table.setItem(r, 1, QTableWidgetItem(value))

        # Load analyses
        for name, values in setup.get("analyses", {}).items():
            self._add_analysis(name)
            widget = self._analysis_tabs.get(name)
            if widget:
                for param_name, param_value in values.items():
                    w = widget._fields.get(param_name)
                    if isinstance(w, QCheckBox):
                        w.setChecked(bool(param_value))
                    elif isinstance(w, QLineEdit):
                        w.setText(str(param_value))

        self._log(f"Loaded ADE setup from {path}")
