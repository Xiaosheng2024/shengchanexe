import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeployScriptTest(unittest.TestCase):
    def test_shell_scripts_have_valid_syntax(self):
        for name in ("prepare_update_package.sh", "deploy_update_to_server.sh"):
            result = subprocess.run(
                ["bash", "-n", str(ROOT / name)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_prepare_package_uses_committed_files_only(self):
        source = (ROOT / "prepare_update_package.sh").read_text(encoding="utf-8")
        self.assertIn("git archive", source)
        self.assertIn("--untracked-files=no", source)

    def test_deploy_script_only_uploads_files(self):
        source = (ROOT / "deploy_update_to_server.sh").read_text(encoding="utf-8")
        self.assertIn("仅上传文件，不执行任何服务器部署命令", source)
        self.assertIn('scp "${DIST_DIR}/mes_update.tar.gz"', source)
        self.assertNotIn("sudo ", source)
        self.assertNotIn("systemctl", source)
        self.assertNotIn("bash -s", source)


if __name__ == "__main__":
    unittest.main()
