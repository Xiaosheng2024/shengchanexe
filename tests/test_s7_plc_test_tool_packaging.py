import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class S7PlcTestToolDeprecationTest(unittest.TestCase):
    def test_shared_package_and_plc_addresses_are_available(self):
        self.assertTrue((ROOT / "shared" / "__init__.py").is_file())
        self.assertTrue((ROOT / "shared" / "s7_plc_client.py").is_file())
        config = (ROOT / "s7_plc_test_tool" / "config.ini").read_text(encoding="utf-8")
        self.assertIn("db_number = 201", config)
        self.assertIn("offset = 800", config)
        self.assertIn("db_number = 221", config)
        self.assertIn("offset = 358", config)

    def test_project_root_is_added_before_shared_import(self):
        source = (ROOT / "s7_plc_test_tool" / "main.py").read_text(encoding="utf-8")
        ast.parse(source)
        self.assertLess(
            source.index("sys.path.insert(0, PROJECT_ROOT)"),
            source.index("from shared.s7_plc_client import"),
        )

    def test_windows_release_no_longer_builds_or_uploads_s7_tool(self):
        workflow = (ROOT / ".github" / "workflows" / "windows-build.yml").read_text(
            encoding="utf-8"
        )
        build_script = (ROOT / "s7_plc_test_tool" / "build_exe.bat").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("--name S7_PLC_Test_Tool", workflow)
        self.assertNotIn("S7_PLC_Test_Tool-windows", workflow)
        self.assertIn("delete-asset windows-latest S7_PLC_Test_Tool.exe", workflow)
        self.assertIn("deprecated", build_script.lower())
        self.assertNotIn("pyinstaller", build_script.lower())
        self.assertTrue((ROOT / "s7_plc_test_tool" / "DEPRECATED.md").is_file())


if __name__ == "__main__":
    unittest.main()
