import socket
import struct
import threading
import unittest

from desktop_app.tool_client import ToolModbusClient


class ToolModbusClientTest(unittest.TestCase):
    def test_read_register_handles_fragmented_response(self):
        ready = threading.Event()
        server_info = {}

        def server():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", 0))
                sock.listen(1)
                server_info["port"] = sock.getsockname()[1]
                ready.set()
                conn, _ = sock.accept()
                with conn:
                    request = conn.recv(1024)
                    transaction_id, _, _, unit_id, function_code, _, _ = struct.unpack(">HHHBBHH", request)
                    self.assertEqual(function_code, 3)
                    response = struct.pack(
                        ">HHHBBBH",
                        transaction_id,
                        0,
                        5,
                        unit_id,
                        3,
                        2,
                        258,
                    )
                    conn.sendall(response[:4])
                    conn.sendall(response[4:9])
                    conn.sendall(response[9:])

        thread = threading.Thread(target=server, daemon=True)
        thread.start()
        ready.wait(2)

        client = ToolModbusClient(timeout=1.0)
        value = client.read_register("127.0.0.1", server_info["port"], 1, 100)

        self.assertEqual(value, 258)
        thread.join(2)


if __name__ == "__main__":
    unittest.main()
