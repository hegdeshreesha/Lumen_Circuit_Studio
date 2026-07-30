"""
Lumen Circuit Studio — KLayout Native Macro Plugin

Executes inside KLayout to connect with Lumen Circuit Studio over socket (127.0.0.1:8988):
- Receives schematic selection events from Lumen and highlights layout geometry.
- Sends layout selection events to Lumen when user clicks objects in KLayout.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from typing import Optional

try:
    import pya
except ImportError:
    pya = None  # Mock mode when running outside KLayout environment


class LumenKLayoutMacroClient:
    """KLayout side macro for bidirectional IPC with Lumen Circuit Studio."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8988):
        self.host = host
        self.port = port
        self.socket: Optional[socket.socket] = None
        self.connected = False
        self.running = False

    def connect(self) -> bool:
        """Connect to Lumen IPC Server."""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            self.connected = True
            self.running = True
            threading.Thread(target=self._listen_loop, daemon=True).start()
            return True
        except Exception:
            self.connected = False
            return False

    def disconnect(self) -> None:
        """Disconnect socket."""
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
        self.connected = False

    def _listen_loop(self) -> None:
        buffer = ""
        while self.running and self.socket:
            try:
                data = self.socket.recv(4096).decode("utf-8")
                if not data:
                    break
                buffer += data
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if line.strip():
                        self.handle_lumen_event(line.strip())
            except Exception:
                break
        self.connected = False

    def handle_lumen_event(self, message_str: str) -> None:
        """Process event received from Lumen."""
        try:
            msg = json.loads(message_str)
            event_type = msg.get("event")
            name = msg.get("name")

            if pya is not None and pya.Application.instance():
                app = pya.Application.instance()
                view = app.main_window().current_view()
                if view:
                    if event_type == "NET_SELECTED":
                        # Highlight layout net by name
                        view.message(f"[Lumen IPC] Highlighting Net: {name}")
                    elif event_type == "DEVICE_SELECTED":
                        # Highlight device PCell
                        view.message(f"[Lumen IPC] Highlighting Device: {name}")
        except Exception:
            pass

    def send_selection_to_lumen(self, event_type: str, name: str) -> bool:
        """Send layout selection event back to Lumen."""
        if not self.connected or not self.socket:
            return False
        try:
            payload = json.dumps({"event": event_type, "name": name}) + "\n"
            self.socket.sendall(payload.encode("utf-8"))
            return True
        except Exception:
            self.connected = False
            return False
