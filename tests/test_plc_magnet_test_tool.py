import ast
import unittest
from pathlib import Path

from plc_magnet_test_tool.logic import (
    VERIFY_WARNING,
    MagnetConfig,
    MagnetFlowController,
    evaluate_magnet_result,
    format_word,
)
from shared.s7_plc_client import S7PlcClient


ROOT = Path(__file__).resolve().parents[1]


class FakePlcClient:
    def __init__(self, initial=None, read_sequences=None):
        self.values = dict(initial or {})
        self.read_sequences = {
            offset: list(values)
            for offset, values in (read_sequences or {}).items()
        }
        self.writes = []

    def read_word(self, db_number, offset):
        sequence = self.read_sequences.get(offset)
        if sequence:
            value = sequence.pop(0)
            self.values[offset] = value
            return value
        return self.values.get(offset, 0)

    def write_word(self, db_number, offset, value):
        self.writes.append((db_number, offset, value))
        self.values[offset] = value

    def read_real(self, db_number, offset):
        return {10: 123.456, 18: 122.98}.get(offset, 0.0)

    def read_dword(self, db_number, offset):
        return {10: 123456, 18: 122980}.get(offset, 0)


class AdvancingClock:
    def __init__(self, step=0.6):
        self.value = 0.0
        self.step = step

    def __call__(self):
        current = self.value
        self.value += self.step
        return current


class PlcMagnetLogicTest(unittest.TestCase):
    def make_controller(
        self,
        client,
        timeout=2.0,
        retry_count=3,
        clock=None,
    ):
        return MagnetFlowController(
            client,
            MagnetConfig(
                timeout_seconds=timeout,
                poll_interval_ms=100,
                write_verify_retry_count=retry_count,
                write_verify_interval_ms=100,
            ),
            sleep_func=lambda seconds: None,
            monotonic_func=clock or AdvancingClock(0.1),
        )

    def test_word_format_is_decimal_and_siemens_hex(self):
        self.assertEqual(format_word(0), "0 / 16#0000")
        self.assertEqual(format_word(1), "1 / 16#0001")

    def test_result_requires_both_sides_ok(self):
        self.assertEqual(evaluate_magnet_result(1, 1), "OK")
        self.assertEqual(evaluate_magnet_result(0, 1), "NG")
        self.assertEqual(evaluate_magnet_result(1, 0), "NG")
        self.assertEqual(evaluate_magnet_result(2, 1), "UNKNOWN")

    def test_each_mes_signal_writes_integer_one_and_reads_back(self):
        for offset in (0, 4, 8):
            with self.subTest(offset=offset):
                client = FakePlcClient(
                    read_sequences={offset: [0, 1]},
                )
                result = self.make_controller(client).write_one_and_verify(offset)
                self.assertTrue(result["confirmed"])
                self.assertEqual(result["attempts"], 2)
                self.assertEqual(client.writes, [(221, offset, 1)])

    def test_write_confirmation_returns_exact_fast_reset_warning(self):
        client = FakePlcClient(read_sequences={0: [0, 0, 0]})
        result = self.make_controller(client).write_one_and_verify(0)
        self.assertFalse(result["confirmed"])
        self.assertEqual(result["message"], VERIFY_WARNING)
        self.assertEqual(result["attempts"], 3)

    def test_write_rejects_any_non_mes_write_offset(self):
        with self.assertRaisesRegex(ValueError, "只允许"):
            self.make_controller(FakePlcClient()).write_one_and_verify(2)

    def test_full_flow_writes_in_order_only_after_plc_signals(self):
        client = FakePlcClient(
            initial={
                2: 1,
                6: 1,
                14: 1,
                16: 1,
                22: 2,
                24: 1,
            }
        )
        result = self.make_controller(client).run_flow()
        self.assertTrue(result["ok"])
        self.assertEqual(
            client.writes,
            [(221, 0, 1), (221, 4, 1), (221, 8, 1)],
        )

    def test_cylinder_timeout_stops_before_dbw4(self):
        client = FakePlcClient(initial={2: 0})
        result = self.make_controller(
            client,
            timeout=1.0,
            clock=AdvancingClock(0.6),
        ).run_flow()
        self.assertEqual(result["stage"], "wait_dbw2")
        self.assertEqual(client.writes, [(221, 0, 1)])

    def test_magnet_timeout_stops_before_result_and_dbw8(self):
        client = FakePlcClient(initial={2: 1, 6: 0})
        result = self.make_controller(
            client,
            timeout=1.0,
            clock=AdvancingClock(0.6),
        ).run_flow()
        self.assertEqual(result["stage"], "wait_dbw6")
        self.assertEqual(
            client.writes,
            [(221, 0, 1), (221, 4, 1)],
        )

    def test_magnet_ng_never_writes_unlock_signal(self):
        client = FakePlcClient(
            initial={
                2: 1,
                6: 1,
                14: 1,
                16: 1,
                22: 2,
                24: 0,
            }
        )
        result = self.make_controller(client).run_flow()
        self.assertEqual(result["stage"], "magnet_ng")
        self.assertNotIn((221, 8, 1), client.writes)
        self.assertTrue(all(value == 1 for _, _, value in client.writes))

    def test_real_parser_receives_mutable_bytearray(self):
        received = []

        class MutatingUtil:
            @staticmethod
            def get_real(data, offset):
                received.append(type(data))
                data[offset] = data[offset]
                return 12.5

        client = S7PlcClient("127.0.0.1")
        client.snap7_util = MutatingUtil
        client.read_bytes = lambda db, offset, length: bytes(length)
        self.assertEqual(client.read_real(221, 10), 12.5)
        self.assertEqual(received, [bytearray])


class PlcMagnetToolPackagingTest(unittest.TestCase):
    def test_source_has_no_clear_or_write_zero_button(self):
        source_path = ROOT / "plc_magnet_test_tool" / "main.py"
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        button_labels = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if not (
                isinstance(function, ast.Name)
                and function.id == "QPushButton"
            ):
                continue
            if node.args and isinstance(node.args[0], ast.Constant):
                button_labels.append(str(node.args[0].value))
        self.assertFalse(
            any(
                "清零" in label
                or "清全部" in label
                or "=0" in label
                for label in button_labels
            ),
            button_labels,
        )

    def test_defaults_and_all_addresses_are_documented(self):
        config = (
            ROOT / "plc_magnet_test_tool" / "config.example.ini"
        ).read_text(encoding="utf-8")
        self.assertIn("ip = 192.168.111.50", config)
        self.assertIn("db = 221", config)
        for offset in (0, 2, 4, 6, 8, 10, 14, 16, 18, 22, 24):
            self.assertIn(f"= {offset}", config)

    def test_separate_workflow_does_not_modify_formal_release_artifacts(self):
        standalone = (
            ROOT / ".github" / "workflows" / "plc-magnet-tool-build.yml"
        ).read_text(encoding="utf-8")
        formal = (
            ROOT / ".github" / "workflows" / "windows-build.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("PLC_Magnet_Test_Tool-windows", standalone)
        self.assertIn("PLC_Magnet_Test_Tool.exe", standalone)
        self.assertNotIn("PLC_Magnet_Test_Tool", formal)

    def test_pyinstaller_data_path_is_relative_to_spec_directory(self):
        build_script = (
            ROOT / "plc_magnet_test_tool" / "build_exe.bat"
        ).read_text(encoding="utf-8")
        self.assertIn('--add-data "config.example.ini;."', build_script)
        self.assertNotIn(
            '--add-data "plc_magnet_test_tool/config.example.ini;."',
            build_script,
        )


if __name__ == "__main__":
    unittest.main()
