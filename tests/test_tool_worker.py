import unittest
from unittest.mock import patch

from desktop_app.tool_worker import ToolPollConfig, ToolPollWorker


def make_config():
    return ToolPollConfig(
        host="127.0.0.1",
        port=502,
        unit_id=1,
        status_register=100,
        trigger_register=53,
        direction_register=54,
        timeout_seconds=1.0,
        poll_interval_ms=800,
        lock_register=4,
        lock_value=2,
        command_delay_ms=0,
    )


class FakeConnectedClient:
    def __init__(self):
        self.values = {54: 0, 53: 1, 100: 2}
        self.reads = []
        self.writes = []
        self.disconnected = False

    def is_connected(self):
        return not self.disconnected

    def read_register(self, address):
        self.reads.append(address)
        return self.values[address]

    def write_register(self, address, value):
        self.writes.append((address, value))

    def disconnect(self):
        self.disconnected = True


class FakeDisconnectedClient:
    def __init__(self):
        self.connect_attempts = 0

    def is_connected(self):
        return False

    def ensure_connected(self):
        self.connect_attempts += 1
        raise ConnectionRefusedError("offline")

    def disconnect(self):
        pass


class ToolPollWorkerTest(unittest.TestCase):
    def test_poll_reuses_worker_client_for_all_business_registers(self):
        worker = ToolPollWorker(make_config())
        client = FakeConnectedClient()
        worker.client = client
        worker.polling = True
        results = []
        worker.result.connect(lambda status, trigger, direction: results.append((status, trigger, direction)))

        worker.poll_once()

        self.assertEqual(client.reads, [54, 53, 100])
        self.assertEqual(results, [(2, 1, 0)])

    def test_stop_locks_tool_then_disconnects_long_connection(self):
        worker = ToolPollWorker(make_config())
        client = FakeConnectedClient()
        worker.client = client
        worker.polling = True

        worker.stop()

        self.assertEqual(client.writes, [(4, 2)])
        self.assertTrue(client.disconnected)
        self.assertFalse(worker.polling)

    def test_failed_reconnect_is_throttled(self):
        worker = ToolPollWorker(make_config())
        client = FakeDisconnectedClient()
        worker.client = client
        worker.polling = True

        worker.poll_once()
        worker.poll_once()

        self.assertEqual(client.connect_attempts, 1)

    def test_write_command_waits_configured_delay_inside_worker(self):
        config = make_config()
        config.command_delay_ms = 50
        worker = ToolPollWorker(config)
        client = FakeConnectedClient()
        worker.client = client
        worker.polling = True

        with patch("desktop_app.tool_worker.sleep") as sleep_mock:
            worker.write_register(53, 0)

        sleep_mock.assert_called_once_with(0.05)
        self.assertEqual(client.writes, [(53, 0)])


if __name__ == "__main__":
    unittest.main()
