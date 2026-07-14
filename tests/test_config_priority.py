"""Configuration precedence regression tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ConfigPriorityTests(unittest.TestCase):
    def test_zotero_server_uses_environment_over_data_directory_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "config.local.json").write_text(
                json.dumps(
                    {
                        "zotero": {
                            "api_key": "",
                            "user_id": "",
                            "default_collection": "File Collection",
                        }
                    }
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env.update(
                {
                    "PAPERCATCH_DATA_DIR": str(data_dir),
                    "PAPERCATCH_RESOURCE_DIR": str(PROJECT_ROOT),
                    "ZOTERO_API_KEY": "environment-api-key",
                    "ZOTERO_USER_ID": "24680",
                    "ZOTERO_DEFAULT_COLLECTION": "Environment Collection",
                }
            )
            script = textwrap.dedent(
                """
                import json
                import config
                import zotero_server

                loaded = config.load_config()
                print(json.dumps({
                    "config_file": str(config.CONFIG_FILE),
                    "loaded_zotero": loaded["zotero"],
                    "app_zotero": zotero_server.APP_CONFIG["zotero"],
                    "api_key": zotero_server.ZOTERO_API_KEY,
                    "user_id": zotero_server.ZOTERO_USER_ID,
                    "api_root": zotero_server.ZOTERO_API_ROOT,
                    "default_collection": zotero_server.DEFAULT_COLLECTION,
                }))
                """
            )

            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=PROJECT_ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(data_dir / "config.local.json", Path(payload["config_file"]))
            self.assertEqual("environment-api-key", payload["loaded_zotero"]["api_key"])
            self.assertEqual("24680", payload["loaded_zotero"]["user_id"])
            self.assertEqual(
                "Environment Collection",
                payload["loaded_zotero"]["default_collection"],
            )
            self.assertEqual(payload["loaded_zotero"], payload["app_zotero"])
            self.assertEqual("environment-api-key", payload["api_key"])
            self.assertEqual("24680", payload["user_id"])
            self.assertEqual("https://api.zotero.org/users/24680", payload["api_root"])
            self.assertEqual("Environment Collection", payload["default_collection"])

    def test_server_config_reload_uses_current_data_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            initial_data_dir = root / "initial"
            patched_data_dir = root / "patched"
            initial_data_dir.mkdir()
            patched_data_dir.mkdir()
            (initial_data_dir / "config.local.json").write_text(
                json.dumps({"test_marker": "initial"}),
                encoding="utf-8",
            )
            (patched_data_dir / "config.local.json").write_text(
                json.dumps({"test_marker": "patched"}),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env.update(
                {
                    "PAPERCATCH_DATA_DIR": str(initial_data_dir),
                    "PAPERCATCH_RESOURCE_DIR": str(PROJECT_ROOT),
                    "PAPERCATCH_PATCHED_DATA_DIR": str(patched_data_dir),
                }
            )
            script = textwrap.dedent(
                """
                import os
                from pathlib import Path
                import zotero_server

                zotero_server.BASE_DIR = Path(os.environ["PAPERCATCH_PATCHED_DATA_DIR"])
                print(zotero_server.load_app_config()["test_marker"])
                """
            )

            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=PROJECT_ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual("patched", result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
