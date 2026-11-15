import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


class SetupTests(unittest.TestCase):
    def test_missing_settings_stop_before_network(self):
        env = os.environ.copy()
        for key in ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_ALLOWED_USERS"):
            env.pop(key, None)
        result = subprocess.run(
            [sys.executable, "main.py"], env=env, capture_output=True, text=True,
            timeout=10,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID", result.stderr)

    def test_no_proxy_is_supported(self):
        self.assertEqual(main.validate_proxy_pool([]), [])
        with patch.object(main, "PROXY_POOL", []):
            self.assertIsNone(main.get_random_proxy())

    def test_untrusted_chat_cannot_issue_commands(self):
        with patch.object(main, "ALLOWED_USERS", {123}), patch.object(main, "send_telegram") as send:
            main.handle_command(456, "/start")
            send.assert_not_called()

    def test_token_can_be_saved_in_workspace_data_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "vfs_token.json"
            with patch.object(main, "TOKEN_FILE", target), patch.object(main, "_vfs_token"), patch.object(main, "_vfs_token_time"):
                main._save_vfs_token("test-only-token")
                self.assertEqual(json.loads(target.read_text())["token"], "test-only-token")


if __name__ == "__main__":
    unittest.main()
