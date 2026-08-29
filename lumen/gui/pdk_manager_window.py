"""
Lumen Circuit Studio — PDK Manager Window

industry-style PDK browser and configuration. Select active PDK,
browse devices, layers, corners, and install/configure PDK data.
"""
from lumen.qt.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget,
    QLabel, QPushButton, QStatusBar, QToolBar, QGroupBox,
    QTreeWidget, QTreeWidgetItem, QMessageBox, QComboBox, QFileDialog,
    QInputDialog
)
from lumen.qt.QtCore import Qt, QSize
from lumen.qt.QtGui import QAction, QColor, QBrush, QFont

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

        self.register_btn = QPushButton("Register Folder...")
        self.register_btn.setToolTip("Register an already-installed local PDK folder")
        self.register_btn.clicked.connect(self._on_register_folder)
        sel_layout.addWidget(self.register_btn)

        self.install_open_btn = QPushButton("Install Open PDK...")
        self.install_open_btn.setToolTip("Clone a supported open PDK repository and register it")
        self.install_open_btn.clicked.connect(self._on_install_open_pdk)
        sel_layout.addWidget(self.install_open_btn)

        self.refresh_install_btn = QPushButton("Refresh Install")
        self.refresh_install_btn.setToolTip("Rescan model files, corners, and devices for the selected PDK")
        self.refresh_install_btn.clicked.connect(self._on_refresh_install)
        sel_layout.addWidget(self.refresh_install_btn)

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

        health_panel = QWidget()
        health_layout = QVBoxLayout(health_panel)
        health_layout.setContentsMargins(4, 4, 4, 4)
        health_actions = QHBoxLayout()
        rescan_btn = QPushButton("Rescan")
        rescan_btn.setToolTip("Rescan model files, corners, and devices for this PDK")
        rescan_btn.clicked.connect(self._on_refresh_install)
        health_actions.addWidget(rescan_btn)
        register_btn = QPushButton("Register Folder...")
        register_btn.setToolTip("Register or replace this PDK from a local folder")
        register_btn.clicked.connect(self._on_register_folder)
        health_actions.addWidget(register_btn)
        models_btn = QPushButton("Choose Models Folder...")
        models_btn.setToolTip("Repair model discovery by selecting the folder containing SPICE model files")
        models_btn.clicked.connect(self._on_choose_models_folder)
        health_actions.addWidget(models_btn)
        manifest_btn = QPushButton("Regenerate Manifest")
        manifest_btn.setToolTip("Rewrite lumen_pdk.json from the current discovered PDK data")
        manifest_btn.clicked.connect(self._on_regenerate_manifest)
        health_actions.addWidget(manifest_btn)
        health_actions.addStretch()
        health_layout.addLayout(health_actions)
        self.health_table = QTableWidget(0, 2)
        self.health_table.setHorizontalHeaderLabels(["Check", "Value"])
        self.health_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.health_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.health_table.verticalHeader().setVisible(False)
        health_layout.addWidget(self.health_table)
        self.detail_tabs.addTab(health_panel, "Health")

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
            if pdk.installed or pdk.name not in self.HIDDEN_PDKS
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
        self._populate_health(pdk)

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

    def _populate_health(self, pdk: PDKInfo):
        report = self.registry.get_pdk_health_report(pdk.name)
        rows = [
            ("Status", report.get("status", "Unknown")),
            ("Root", report.get("root_path", "")),
            ("Models Path", report.get("models_path", "")),
            ("Manifest", report.get("manifest_path", "")),
            ("Model Files", report.get("model_files_count", 0)),
            ("Model Sections", report.get("model_sections_count", 0)),
            ("Devices", report.get("devices_count", 0)),
            ("Corners", report.get("corners_count", 0)),
            ("Layers", report.get("layers_count", 0)),
            ("Issues", "; ".join(report.get("issues", [])) or "None"),
        ]
        self.health_table.setRowCount(len(rows))
        for row, (label, value) in enumerate(rows):
            label_item = QTableWidgetItem(str(label))
            label_item.setFlags(label_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            value_item = QTableWidgetItem(str(value))
            value_item.setFlags(value_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if label == "Status":
                value_item.setForeground(QBrush(QColor("#8bc78b" if value == "Ready" else "#ffd166")))
            self.health_table.setItem(row, 0, label_item)
            self.health_table.setItem(row, 1, value_item)

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

    def _on_register_folder(self):
        path = QFileDialog.getExistingDirectory(
            self,
            "Register Local PDK Folder",
            "",
        )
        if not path:
            return
        pdk = self.registry.register_local_pdk(path)
        if not pdk:
            QMessageBox.warning(self, "Register PDK", "Could not register that folder as a PDK.")
            return
        self._refresh()
        idx = self.pdk_combo.findData(pdk.name)
        if idx >= 0:
            self.pdk_combo.setCurrentIndex(idx)
        QMessageBox.information(
            self,
            "Register PDK",
            self._install_summary(pdk),
        )
        if self.ciw:
            self.ciw.log(f"Registered PDK: {pdk.display_name} ({pdk.root_path})")

    def _on_install_open_pdk(self):
        sources = self.registry.available_open_pdk_sources()
        labels = {
            f"{info.get('display_name', name)} ({name})": name
            for name, info in sources.items()
        }
        choice, ok = QInputDialog.getItem(
            self,
            "Install Open PDK",
            "PDK:",
            sorted(labels.keys()),
            0,
            False,
        )
        if not ok or not choice:
            return
        dest = QFileDialog.getExistingDirectory(
            self,
            "Choose Install Folder",
            str(self.registry.workspace / "pdks"),
        )
        if not dest:
            return
        name = labels[str(choice)]
        self.statusBar().showMessage(f"Installing {choice}...", 0)
        pdk = self.registry.install_open_pdk(name, dest)
        if not pdk:
            QMessageBox.warning(self, "Install Open PDK", "Clone/register failed. Check Git and network access.")
            self.statusBar().showMessage("Open PDK install failed", 5000)
            return
        self._refresh()
        idx = self.pdk_combo.findData(pdk.name)
        if idx >= 0:
            self.pdk_combo.setCurrentIndex(idx)
        QMessageBox.information(
            self,
            "Install Open PDK",
            self._install_summary(pdk),
        )
        if self.ciw:
            self.ciw.log(f"Installed open PDK: {pdk.display_name} ({pdk.root_path})")

    def _on_refresh_install(self):
        name = self.pdk_combo.currentData()
        if not name:
            return
        pdk = self.registry.refresh_pdk_installation(name)
        if not pdk:
            QMessageBox.warning(self, "Refresh PDK", "Could not rescan this PDK installation.")
            return
        self._refresh()
        idx = self.pdk_combo.findData(pdk.name)
        if idx >= 0:
            self.pdk_combo.setCurrentIndex(idx)
        report = self.registry.get_pdk_health_report(pdk.name)
        issues = report.get("issues", [])
        text = "Ready" if not issues else "Needs setup:\n" + "\n".join(f"- {issue}" for issue in issues[:8])
        QMessageBox.information(self, "Refresh PDK", text)
        if self.ciw:
            self.ciw.log(f"Refreshed PDK install: {pdk.display_name}")

    def _on_choose_models_folder(self):
        name = self.pdk_combo.currentData()
        if not name:
            return
        pdk = self.registry.get_pdk(name)
        start = getattr(pdk, "models_path", "") or getattr(pdk, "root_path", "") or ""
        path = QFileDialog.getExistingDirectory(self, "Choose PDK Models Folder", start)
        if not path:
            return
        repaired = self.registry.set_pdk_models_path(name, path)
        if not repaired:
            QMessageBox.warning(self, "Choose Models Folder", "Could not use that models folder.")
            return
        self._refresh()
        idx = self.pdk_combo.findData(repaired.name)
        if idx >= 0:
            self.pdk_combo.setCurrentIndex(idx)
        QMessageBox.information(self, "Choose Models Folder", self._install_summary(repaired))
        if self.ciw:
            self.ciw.log(f"Updated PDK models folder: {repaired.display_name} ({path})")

    def _on_regenerate_manifest(self):
        name = self.pdk_combo.currentData()
        if not name:
            return
        pdk = self.registry.refresh_pdk_installation(name)
        if not pdk:
            QMessageBox.warning(self, "Regenerate Manifest", "Could not regenerate this PDK manifest.")
            return
        QMessageBox.information(self, "Regenerate Manifest", self._install_summary(pdk))
        self._refresh()

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

    def _install_summary(self, pdk: PDKInfo) -> str:
        report = self.registry.get_pdk_health_report(pdk.name)
        issues = report.get("issues", []) or []
        lines = [
            f"Registered and activated: {pdk.display_name}",
            "",
            str(pdk.root_path),
            "",
            f"Models: {report.get('model_files_count', 0)}",
            f"Sections: {report.get('model_sections_count', 0)}",
            f"Devices: {report.get('devices_count', 0)}",
            f"Corners: {report.get('corners_count', 0)}",
            f"Manifest: {report.get('manifest_path', '') or 'None'}",
        ]
        if issues:
            lines.extend(["", "Needs setup:"])
            lines.extend(f"- {issue}" for issue in issues[:8])
        else:
            lines.extend(["", "Status: Ready"])
        return "\n".join(lines)
