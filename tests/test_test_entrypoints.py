"""Regression tests for the documented direct test-script commands."""

import os
import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestScriptEntrypoints(unittest.TestCase):
    def run_test_script(self, filename):
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "tests" / filename)],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def test_features_script_can_run_directly(self):
        result = self.run_test_script("test_features.py")

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_delete_script_can_run_directly(self):
        result = self.run_test_script("test_delete.py")

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
