import struct
import tempfile
import unittest
from pathlib import Path

from shared.plc_magnet_flow import (
    PlcMagnetConfig,
    PlcMagnetFlowController,
    parse_plc_magnet_block,
)
from web_admin_app import database, services
from web_admin_app.admin_page import HTML


def sample_block(left_result=1, right_result=1):
    raw = bytearray(26)
    for offset, value in (
        (0, 1),
        (2, 1),
        (4, 1),
        (6, 1),
        (8, 0),
        (14, 78),
        (16, left_result),
        (22, 78),
        (24, right_result),
    ):
        raw[offset:offset + 2] = int(value).to_bytes(2, "big")
    raw[10:14] = struct.pack(">f", 12.5)
    raw[18:22] = struct.pack(">f", -3.25)
    return bytes(raw)


class FakeMagnetClient:
    def __init__(self, raw=None, values=None, failed_readbacks=None):
        self.raw = raw or sample_block()
        self.values = {0: 1, 2: 1, 4: 1, 6: 1, 8: 1}
        self.values.update(values or {})
        self.writes = []
        self.read_blocks = []
        self.connected = False
        self.failed_readbacks = set(failed_readbacks or ())

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def write_word(self, db, offset, value):
        self.writes.append((db, offset, value))
        self.values[offset] = value

    def read_word(self, db, offset):
        if offset in self.failed_readbacks:
            return 0
        return self.values.get(offset, 0)

    def read_bytes(self, db, start, size):
        self.read_blocks.append((db, start, size))
        return self.raw[:size]


class AdvancingClock:
    def __init__(self, step=0.1):
        self.value = 0.0
        self.step = step

    def __call__(self):
        value = self.value
        self.value += self.step
        return value


class PlcMagnetFlowTest(unittest.TestCase):
    def controller(self, client, config=None, clock=None):
        return PlcMagnetFlowController(
            client,
            config or PlcMagnetConfig(),
            sleep_func=lambda seconds: None,
            monotonic_func=clock or AdvancingClock(),
        )

    def test_full_flow_writes_one_reads_26_bytes_and_finishes(self):
        client = FakeMagnetClient()
        result = self.controller(client).run()
        self.assertTrue(result["ok"])
        self.assertEqual(
            client.writes,
            [(221, 0, 1), (221, 4, 1), (221, 8, 1)],
        )
        self.assertEqual(client.read_blocks, [(221, 0, 26)])
        self.assertAlmostEqual(result["left_flux"], 12.5)
        self.assertAlmostEqual(result["right_flux"], -3.25)
        self.assertEqual(result["left_result"], 1)
        self.assertEqual(result["right_result"], 1)

    def test_ng_result_never_writes_dbw8(self):
        client = FakeMagnetClient(raw=sample_block(right_result=0))
        result = self.controller(client).run()
        self.assertFalse(result["ok"])
        self.assertEqual(result["result"], "NG")
        self.assertNotIn((221, 8, 1), client.writes)

    def test_wait_timeout_does_not_continue(self):
        config = PlcMagnetConfig(
            plc_timeout_seconds=1,
            plc_poll_interval_ms=100,
        )
        client = FakeMagnetClient(values={2: 0})
        with self.assertRaisesRegex(TimeoutError, "气缸夹紧超时"):
            self.controller(
                client,
                config,
                AdvancingClock(0.6),
            ).run()
        self.assertEqual(client.writes, [(221, 0, 1)])

    def test_dbw0_readback_failure_stops_flow(self):
        client = FakeMagnetClient(failed_readbacks={0})
        with self.assertRaisesRegex(RuntimeError, "DBW0"):
            self.controller(client).run()
        self.assertEqual(client.writes, [(221, 0, 1)])

    def test_magnet_complete_timeout_does_not_read_results(self):
        config = PlcMagnetConfig(
            plc_timeout_seconds=1,
            plc_poll_interval_ms=100,
        )
        client = FakeMagnetClient(values={6: 0})
        with self.assertRaisesRegex(TimeoutError, "磁通量检测完成信号超时"):
            self.controller(
                client,
                config,
                AdvancingClock(0.3),
            ).run()
        self.assertEqual(client.read_blocks, [])
        self.assertNotIn((221, 8, 1), client.writes)

    def test_dbw8_readback_failure_does_not_report_success(self):
        client = FakeMagnetClient(failed_readbacks={8})
        with self.assertRaisesRegex(RuntimeError, "DBW8"):
            self.controller(client).run()
        self.assertIn((221, 8, 1), client.writes)

    def test_progress_contains_every_production_stage(self):
        progress = []
        client = FakeMagnetClient()
        controller = PlcMagnetFlowController(
            client,
            PlcMagnetConfig(),
            progress=lambda stage, data: progress.append(stage),
            sleep_func=lambda seconds: None,
            monotonic_func=AdvancingClock(),
        )
        controller.run()
        for stage in (
            "connection",
            "barcode_ok",
            "cylinder_clamped",
            "screw_complete",
            "magnet_complete",
            "magnet_result",
            "mes_read_done",
        ):
            self.assertIn(stage, progress)

    def test_parser_requires_complete_26_byte_block(self):
        with self.assertRaisesRegex(ValueError, "数据长度不足"):
            parse_plc_magnet_block(sample_block()[:25], PlcMagnetConfig())


