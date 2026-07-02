import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent
from PyQt5.QtWidgets import QApplication

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
        poll_interval_ms=100,
        lock_register=4,
        lock_value=2,
        command_delay_ms=0,
    )


class FakeConnectedClient:
    def __init__(self):
        self.values = {54: 3, 53: 1, 100: 2}
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


class FakeWriteFailClient(FakeConnectedClient):
    def write_register(self, address, value):
        raise BrokenPipeError("write failed")


class ToolPollWorkerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def test_poll_reuses_worker_client_for_all_business_registers(self):
        worker = ToolPollWorker(make_config())
        client = FakeConnectedClient()
        worker.client = client
        worker.polling = True
        results = []
        worker.result.connect(lambda status, trigger, direction: results.append((status, trigger, direction)))

        worker.poll_once()

        self.assertEqual(client.reads, [54, 100, 53])
        self.assertEqual(results, [(2, 1, 3)])

        worker.poll_once()
        self.assertEqual(client.reads, [54, 100, 53, 54, 100, 53])
        self.assertEqual(results, [(2, 1, 3), (2, 1, 3)])

    def test_start_keeps_100ms_poll_timer_active(self):
        worker = ToolPollWorker(make_config())
        worker.client = FakeConnectedClient()

        worker.start()

        self.assertTrue(worker.polling)
        self.assertTrue(worker.timer.isActive())
        self.assertEqual(worker.timer.interval(), 100)
        worker.stop()

    def test_pending_status_temporarily_uses_fast_poll_interval(self):
        config = make_config()
        config.poll_interval_ms = 800
        config.final_status_poll_ms = 100
        worker = ToolPollWorker(config)
        client = FakeConnectedClient()
        client.values[100] = 1
        worker.client = client

        worker.start()

        self.assertTrue(worker.pending_result_active)
        self.assertEqual(worker.timer.interval(), 100)
        client.values[100] = 3
        worker.poll_once()
        self.assertFalse(worker.pending_result_active)
        self.assertEqual(worker.timer.interval(), 800)
        worker.stop()

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
        successes = []
        worker.write_succeeded.connect(lambda address, value: successes.append((address, value)))

        with patch("desktop_app.tool_worker.sleep") as sleep_mock:
            worker.write_register(53, 0)

        sleep_mock.assert_called_once_with(0.05)
        self.assertEqual(client.writes, [(53, 0)])
        self.assertEqual(successes, [(53, 0)])

    def test_write_failure_reports_register_for_retry(self):
        worker = ToolPollWorker(make_config())
        worker.client = FakeWriteFailClient()
        worker.polling = True
        errors = []
        worker.write_error.connect(
            lambda address, value, message: errors.append((address, value, message))
        )

        worker.write_register(53, 0)

        self.assertEqual(errors[0][:2], (53, 0))
        self.assertIn("write failed", errors[0][2])

    def test_degraded_bypass_stops_polling_and_writes_unlock(self):
        worker = ToolPollWorker(make_config())
        client = FakeConnectedClient()
        worker.client = client
        worker.polling = True
        results = []
        worker.bypass_changed.connect(
            lambda enabled, success, message: results.append(
                (enabled, success, message)
            )
        )

        worker.set_bypass(True)
        worker.poll_once()

        self.assertTrue(worker.bypass)
        self.assertEqual(client.writes, [(4, 1)])
        self.assertEqual(client.reads, [])
        self.assertEqual(results, [(True, True, "")])


if __name__ == "__main__":
    unittest.main()
