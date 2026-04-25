from PySide6.QtWidgets import (QDialog, QHBoxLayout, QVBoxLayout, QListWidget, 
                                 QLabel, QFrame, QPushButton, QSplitter, QLineEdit, QCheckBox)
from PySide6.QtGui import QFont, QIcon
from PySide6.QtCore import Qt, Signal

class LibraryManager(QDialog):
    # Signal to tell the CIW to open a specific cell/view
    open_view_requested = Signal(str, str, str) # lib, cell, view

    def __init__(self, parent=None, theme="dark"):
        super().__init__(parent)
        self.setWindowTitle("Lumen Library Manager")
        self.resize(900, 600)
        self.theme = theme
        
        # Main Layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(2)
        
        # --- Top Menu/Toolbar Bar ---
        top_bar = QHBoxLayout()
        self.new_lib_btn = QPushButton("Edit")
        self.view_btn = QPushButton("View")
        self.design_btn = QPushButton("Design")
        
        for btn in [self.new_lib_btn, self.view_btn, self.design_btn]:
            btn.setFixedWidth(70)
            top_bar.addWidget(btn)
        
        top_bar.addStretch()
        self.category_cb = QCheckBox("Show Categories")
        top_bar.addWidget(self.category_cb)
        main_layout.addLayout(top_bar)

        # --- The 3-Column Splitter ---
        self.splitter = QSplitter(Qt.Horizontal)
        
        # Column 1: Library
        self.lib_col = self.create_refined_column("Library")
        self.lib_list = self.lib_col['list']
        self.lib_search = self.lib_col['search']
        
        # Column 2: Cell
        self.cell_col = self.create_refined_column("Cell")
        self.cell_list = self.cell_col['list']
        self.cell_search = self.cell_col['search']
        
        # Column 3: View
        self.view_col = self.create_refined_column("View")
        self.view_list = self.view_col['list']
        self.view_search = self.view_col['search']

        main_layout.addWidget(self.splitter)

        # --- Bottom Message Bar ---
        self.status_frame = QFrame()
        self.status_frame.setFrameShape(QFrame.StyledPanel)
        status_layout = QHBoxLayout(self.status_frame)
        status_layout.setContentsMargins(5, 2, 5, 2)
        
        self.status_label = QLabel("Messages: Select a library to begin.")
        status_layout.addWidget(self.status_label)
        main_layout.addWidget(self.status_frame)

        # Mock Data
        self.load_mock_data()

        # Connections
        self.lib_list.itemClicked.connect(self.on_lib_clicked)
        self.cell_list.itemClicked.connect(self.on_cell_clicked)
        self.view_list.itemDoubleClicked.connect(self.on_view_double_clicked)
        
        # Basic filtering logic
        self.lib_search.textChanged.connect(lambda t: self.filter_list(self.lib_list, t))
        self.cell_search.textChanged.connect(lambda t: self.filter_list(self.cell_list, t))
        self.view_search.textChanged.connect(lambda t: self.filter_list(self.view_list, t))

        self.apply_theme()

    def create_refined_column(self, title):
        container = QFrame()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        
        # Header
        header = QLabel(title)
        header.setStyleSheet("font-weight: bold; font-size: 10pt;")
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)
        
        # Search Bar
        search = QLineEdit()
        search.setPlaceholderText(f"Filter {title}...")
        search.setFixedHeight(22)
        layout.addWidget(search)
        
        # List
        lst = QListWidget()
        layout.addWidget(lst)
        
        self.splitter.addWidget(container)
        return {'list': lst, 'search': search}

    def filter_list(self, list_widget, text):
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            item.setHidden(text.lower() not in item.text().lower())

    def load_mock_data(self):
        libs = [
            "📂 analogLib", 
            "📂 sky130_fd_pr", 
            "📂 Lumen_Logic", 
            "📂 My_Design_Lib", 
            "📂 basic",
            "📂 ihp_open_pdk"
        ]
        self.lib_list.addItems(libs)

    def on_lib_clicked(self, item):
        self.cell_list.clear()
        self.view_list.clear()
        lib_name = item.text().replace("📂 ", "")
        self.status_label.setText(f"Library: {lib_name}")
        
        if "sky130" in lib_name:
            cells = ["晶 nfet_01v8", "晶 pfet_01v8", "晶 nfet_g5v0", "🧱 res_high_po", "🧱 cap_mim_m3"]
        elif "analogLib" in lib_name:
            cells = ["🧱 res", "🧱 cap", "🧱 ind", "⚡ vsource", "⚡ isource", "⏚ gnd"]
        else:
            cells = ["📦 opamp", "📦 bandgap", "📦 dac_8bit", "📦 test_bench_01"]
        
        self.cell_list.addItems(cells)

    def on_cell_clicked(self, item):
        self.view_list.clear()
        views = ["📝 schematic", "👁 symbol", "🏗 layout", "📉 spectre"]
        self.view_list.addItems(views)

    def on_view_double_clicked(self, item):
        lib = self.lib_list.currentItem().text().replace("📂 ", "")
        cell = self.cell_list.currentItem().text().split(" ")[1]
        view = item.text().split(" ")[1]
        self.open_view_requested.emit(lib, cell, view)

    def apply_theme(self):
        if self.theme == "dark":
            self.setStyleSheet("""
                QDialog { background-color: #2b2b2b; color: #e0e0e0; }
                QListWidget { 
                    background-color: #1e1e1e; 
                    color: #dcdcdc; 
                    border: 1px solid #444;
                    padding: 5px;
                }
                QListWidget::item:selected { background-color: #4b6eaf; color: white; }
                QLineEdit { 
                    background-color: #3c3f41; 
                    color: white; 
                    border: 1px solid #555; 
                    border-radius: 2px;
                }
                QPushButton {
                    background-color: #444;
                    color: #eee;
                    border: 1px solid #555;
                    padding: 4px;
                    border-radius: 2px;
                }
                QPushButton:hover { background-color: #555; }
                QLabel { color: #aaa; }
                QSplitter::handle { background-color: #444; }
                QCheckBox { color: #aaa; }
            """)
        else:
            self.setStyleSheet("""
                QDialog { background-color: #f0f0f0; color: #000; }
                QListWidget { 
                    background-color: #ffffff; 
                    color: #333; 
                    border: 1px solid #ccc;
                    padding: 5px;
                }
                QListWidget::item:selected { background-color: #0078d7; color: white; }
                QLineEdit { 
                    background-color: #ffffff; 
                    color: #000; 
                    border: 1px solid #aaa; 
                    border-radius: 2px;
                }
                QPushButton {
                    background-color: #e1e1e1;
                    color: #000;
                    border: 1px solid #ccc;
                    padding: 4px;
                    border-radius: 2px;
                }
                QPushButton:hover { background-color: #d0d0d0; }
                QLabel { color: #333; }
                QSplitter::handle { background-color: #ccc; }
                QCheckBox { color: #333; }
            """)