class PlcMagnetAdminConfigTest(unittest.TestCase):
    def setUp(self):
        self.old_db_path = database.DB_PATH
        self.old_config_path = database.CONFIG_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_dir.name) / "quality_control.db"
        database.CONFIG_PATH = Path(self.temp_dir.name) / "config.ini"
        database.CONFIG_PATH.write_text(
            f"[DATABASE]\ntype = sqlite\npath = {database.DB_PATH}\n",
            encoding="utf-8",
        )
        database.init_db()
        self.station = services.list_projects_full()[0]["stations"][0]

    def tearDown(self):
        database.DB_PATH = self.old_db_path
        database.CONFIG_PATH = self.old_config_path
        self.temp_dir.cleanup()

    def test_admin_can_save_and_export_plc_magnet_step(self):
        result = services.add_step(
            {
                "station_id": self.station["id"],
                "name": "PLC磁通检测获取",
                "type": "plc_magnet_check",
                "step_order": 2,
                "plc_magnet_config": {
                    "plc_ip": "192.168.111.50",
                    "plc_db": 221,
                    "read_block_size": 26,
                },
            }
        )
        step = next(
            item
            for item in services.list_steps(self.station["id"])
            if item["id"] == result["id"]
        )
        self.assertEqual(step["type"], "plc_magnet_check")
        magnet_config = step["plc_magnet_config"]
        expected_defaults = {
            "plc_ip": "192.168.111.50",
            "plc_rack": 0,
            "plc_slot": 1,
            "plc_db": 221,
            "plc_poll_interval_ms": 300,
            "plc_timeout_seconds": 30,
            "barcode_ok_offset": 0,
            "cylinder_clamped_offset": 2,
            "screw_complete_offset": 4,
            "magnet_complete_offset": 6,
            "mes_read_done_offset": 8,
            "left_flux_offset": 10,
            "left_polarity_offset": 14,
            "left_result_offset": 16,
            "right_flux_offset": 18,
            "right_polarity_offset": 22,
            "right_result_offset": 24,
            "read_block_start": 0,
            "read_block_size": 26,
            "ok_value": 1,
            "write_verify_retry_count": 3,
            "write_verify_interval_ms": 100,
        }
        for key, expected in expected_defaults.items():
            self.assertEqual(magnet_config[key], expected, key)
        config = services.get_station_config_by_ids(
            services.list_projects_full()[0]["id"],
            self.station["id"],
        )
        exported = next(
            item for item in config["steps"] if item["id"] == result["id"]
        )
        self.assertEqual(exported["type"], "plc_magnet_check")
        self.assertEqual(
            exported["plc_magnet_config"]["right_result_offset"],
            24,
        )

    def test_magnet_log_table_accepts_result(self):
        result = services.add_plc_magnet_log(
            {
                "project_id": services.list_projects_full()[0]["id"],
                "station_id": self.station["id"],
                "step_id": 1,
                "product_barcode": "B001",
                "plc_ip": "192.168.111.50",
                "plc_db": 221,
                "left_flux": 12.5,
                "left_polarity": 78,
                "left_result": 1,
                "right_flux": -3.25,
                "right_polarity": 78,
                "right_result": 1,
                "raw_hex": "00 01",
                "result": "OK",
            }
        )
        self.assertGreater(result["id"], 0)
        with database.get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM plc_magnet_logs WHERE id = ?",
                (result["id"],),
            ).fetchone()
        self.assertEqual(row["product_barcode"], "B001")
        self.assertEqual(row["result"], "OK")

    def test_admin_page_contains_magnet_type_and_all_offsets(self):
        self.assertIn("PLC磁通检测获取", HTML)
        self.assertIn(
            '<option value="plc_magnet_check">PLC磁通检测获取</option>',
            HTML,
        )
        for element_id in (
            "magnetBarcodeOkOffset",
            "magnetCylinderOffset",
            "magnetScrewOffset",
            "magnetCompleteOffset",
            "magnetReadDoneOffset",
            "magnetLeftFluxOffset",
            "magnetLeftPolarityOffset",
            "magnetLeftResultOffset",
            "magnetRightFluxOffset",
            "magnetRightPolarityOffset",
            "magnetRightResultOffset",
        ):
            self.assertIn(f'id="{element_id}"', HTML)

    def test_legacy_magnet_type_is_normalized_to_canonical_code(self):
        result = services.add_step(
            {
                "station_id": self.station["id"],
                "name": "旧值兼容",
                "type": "PLC磁通检测获取",
                "step_order": 2,
            }
        )
        step = next(
            item
            for item in services.list_steps(self.station["id"])
            if item["id"] == result["id"]
        )
        self.assertEqual(step["type"], "plc_magnet_check")


if __name__ == "__main__":
    unittest.main()
