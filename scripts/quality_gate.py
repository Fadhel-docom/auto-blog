#!/usr/bin/env python3
"""Standalone editorial quality gate."""
from pathlib import Path
import subprocess
import sys

GUARD = Path(__file__).with_name("publish_guard.py")
if not GUARD.is_file():
    raise SystemExit("QUALITY GATE: publish_guard.py not found")
result = subprocess.run([sys.executable, str(GUARD)], check=False)
if result.returncode == 0:
    print("QUALITY GATE: PASS")
else:
    print(f"QUALITY GATE: BLOCKED (publish_guard exit={result.returncode})")
sys.exit(result.returncode)
