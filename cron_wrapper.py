#!/usr/bin/env python3
"""Cron job wrapper: runs the PaperCatch daily pipeline"""
import subprocess, sys, os

project_dir = os.path.dirname(os.path.abspath(__file__))  # auto-detect
pipeline = os.path.join(project_dir, "daily_pipeline.py")

os.chdir(project_dir)
result = subprocess.run(
    [sys.executable, pipeline, "--email"],
    cwd=project_dir,
    capture_output=True,
    text=True,
    timeout=300,
)

# Forward stdout (this becomes the agent's context)
print(result.stdout)

# Forward stderr to real stderr for debugging
if result.stderr:
    print(result.stderr, file=sys.stderr)

sys.exit(result.returncode)
