import unittest
import time
from lumen.core.klayout_ipc import KLayoutIPCServer
from lumen.klayout.lumen_klayout_client import LumenKLayoutMacroClient


class TestKLayoutClientPlugin(unittest.TestCase):
    def test_client_connection_and_event_exchange(self):
        server = KLayoutIPCServer(port=18989)
        self.assertTrue(server.start())

        received_at_server = []
        server.register_callback(lambda e: received_at_server.append(e))

        client = LumenKLayoutMacroClient(port=18989)
        self.assertTrue(client.connect())

        # Client sends layout selection to Lumen Server
        self.assertTrue(client.send_selection_to_lumen("NET_SELECTED", "net_vout"))

        time.sleep(0.2)
        self.assertEqual(len(received_at_server), 1)
        self.assertEqual(received_at_server[0].name, "net_vout")

        client.disconnect()
        server.stop()


if __name__ == "__main__":
    unittest.main()
