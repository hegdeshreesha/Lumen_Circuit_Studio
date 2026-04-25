import sys
import datetime
from PySide6.QtWidgets import (QApplication, QMainWindow, QTextEdit, 
                               QLineEdit, QVBoxLayout, QWidget, QMenuBar, QMenu)
from PySide6.QtGui import QFont, QColor, QPalette
from PySide6.QtCore import Qt
from library_manager import LibraryManager
from schematic_editor import SchematicEditor

# --- THEMES ---
DARK_THEME = """
QMainWindow, QWidget {
    background-color: #2b2b2b;
    color: #e0e0e0;
}
QTextEdit {
    background-color: #1e1e1e;
    color: #dcdcdc;
    border: 1px solid #444;
}
QLineEdit {
    background-color: #3c3f41;
    color: #ffffff;
    border: 1px solid #555;
    padding: 3px;
}
QMenuBar {
    background-color: #333;
    color: #eee;
}
QMenuBar::item:selected {
    background-color: #444;
}
QMenu {
    background-color: #333;
    color: #eee;
    border: 1px solid #555;
}
QMenu::item:selected {
    background-color: #4b6eaf;
}
"""

LIGHT_THEME = """
QMainWindow, QWidget {
    background-color: #f5f5f5;
    color: #000000;
}
QTextEdit {
    background-color: #ffffff;
    color: #333333;
    border: 1px solid #ccc;
}
QLineEdit {
    background-color: #ffffff;
    color: #000000;
    border: 1px solid #aaa;
    padding: 3px;
}
QMenuBar {
    background-color: #e0e0e0;
    color: #000;
}
QMenu {
    background-color: #ffffff;
    color: #000;
}
"""

class LumenCIW(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lumen Circuit Studio - CIW")
        self.resize(800, 450)
        
        # Internal state
        self.is_dark_mode = True
        self.lib_manager = None
        self.editors = [] # Keep track of open schematic windows

        # Set up the main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(10, 10, 10, 10)

        # Log Output Area
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFont(QFont("Consolas", 11))
        layout.addWidget(self.log_area)

        # Command Entry Line
        self.cmd_input = QLineEdit()
        self.cmd_input.setFont(QFont("Consolas", 11))
        self.cmd_input.setPlaceholderText("Lumen> Type commands here...")
        self.cmd_input.returnPressed.connect(self.execute_command)
        layout.addWidget(self.cmd_input)

        self.build_menus()
        self.apply_theme()

        # Startup message
        self.log_message("<b>Lumen Circuit Studio v0.1</b>")
        self.log_message(f"<i>Session Started: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>")
        self.log_message("Type <b>ddsOpenLibManager()</b> to browse libraries.")

    def build_menus(self):
        menu_bar = self.menuBar()
        
        # File Menu
        file_menu = menu_bar.addMenu("File")
        file_menu.addAction("New CellView...")
        file_menu.addAction("Open...")
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close)

        # Tools Menu
        tools_menu = menu_bar.addMenu("Tools")
        tools_menu.addAction("Library Manager", self.open_library_manager)
        tools_menu.addAction("Schematic Editor", lambda: self.handle_open_view("Default", "untitled", "schematic"))

        # Options Menu
        options_menu = menu_bar.addMenu("Options")
        
        theme_menu = options_menu.addMenu("Theme")
        self.dark_action = theme_menu.addAction("Dark Mode", self.set_dark_mode)
        self.dark_action.setCheckable(True)
        self.dark_action.setChecked(True)
        
        self.light_action = theme_menu.addAction("Light Mode", self.set_light_mode)
        self.light_action.setCheckable(True)

    def open_library_manager(self):
        theme_str = "dark" if self.is_dark_mode else "light"
        self.lib_manager = LibraryManager(self, theme=theme_str)
        self.lib_manager.open_view_requested.connect(self.handle_open_view)
        self.lib_manager.show()
        self.log_message("ddsOpenLibManager() called.")

    def handle_open_view(self, lib, cell, view):
        self.log_message(f"Opening {lib} / {cell} / {view} ...")
        
        if view == "schematic":
            theme_str = "dark" if self.is_dark_mode else "light"
            editor = SchematicEditor(cell_name=cell, theme=theme_str)
            
            # Connect Debug Signal
            editor.view.debug_msg.connect(self.log_debug)
            
            editor.show()
            self.editors.append(editor)
        else:
            self.log_message(f"<span style='color: orange;'>Notice: Opening '{view}' view is not yet implemented.</span>")

    def set_dark_mode(self):
        self.is_dark_mode = True
        self.dark_action.setChecked(True)
        self.light_action.setChecked(False)
        self.apply_theme()
        if self.lib_manager: self.lib_manager.theme = "dark"; self.lib_manager.apply_theme()
        for ed in self.editors: ed.apply_theme("dark")
        self.log_message("Theme switched to Dark Mode.")

    def set_light_mode(self):
        self.is_dark_mode = False
        self.dark_action.setChecked(False)
        self.light_action.setChecked(True)
        self.apply_theme()
        if self.lib_manager: self.lib_manager.theme = "light"; self.lib_manager.apply_theme()
        for ed in self.editors: ed.apply_theme("light")
        self.log_message("Theme switched to Light Mode.")

    def apply_theme(self):
        if self.is_dark_mode:
            self.setStyleSheet(DARK_THEME)
        else:
            self.setStyleSheet(LIGHT_THEME)

    def log_message(self, message):
        self.log_area.append(message)
        self.log_area.verticalScrollBar().setValue(self.log_area.verticalScrollBar().maximum())

    def log_debug(self, message):
        # Professional debug log style
        timestamp = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
        self.log_message(f"<span style='color: #888;'>[{timestamp}] DEBUG: {message}</span>")

    def execute_command(self):
        cmd = self.cmd_input.text()
        if not cmd.strip(): return
        
        color = "#569cd6" if self.is_dark_mode else "blue"
        self.log_message(f"<span style='color: {color};'>Lumen> {cmd}</span>")
        self.cmd_input.clear()
        
        if cmd.lower() in ['exit', 'quit']:
            self.close()
        elif cmd.lower() == 'clear':
            self.log_area.clear()
        elif "ddsopenlibmanager" in cmd.lower():
            self.open_library_manager()
        else:
            self.log_message(f"<span style='color: #f44747;'>Error: Command '{cmd}' not found.</span>")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    ciw = LumenCIW()
    ciw.show()
    sys.exit(app.exec())
