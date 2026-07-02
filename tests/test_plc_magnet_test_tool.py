import ast
import os
import tempfile
import unittest
from pathlib import Path

from plc_magnet_test_tool.logic import (
    DB_ACCESS_GUIDANCE,
    DB_LENGTH_GUIDANCE,
    REAL_ACCESS_GUIDANCE,
    VERIFY_WARNING,
    MagnetConfig,
    MagnetFlowController,
    evaluate_magnet_result,
    format_word,
)
from plc_magnet_test_tool.paths import (
    ensure_config_file,
    ensure_log_dir,
    get_base_dir,
    get_config_path,
    get_resource_path,
)
from shared.s7_plc_client import S7PlcClient


ROOT = Path(__file__).resolve().parents[1]


class FakePlcClient:
    def __init__(
        self,
        initial=None,
        read_sequences=None,
        failures=None,
        raw_length=26,
    ):
        self.ip = "192.168.111.50"
        self.rack = 0
        self.slot = 1
        self.values = dict(initial or {})
        self.read_sequences = {
            offset: list(values)
            for offset, values in (read_sequences or {}).items()
        }
        self.failures = dict(failures or {})
        self.raw_length = raw_length
        self.writes = []

    def read_word(self, db_number, offset):
        if ("word", offset) in self.failures:
            raise RuntimeError(self.failures[("word", offset)])
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
        if ("real", offset) in self.failures:
            raise RuntimeError(self.failures[("real", offset)])
        return {10: 123.456, 18: 122.98}.get(offset, 0.0)

    def read_dword(self, db_number, offset):
        if ("dword", offset) in self.failures:
            raise RuntimeError(self.failures[("dword", offset)])
        return {10: 123456, 18: 122980}.get(offset, 0)

    def read_bytes(self, db_number, offset, length):
        if ("bytes", offset) in self.failures:
            raise RuntimeError(self.failures[("bytes", offset)])
        return bytes(min(length, self.raw_length))


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

    def test_single_dbw0_failure_has_full_context_and_guidance(self):
        messages = []
        client = FakePlcClient(
            failures={("word", 0): "CPU : Item not available"},
        )
        controller = MagnetFlowController(
            client,
            MagnetConfig(),
            log=messages.append,
        )
        result = controller.read_point("barcode_ok")
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], DB_ACCESS_GUIDANCE)
        log_text = "\n".join(messages)
        self.assertIn("PLC IP=192.168.111.50", log_text)
        self.assertIn("Rack=0", log_text)
        self.assertIn("Slot=1", log_text)
        self.assertIn("DB=221", log_text)
        self.assertIn("地址=DB221.DBW0", log_text)
        self.assertIn("读取长度=2", log_text)
        self.assertIn("错误原文=CPU : Item not available", log_text)

    def test_read_all_continues_after_individual_address_failure(self):
        client = FakePlcClient(
            initial={0: 1, 2: 1, 4: 1, 6: 1, 8: 1, 14: 1, 16: 1, 22: 2, 24: 1},
            failures={("word", 4): "DBW4 unavailable"},
        )
        result = self.make_controller(client).read_all_diagnostic()
        self.assertIn("screw_complete", result["read_errors"])
        self.assertEqual(result["barcode_ok"], 1)
        self.assertEqual(result["right_result"], 1)
        self.assertEqual(result["left_flux"], 123.456)

    def test_real_failure_after_word_success_has_specific_guidance(self):
        client = FakePlcClient(
            initial={0: 1},
            failures={("real", 10): "Address out of range"},
        )
        result = self.make_controller(client).read_all_diagnostic()
        self.assertEqual(result["barcode_ok"], 1)
        self.assertIn("left_flux", result["read_errors"])
        self.assertEqual(result["diagnostic_message"], REAL_ACCESS_GUIDANCE)

    def test_db_length_precheck_reports_external_access_failure(self):
        messages = []
        client = FakePlcClient(
            failures={("bytes", 0): "CLI : Address out of range"},
        )
        controller = MagnetFlowController(
            client,
            MagnetConfig(),
            log=messages.append,
        )
        result = controller.precheck_db_length()
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], DB_LENGTH_GUIDANCE)
        self.assertIn("读取长度=26", "\n".join(messages))

    def test_db_length_precheck_rejects_short_read(self):
        result = self.make_controller(
            FakePlcClient(raw_length=12)
        ).precheck_db_length()
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], DB_LENGTH_GUIDANCE)


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

    def test_ui_contains_all_single_point_read_buttons_and_s7_hints(self):
        source = (
            ROOT / "plc_magnet_test_tool" / "main.py"
        ).read_text(encoding="utf-8")
        for address in (
            "DBW0",
            "DBW2",
            "DBW4",
            "DBW6",
            "DBW8",
            "DBD10",
            "DBW14",
            "DBW16",
            "DBD18",
            "DBW22",
            "DBW24",
        ):
            self.assertIn(f'"{address}"', source)
        self.assertIn('QPushButton(f"读取 {address}")', source)
        self.assertIn("测试DBW0访问", source)
        self.assertIn("DB长度预检(0-25)", source)
        self.assertIn("Optimized block access", source)
        self.assertIn("DB221 至少 26 字节", source)

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
        self.assertIn("--path-self-check", standalone)
        self.assertIn("WorkingDirectory $otherCwd", standalone)
        self.assertIn("$exeDir/config.ini", standalone)
        self.assertIn("$exeDir/logs/plc_magnet_test.log", standalone)
        self.assertNotIn("PLC_Magnet_Test_Tool", formal)

    def test_pyinstaller_data_path_is_relative_to_spec_directory(self):
        build_script = (
            ROOT / "plc_magnet_test_tool" / "build_exe.bat"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '--add-data "plc_magnet_test_tool/config.example.ini;."',
            build_script,
        )
        self.assertNotIn("--specpath", build_script)


