import configparser
import io
import tempfile
import unittest
import urllib.error
from pathlib import Path

from desktop_app.window import QualityControlWindow, normalize_server_url


class TextFieldStub:
    def __init__(self, text=""):
        self.value = text

    def text(self):
        return self.value

    def setText(self, value):
        self.value = value


class ServerUrlConfigTest(unittest.TestCase):
    def test_normalize_server_url_accepts_dns_name(self):
        self.assertEqual(normalize_server_url("mes.company.local:8000/"), "http://mes.company.local:8000")

    def test_persist_server_url_preserves_client_id_and_builds_download_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.ini"
            config_path.write_text(
                "[LOCAL_DEVICE]\n"
                "client_id = fixed-client-id\n"
                "mes_server = http://old-mes:8000\n",
                encoding="utf-8",
            )
            window = type("WindowStub", (), {})()
            window.app_config_path = config_path
            window.api_base_input = TextFieldStub()
            window.local_mes_server_label = TextFieldStub()

            saved_url = QualityControlWindow.persist_server_url(window, "mes.company.local:8000")

            saved = configparser.ConfigParser()
            saved.read(config_path, encoding="utf-8")
            self.assertEqual(saved_url, "http://mes.company.local:8000")
            self.assertEqual(saved.get("SERVER", "url"), saved_url)
            self.assertEqual(saved.get("LOCAL_DEVICE", "client_id"), "fixed-client-id")
            self.assertFalse(saved.has_option("LOCAL_DEVICE", "mes_server"))
            self.assertEqual(
                QualityControlWindow.api_url(window, "/api/client-update/download/v0.8.5/release"),
                "http://mes.company.local:8000/api/client-update/download/v0.8.5/release",
            )

    def test_http_error_message_includes_server_detail(self):
        error = urllib.error.HTTPError(
            "http://mes/api/station-config",
            500,
            "Internal Server Error",
            {},
            io.BytesIO('{"error":"缺少工序字段"}'.encode("utf-8")),
        )
        self.assertEqual(
            QualityControlWindow.http_error_message(error),
            "服务端响应错误 HTTP 500：缺少工序字段",
        )


if __name__ == "__main__":
    unittest.main()
