import socket
import struct
import threading
import unittest

from desktop_app.tool_client import ToolModbusClient


def receive_exact(conn, size):
    data = b""
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            raise ConnectionError("client disconnected")
        data += chunk
    return data


def receive_request(conn):
    return receive_exact(conn, 12)


def read_response(request, value):
    transaction_id, _, _, unit_id, function_code, _, _ = struct.unpack(">HHHBBHH", request)
    if function_code != 3:
        raise AssertionError(f"unexpected function code {function_code}")
    return struct.pack(">HHHBBBH", transaction_id, 0, 5, unit_id, 3, 2, value)


class ToolModbusClientTest(unittest.TestCase):
    def start_server(self, handler):
        ready = threading.Event()
        server_info = {}

        def server():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("127.0.0.1", 0))
                sock.listen(2)
                server_info["port"] = sock.getsockname()[1]
                ready.set()
                handler(sock)

        thread = threading.Thread(target=server, daemon=True)
        thread.start()
        self.assertTrue(ready.wait(2))
        return server_info, thread

    def test_read_register_handles_fragmented_response(self):
        def handler(sock):
            conn, _ = sock.accept()
            with conn:
                response = read_response(receive_request(conn), 258)
                conn.sendall(response[:4])
                conn.sendall(response[4:9])
                conn.sendall(response[9:])

        server_info, thread = self.start_server(handler)
        client = ToolModbusClient("127.0.0.1", server_info["port"], 1, timeout=1.0)

        self.assertEqual(client.read_register(100), 258)
        client.disconnect()
        thread.join(2)

    def test_multiple_requests_reuse_one_tcp_connection(self):
        accepts = []

        def handler(sock):
            conn, _ = sock.accept()
            accepts.append(1)
            with conn:
                for value in (54, 53, 100):
                    conn.sendall(read_response(receive_request(conn), value))

        server_info, thread = self.start_server(handler)
        client = ToolModbusClient("127.0.0.1", server_info["port"], 1, timeout=1.0)

        values = [client.read_register(address) for address in (54, 53, 100)]

        self.assertEqual(values, [54, 53, 100])
        self.assertEqual(len(accepts), 1)
        self.assertTrue(client.is_connected())
        client.disconnect()
        thread.join(2)

    def test_disconnect_marks_client_disconnected_and_next_read_reconnects(self):
        accepts = []

        def handler(sock):
            first, _ = sock.accept()
            accepts.append(1)
            with first:
                first.sendall(read_response(receive_request(first), 2))
            second, _ = sock.accept()
            accepts.append(1)
            with second:
                second.sendall(read_response(receive_request(second), 3))

        server_info, thread = self.start_server(handler)
        client = ToolModbusClient("127.0.0.1", server_info["port"], 1, timeout=1.0)

        self.assertEqual(client.read_register(100), 2)
        with self.assertRaises((ConnectionError, OSError, ValueError)):
            client.read_register(100)
        self.assertFalse(client.is_connected())
        self.assertEqual(client.read_register(100), 3)
        self.assertEqual(len(accepts), 2)
        client.disconnect()
        thread.join(2)

    def test_read_registers_returns_all_values(self):
        def handler(sock):
            conn, _ = sock.accept()
            with conn:
                request = receive_request(conn)
                transaction_id, _, _, unit_id, function_code, _, count = struct.unpack(
                    ">HHHBBHH", request
                )
                self.assertEqual((function_code, count), (3, 3))
                response = struct.pack(
                    ">HHHBBBHHH",
                    transaction_id,
                    0,
                    9,
                    unit_id,
                    3,
                    6,
                    10,
                    20,
                    30,
                )
                conn.sendall(response)

        server_info, thread = self.start_server(handler)
        client = ToolModbusClient("127.0.0.1", server_info["port"], 1, timeout=1.0)

        self.assertEqual(client.read_registers(53, 3), [10, 20, 30])
        client.disconnect()
        thread.join(2)


if __name__ == "__main__":
    unittest.main()
