"""
Lumen Circuit Studio — PDK Manager Window

Virtuoso-style PDK browser and configuration. Select active PDK,
browse devices, layers, corners, and install/configure PDK data.
"""
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget,
    QLabel, QPushButton, QStatusBar, QToolBar, QGroupBox,
    QTreeWidget, QTreeWidgetItem, QMessageBox, QComboBox
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QAction, QColor, QBrush, QFont

from lumen.core.pdk_unified import PDKRegistry, PDKInfo
from lumen.gui.branding import apply_window_branding


class PDKManagerWindow(QMainWindow):
    """PDK Manager — browse and select process design kits."""

    HIDDEN_PDKS = {"sky130", "gf180mcu"}

    CATEGORY_ICONS = {
        "MOSFET": "⊞", "Resistor": "⏚", "Capacitor": "⊟",
        "Diode": "◮", "BJT": "⊳", "Inductor": "∿",
    }

    def __init__(self, registry: PDKRegistry, ciw=None, parent=None):
        super().__init__(parent)
        self.registry = registry
        self.ciw = ciw
        self.setWindowTitle("Lumen — PDK Manager")
        apply_window_branding(self)
        self.setMinimumSize(1000, 650)
        self.resize(1150, 720)

        self._build_ui()
        self._create_toolbar()
        self._create_status_bar()
        self._refresh()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)

        # PDK selector row
        sel_layout = QHBoxLayout()
        sel_layout.addWidget(QLabel("Active PDK:"))
        self.pdk_combo = QComboBox()
        self.pdk_combo.setMinimumWidth(300)
        self.pdk_combo.currentIndexChanged.connect(self._on_pdk_changed)
        sel_layout.addWidget(self.pdk_combo)

        self.activate_btn = QPushButton("Set Active")
        self.activate_btn.clicked.connect(self._on_activate)
        sel_layout.addWidget(self.activate_btn)

        self.install_btn = QPushButton("Install")
        self.install_btn.clicked.connect(self._on_install)
        sel_layout.addWidget(self.install_btn)

        sel_layout.addStretch()
        layout.addLayout(sel_layout)

        # Info + tabs
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: PDK info
        info_panel = QWidget()
        info_layout = QVBoxLayout(info_panel)
        info_layout.setContentsMargins(0, 0, 0, 0)

        self.info_group = QGroupBox("PDK Information")
        info_form = QVBoxLayout(self.info_group)
        self.info_labels = {}
        for field in ["Foundry", "Process", "Node", "VDD", "Temp Range",
                       "Version", "License", "Status"]:
            row = QHBoxLayout()
            lbl = QLabel(f"{field}:")
            lbl.setFixedWidth(80)
            lbl.setStyleSheet("font-weight:bold;background:transparent;")
            val = QLabel("—")
            val.setStyleSheet("background:transparent;")
            val.setWordWrap(True)
            row.addWidget(lbl)
            row.addWidget(val, stretch=1)
            info_form.addLayout(row)
            self.info_labels[field] = val

        self.desc_label = QLabel()
        self.desc_label.setWordWrap(True)
        self.desc_label.setStyleSheet("color:#808080;background:transparent;padding:8px 0;")
        info_form.addWidget(self.desc_label)
        info_form.addStretch()
        info_layout.addWidget(self.info_group)
        splitter.addWidget(info_panel)

        # Right: detail tabs
        self.detail_tabs = QTabWidget()

        # Devices tab
        self.device_table = QTableWidget(0, 5)
        self.device_table.setHorizontalHeaderLabels(
            ["Device", "Category", "Model", "Description", "Params"])
        self.device_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.device_table.verticalHeader().setVisible(False)
        self.device_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self.detail_tabs.addTab(self.device_table, "Devices")

        # Layers tab
        self.layer_table = QTableWidget(0, 5)
        self.layer_table.setHorizontalHeaderLabels(
            ["Layer", "GDS #", "Datatype", "Purpose", "Color"])
        self.layer_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.layer_table.verticalHeader().setVisible(False)
        self.detail_tabs.addTab(self.layer_table, "Layers")

        # Corners tab
        self.corner_table = QTableWidget(0, 3)
        self.corner_table.setHorizontalHeaderLabels(
            ["Corner", "Description", "Temperature"])
        self.corner_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.corner_table.verticalHeader().setVisible(False)
        self.detail_tabs.addTab(self.corner_table, "Corners")

        splitter.addWidget(self.detail_tabs)
        splitter.setSizes([320, 700])
        layout.addWidget(splitter)

    def _create_toolbar(self):
        tb = QToolBar("PDK")
        tb.setIconSize(QSize(18, 18))
        act_refresh = QAction("Refresh", self)
        act_refresh.triggered.connect(self._refresh)
        tb.addAction(act_refresh)
        act_close = QAction("Close", self)
        act_close.triggered.connect(self.close)
        tb.addAction(act_close)
        self.addToolBar(tb)

    def _create_status_bar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.status_label = QLabel()
        self.status_label.setStyleSheet("color:#ffffff;padding:0 8px;")
        sb.addWidget(self.status_label)

    def _refresh(self):
        """Reload PDK list."""
        self.pdk_combo.blockSignals(True)
        self.pdk_combo.clear()
        active = self.registry.get_active_name()
        select_idx = 0
        pdks = [
            pdk for pdk in self.registry.get_all_pdks()
            if pdk.name not in self.HIDDEN_PDKS
        ]
        for i, pdk in enumerate(pdks):
            status = "✓" if pdk.installed else "○"
            self.pdk_combo.addItem(
                f"{status} {pdk.display_name} ({pdk.node})", pdk.name)
            if pdk.name == active:
                select_idx = i
        self.pdk_combo.setCurrentIndex(select_idx)
        self.pdk_combo.blockSignals(False)
        self._on_pdk_changed(select_idx)

        count = len(pdks)
        self.status_label.setText(
            f"{count} PDKs available | Active: {active or 'None'}")

    def _on_pdk_changed(self, index):
        """Update display for selected PDK."""
        name = self.pdk_combo.currentData()
        if not name:
            return
        pdk = self.registry.get_pdk(name)
        if not pdk:
            return

        # Update info panel
        self.info_labels["Foundry"].setText(pdk.foundry)
        self.info_labels["Process"].setText(pdk.process)
        self.info_labels["Node"].setText(pdk.node)
        self.info_labels["VDD"].setText(f"{pdk.supply_voltage}V")
        self.info_labels["Temp Range"].setText(
            f"{pdk.temperature_range[0]}°C to {pdk.temperature_range[1]}°C")
        self.info_labels["Version"].setText(pdk.version)
        self.info_labels["License"].setText(pdk.license)

        if pdk.installed:
            self.info_labels["Status"].setText("✓ Installed")
            self.info_labels["Status"].setStyleSheet(
                "color:#8bc78b;background:transparent;")
        else:
            self.info_labels["Status"].setText("○ Not Installed")
            self.info_labels["Status"].setStyleSheet(
                "color:#cc8888;background:transparent;")

        active = self.registry.get_active_name()
        if name == active:
            self.info_group.setTitle(f"PDK Information  ★ ACTIVE")
        else:
            self.info_group.setTitle("PDK Information")

        self.desc_label.setText(pdk.description)

        # Update devices table
        self._populate_devices(pdk)
        self._populate_layers(pdk)
        self._populate_corners(pdk)

    def _populate_devices(self, pdk: PDKInfo):
        devs = pdk.devices
        self.device_table.setRowCount(len(devs))
        for row, dev in enumerate(devs):
            category = dev.category.value if hasattr(dev.category, "value") else str(dev.category)
            icon = self.CATEGORY_ICONS.get(category, "?")
            name_item = QTableWidgetItem(f"{icon} {dev.name}")
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            cat_item = QTableWidgetItem(category)
            cat_item.setFlags(cat_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            model_item = QTableWidgetItem(dev.model)
            model_item.setFlags(model_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            model_item.setForeground(QBrush(QColor("#6b9ece")))

            desc_item = QTableWidgetItem(dev.description)
            desc_item.setFlags(desc_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            if isinstance(dev.parameters, dict):
                params = ", ".join(f"{k}={v}" for k, v in dev.parameters.items())
            else:
                params = ", ".join(
                    f"{p.name}={p.default}" for p in dev.parameters if hasattr(p, "name")
                )
            param_item = QTableWidgetItem(params)
            param_item.setFlags(param_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            param_item.setForeground(QBrush(QColor("#808080")))

            self.device_table.setItem(row, 0, name_item)
            self.device_table.setItem(row, 1, cat_item)
            self.device_table.setItem(row, 2, model_item)
            self.device_table.setItem(row, 3, desc_item)
            self.device_table.setItem(row, 4, param_item)

    def _populate_layers(self, pdk: PDKInfo):
        layers = pdk.layers
        self.layer_table.setRowCount(len(layers))
        for row, lyr in enumerate(layers):
            if isinstance(lyr, dict):
                layer_name = lyr.get("name", "")
                gds_number = lyr.get("gds_number", lyr.get("gds", 0))
                gds_datatype = lyr.get("gds_datatype", lyr.get("datatype", 0))
                purpose = lyr.get("purpose", "")
                color = lyr.get("color", "#808080")
            else:
                layer_name = lyr.name
                gds_number = lyr.gds_number
                gds_datatype = lyr.gds_datatype
                purpose = lyr.purpose
                color = lyr.color

            name_item = QTableWidgetItem(layer_name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name_item.setForeground(QBrush(QColor(color)))
            font = name_item.font()
            font.setBold(True)
            name_item.setFont(font)

            gds_item = QTableWidgetItem(str(gds_number))
            gds_item.setFlags(gds_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            dt_item = QTableWidgetItem(str(gds_datatype))
            dt_item.setFlags(dt_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            purpose_item = QTableWidgetItem(purpose)
            purpose_item.setFlags(purpose_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            color_item = QTableWidgetItem(f"####  {color}")
            color_item.setForeground(QBrush(QColor(color)))
            color_item.setFlags(color_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self.layer_table.setItem(row, 0, name_item)
            self.layer_table.setItem(row, 1, gds_item)
            self.layer_table.setItem(row, 2, dt_item)
            self.layer_table.setItem(row, 3, purpose_item)
            self.layer_table.setItem(row, 4, color_item)

    def _populate_corners(self, pdk: PDKInfo):
        corners = pdk.corners
        self.corner_table.setRowCount(len(corners))
        for row, corner in enumerate(corners):
            if isinstance(corner, dict):
                cname = corner.get("name", "")
                cdesc = corner.get("description", "")
                ctemp = corner.get("temp", corner.get("temperature", 25))
            else:
                cname = corner.name
                cdesc = corner.description
                ctemp = corner.temperature

            name_item = QTableWidgetItem(cname)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            font = name_item.font()
            font.setBold(True)
            name_item.setFont(font)

            desc_item = QTableWidgetItem(cdesc)
            desc_item.setFlags(desc_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            temp_item = QTableWidgetItem(f"{ctemp} C")
            temp_item.setFlags(temp_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self.corner_table.setItem(row, 0, name_item)
            self.corner_table.setItem(row, 1, desc_item)
            self.corner_table.setItem(row, 2, temp_item)
    def _on_activate(self):
        name = self.pdk_combo.currentData()
        if not name:
            return
        pdk = self.registry.get_pdk(name)
        if not pdk.installed:
            reply = QMessageBox.question(
                self, "Install PDK",
                f"PDK '{pdk.display_name}' is not installed. Install now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self._do_install(name)
            else:
                return
        self.registry.set_active_pdk(name)
        self._refresh()
        if self.ciw:
            self.ciw.log(f"Active PDK set to: {pdk.display_name}")

    def _on_install(self):
        name = self.pdk_combo.currentData()
        if name:
            self._do_install(name)

    def _do_install(self, name: str):
        pdk = self.registry.get_pdk(name)
        if not pdk:
            return
        ok = self.registry.install_pdk(name)
        if ok:
            QMessageBox.information(
                self, "PDK Installed",
                f"PDK '{pdk.display_name}' installed to:\n{pdk.install_path}")
            if self.ciw:
                self.ciw.log(f"Installed PDK: {pdk.display_name}")
            self._refresh()
        else:
            QMessageBox.warning(self, "Error", "PDK installation failed.")
