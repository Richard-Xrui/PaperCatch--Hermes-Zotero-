from __future__ import annotations

import importlib
import io
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CronWrapperTests(unittest.TestCase):
    def test_import_does_not_start_subprocess_or_change_cwd(self):
        with patch("subprocess.run") as run_mock, patch("os.chdir") as chdir_mock:
            sys.modules.pop("cron_wrapper", None)
            importlib.import_module("cron_wrapper")

        self.assertFalse(run_mock.called)
        self.assertFalse(chdir_mock.called)

    def test_main_forwards_stdout_stderr_and_exit_code(self):
        sys.modules.pop("cron_wrapper", None)
        import cron_wrapper

        completed = types.SimpleNamespace(stdout="ok\n", stderr="warn\n", returncode=7)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.object(cron_wrapper.subprocess, "run", return_value=completed) as run_mock, patch(
            "sys.stdout", stdout
        ), patch("sys.stderr", stderr), patch.object(cron_wrapper.os, "chdir") as chdir_mock:
            code = cron_wrapper.main()

        self.assertEqual(7, code)
        self.assertTrue(run_mock.called)
        self.assertTrue(chdir_mock.called)
        self.assertEqual("ok\n", stdout.getvalue())
        self.assertEqual("warn\n", stderr.getvalue())

    def test_main_propagates_timeout_as_nonzero(self):
        sys.modules.pop("cron_wrapper", None)
        import cron_wrapper

        stderr = io.StringIO()
        with patch.object(
            cron_wrapper.subprocess,
            "run",
            side_effect=cron_wrapper.subprocess.TimeoutExpired(["python"], 300),
        ), patch("sys.stderr", stderr):
            code = cron_wrapper.main()

        self.assertEqual(1, code)
        self.assertIn("CRON_TIMEOUT", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
