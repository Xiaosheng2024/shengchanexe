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

    def test_deploy_uses_get_health_check_and_restores_service_on_error(self):
        source = (ROOT / "deploy_update_to_server.sh").read_text(encoding="utf-8")
        self.assertNotIn("curl -fsSI", source)
        self.assertIn("-w '%{http_code}'", source)
        self.assertIn('sudo systemctl start "${MES_SERVICE}" || true', source)
        self.assertIn("服务器禁止 ICMP/Ping", source)


if __name__ == "__main__":
    unittest.main()
