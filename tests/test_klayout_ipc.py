import unittest
import socket
import json
import time
from lumen.core.klayout_ipc import KLayoutIPCServer, SelectionEvent


class TestKLayoutIPC(unittest.TestCase):
    def test_server_startup_and_event_broadcast(self):
        server = KLayoutIPCServer(port=18988)
        self.assertTrue(server.start())

        received_events = []
        server.register_callback(lambda e: received_events.append(e))

        # Connect a client socket to simulate KLayout
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(("127.0.0.1", 18988))

        # Send event from KLayout to Lumen
        payload = json.dumps({"event": "NET_SELECTED", "name": "VDD"}) + "\n"
        client.sendall(payload.encode("utf-8"))

        time.sleep(0.2)
        self.assertEqual(len(received_events), 1)
        self.assertEqual(received_events[0].name, "VDD")

        client.close()
        server.stop()


if __name__ == "__main__":
    unittest.main()
