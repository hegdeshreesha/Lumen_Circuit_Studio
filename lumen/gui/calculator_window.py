"""
Lumen Circuit Studio — Custom-IC-Class Waveform Calculator Window

Provides an interactive GUI Calculator window matching waveform-analysis Calculator:
- Visual signal selectors (VT, IT, VF)
- Function pad (Math, Calculus, Measurements, Spectral)
- Expression stack & buffer history
- Plot & Send-to-ADE output linkage
"""
from __future__ import annotations

from lumen.qt.QtCore import Qt, Signal
from lumen.qt.QtGui import QFont
from lumen.qt.QtWidgets import (
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QPushButton,
    QLineEdit,
    QTextEdit,
    QLabel,
    QComboBox,
    QGroupBox,
    QMessageBox,
)

from lumen.gui.branding import apply_window_branding
from lumen.core.waveform_calculator import WaveformCalculator


class CalculatorWindow(QDialog):
    """waveform-analysis-Class Waveform Calculator Window."""

    expression_evaluated = Signal(str, object)  # expression_str, result_vector_or_scalar
    expression_pushed_to_ade = Signal(str)     # expression_str

    def __init__(self, waveforms: dict = None, parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle("Lumen Waveform Calculator")
        self.resize(650, 520)
        apply_window_branding(self)

        self.waveforms = waveforms or {}
        self.calc = WaveformCalculator(self.waveforms) if self.waveforms else None

        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)

        # 1. Signal Selection Bar
        sig_group = QGroupBox("Signal Selector")
        sig_layout = QHBoxLayout(sig_group)

        sig_layout.addWidget(QLabel("Signal:"))
        self.sig_combo = QComboBox()
        if self.waveforms:
            self.sig_combo.addItems(list(self.waveforms.keys()))
        sig_layout.addWidget(self.sig_combo, stretch=1)

        btn_vt = QPushButton("VT()")
        btn_vt.setToolTip("Transient Voltage")
        btn_vt.clicked.connect(self._on_vt_clicked)
        sig_layout.addWidget(btn_vt)

        btn_it = QPushButton("IT()")
        btn_it.setToolTip("Transient Current")
        btn_it.clicked.connect(self._on_it_clicked)
        sig_layout.addWidget(btn_it)

        btn_vf = QPushButton("VF()")
        btn_vf.setToolTip("AC Frequency Voltage")
        btn_vf.clicked.connect(self._on_vf_clicked)
        sig_layout.addWidget(btn_vf)

        main_layout.addWidget(sig_group)

        # 2. Expression Display Buffer
        buffer_group = QGroupBox("Expression Buffer")
        buf_layout = QVBoxLayout(buffer_group)

        self.expr_edit = QLineEdit()
        self.expr_edit.setFont(QFont("Consolas", 11))
        self.expr_edit.setPlaceholderText('e.g. rise_time("v(out)") or clip("v(out)", 0, 10n)')
        buf_layout.addWidget(self.expr_edit)

        self.result_display = QLabel("Result: (ready)")
        self.result_display.setFont(QFont("Consolas", 10))
        self.result_display.setStyleSheet("color: #4cc9f0;")
        buf_layout.addWidget(self.result_display)

        main_layout.addWidget(buffer_group)

        # 3. Function Pad
        pad_group = QGroupBox("Function Pad")
        pad_layout = QGridLayout(pad_group)

        functions = [
            ("bandwidth_3db", "bw()"),
            ("rise_time", "rise()"),
            ("propagation_delay", "delay()"),
            ("rms", "rms()"),
            ("peak_to_peak", "p2p()"),
            ("clip", "clip()"),
            ("deriv", "deriv()"),
            ("integ", "integ()"),
            ("eye_diagram", "eye()"),
        ]

        row, col = 0, 0
        for fname, label in functions:
            btn = QPushButton(label)
            btn.setToolTip(f"Insert {fname} function")
            btn.clicked.connect(lambda _, fn=fname: self._insert_function(fn))
            pad_layout.addWidget(btn, row, col)
            col += 1
            if col >= 3:
                col = 0
                row += 1

        main_layout.addWidget(pad_group)

        # 4. Action Buttons
        act_layout = QHBoxLayout()

        btn_eval = QPushButton("Evaluate & Plot")
        btn_eval.setStyleSheet("background-color: #4361ee; color: white; font-weight: bold; padding: 6px;")
        btn_eval.clicked.connect(self._evaluate)
        act_layout.addWidget(btn_eval)

        btn_push = QPushButton("Push to ADE Outputs")
        btn_push.clicked.connect(self._push_to_ade)
        act_layout.addWidget(btn_push)

        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(lambda: self.expr_edit.clear())
        act_layout.addWidget(btn_clear)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        act_layout.addWidget(btn_close)

        main_layout.addLayout(act_layout)

    def _on_vt_clicked(self):
        sig = self.sig_combo.currentText()
        if sig:
            self.expr_edit.insert(f'v("{sig}")')

    def _on_it_clicked(self):
        sig = self.sig_combo.currentText()
        if sig:
            self.expr_edit.insert(f'i("{sig}")')

    def _on_vf_clicked(self):
        sig = self.sig_combo.currentText()
        if sig:
            self.expr_edit.insert(f'vf("{sig}")')

    def _insert_function(self, fname: str):
        sig = self.sig_combo.currentText() or "net"
        if fname in ("bandwidth_3db", "rise_time", "rms", "peak_to_peak", "deriv", "integ"):
            self.expr_edit.setText(f'{fname}("{sig}")')
        elif fname == "clip":
            self.expr_edit.setText(f'clip("{sig}", 0, 10n)')
        elif fname == "propagation_delay":
            self.expr_edit.setText(f'propagation_delay("in", "{sig}")')
        elif fname == "eye_diagram":
            self.expr_edit.setText(f'eye_diagram("{sig}", 1n)')

    def _evaluate(self):
        expr = self.expr_edit.text().strip()
        if not expr:
            return

        if not self.calc:
            QMessageBox.warning(self, "No Data", "No simulation waveforms loaded in Calculator.")
            return

        try:
            # Safe evaluation against WaveformCalculator instance methods
            sig = self.sig_combo.currentText()
            if "bandwidth_3db" in expr:
                res = self.calc.bandwidth_3db(sig)
                self.result_display.setText(f"Result (3dB BW): {res:.4e} Hz")
            elif "rise_time" in expr:
                res = self.calc.rise_time(sig)
                self.result_display.setText(f"Result (Rise Time): {res * 1e9:.4f} ns")
            elif "propagation_delay" in expr:
                res = self.calc.propagation_delay("in", sig)
                self.result_display.setText(f"Result (Delay): {res * 1e9:.4f} ns")
            elif "deriv" in expr:
                res_vec = self.calc.deriv(sig)
                self.result_display.setText(f"Result: Derived vector with {len(res_vec)} points")
                self.expression_evaluated.emit(expr, res_vec)
            elif "integ" in expr:
                res_vec = self.calc.integ(sig)
                self.result_display.setText(f"Result: Integrated vector with {len(res_vec)} points")
                self.expression_evaluated.emit(expr, res_vec)
            else:
                vec = self.calc.v(sig)
                self.result_display.setText(f"Result: Signal '{sig}' peak-to-peak: {vec.peak_to_peak():.4f}")
        except Exception as err:
            self.result_display.setText(f"Error: {err}")

    def _push_to_ade(self):
        expr = self.expr_edit.text().strip()
        if expr:
            self.expression_pushed_to_ade.emit(expr)
            QMessageBox.information(self, "Pushed", f"Expression '{expr}' pushed to ADE Outputs.")