class PlcMagnetPathTest(unittest.TestCase):
    def test_source_base_dir_is_tool_directory(self):
        expected = ROOT / "plc_magnet_test_tool"
        self.assertEqual(get_base_dir(), expected.resolve())

    def test_frozen_base_dir_is_executable_directory(self):
        executable = Path("C:/MES/PLC_Magnet_Test_Tool.exe")
        expected = executable.resolve().parent
        self.assertEqual(
            get_base_dir(
                frozen=True,
                executable=executable,
            ),
            expected,
        )

    def test_config_path_is_always_under_base_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "PLC_Magnet_Test_Tool.exe"
            self.assertEqual(
                get_config_path(
                    frozen=True,
                    executable=executable,
                ),
                Path(temp_dir).resolve() / "config.ini",
            )

    def test_missing_config_is_copied_from_embedded_template(self):
        with tempfile.TemporaryDirectory() as base_dir:
            with tempfile.TemporaryDirectory() as resource_dir:
                template = Path(resource_dir) / "config.example.ini"
                template.write_text("[PLC]\nip=192.168.111.50\n", encoding="utf-8")
                target = ensure_config_file(
                    base_dir=base_dir,
                    resource_path=template,
                )
                self.assertEqual(target, Path(base_dir).resolve() / "config.ini")
                self.assertEqual(
                    target.read_text(encoding="utf-8"),
                    template.read_text(encoding="utf-8"),
                )

    def test_existing_config_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as base_dir:
            with tempfile.TemporaryDirectory() as resource_dir:
                target = Path(base_dir) / "config.ini"
                target.write_text("user_value=keep", encoding="utf-8")
                template = Path(resource_dir) / "config.example.ini"
                template.write_text("user_value=replace", encoding="utf-8")
                result = ensure_config_file(
                    base_dir=base_dir,
                    resource_path=template,
                )
                self.assertEqual(result.read_text(encoding="utf-8"), "user_value=keep")

    def test_log_directory_is_created_next_to_executable(self):
        with tempfile.TemporaryDirectory() as base_dir:
            log_dir = ensure_log_dir(base_dir=base_dir)
            self.assertEqual(log_dir, Path(base_dir).resolve() / "logs")
            self.assertTrue(log_dir.is_dir())

    def test_paths_do_not_depend_on_current_working_directory(self):
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as other_dir:
            try:
                os.chdir(other_dir)
                self.assertEqual(
                    get_resource_path("config.example.ini"),
                    (
                        ROOT
                        / "plc_magnet_test_tool"
                        / "config.example.ini"
                    ).resolve(),
                )
            finally:
                os.chdir(original_cwd)

    def test_missing_template_has_clear_error(self):
        with tempfile.TemporaryDirectory() as base_dir:
            missing = Path(base_dir) / "missing-config.example.ini"
            with self.assertRaisesRegex(
                RuntimeError,
                "config.example.ini 未打包或不存在",
            ):
                ensure_config_file(
                    base_dir=base_dir,
                    resource_path=missing,
                )


if __name__ == "__main__":
    unittest.main()
