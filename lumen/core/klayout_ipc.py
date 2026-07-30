"""
Lumen Circuit Studio — KLayout Bidirectional IPC Bridge

Enables live 2-way cross-probing between Lumen Schematic Canvas and KLayout window:
- Selecting schematic nets/instances highlights corresponding PCells/layout nets in KLayout.
- Selecting layout polygons/nets in KLayout highlights schematic nets/instances in Lumen.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional, Dict, Any


@dataclass
class SelectionEvent:
    event_type: str  # "NET_SELECTED", "DEVICE_SELECTED", "DRC_ERROR_SELECTED"
    name: str
    library: str = ""
    cell: str = ""
    details: Dict[str, Any] = None


class KLayoutIPCServer:
    """Lightweight JSON-RPC server for KLayout bidirectional cross-probing."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8988):
        self.host = host
        self.port = port
        self.server_socket: Optional[socket.socket] = None
        self.running = False
        self.connected_clients: list[socket.socket] = []
        self.event_callbacks: list[Callable[[SelectionEvent], None]] = []

    def register_callback(self, callback: Callable[[SelectionEvent], None]) -> None:
        """Register callback for incoming selection events from KLayout."""
        self.event_callbacks.append(callback)

    def start(self) -> bool:
        """Start listening thread."""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            self.running = True
            threading.Thread(target=self._listen_loop, daemon=True).start()
            return True
        except Exception:
            self.running = False
            return False

    def stop(self) -> None:
        """Stop IPC server."""
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass

    def _listen_loop(self) -> None:
        while self.running:
            try:
                self.server_socket.settimeout(1.0)
                client, _ = self.server_socket.accept()
                self.connected_clients.append(client)
                threading.Thread(target=self._client_loop, args=(client,), daemon=True).start()
            except socket.timeout:
                continue
            except Exception:
                break

    def _client_loop(self, client: socket.socket) -> None:
        buffer = ""
        while self.running:
            try:
                data = client.recv(4096).decode("utf-8")
                if not data:
                    break
                buffer += data
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if line.strip():
                        self._process_message(line.strip())
            except Exception:
                break
        if client in self.connected_clients:
            self.connected_clients.remove(client)

    def _process_message(self, message: str) -> None:
        try:
            payload = json.loads(message)
            event = SelectionEvent(
                event_type=payload.get("event", "UNKNOWN"),
                name=payload.get("name", ""),
                library=payload.get("library", ""),
                cell=payload.get("cell", ""),
                details=payload.get("details", {}),
            )
            for cb in self.event_callbacks:
                cb(event)
        except Exception:
            pass

    def broadcast_selection(self, event_type: str, name: str, details: Dict[str, Any] = None) -> None:
        """Send selection event to KLayout."""
        msg = json.dumps({
            "event": event_type,
            "name": name,
            "details": details or {},
            "timestamp": time.time(),
        }) + "\n"
        dead_clients = []
        for client in self.connected_clients:
            try:
                client.sendall(msg.encode("utf-8"))
            except Exception:
                dead_clients.append(client)
        for dead in dead_clients:
            if dead in self.connected_clients:
                self.connected_clients.remove(dead)
