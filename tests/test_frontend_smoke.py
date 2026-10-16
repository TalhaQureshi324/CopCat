"""Frontend smoke test: run the jsdom lock-screen click-through.

Requires node + `npm install` inside tests/ui (jsdom). Skips gracefully
when either is unavailable so lean environments still pass the suite.
This exists because a single-character JS syntax error once shipped and
silently disabled every click handler on the lock screen.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parent / "ui"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_lock_screen_behaviors():
    if not (UI / "node_modules" / "jsdom").exists():
        pytest.skip("jsdom missing (run: npm install inside tests/ui)")
    r = subprocess.run([shutil.which("node"), "lock_test.js"], cwd=UI,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, "frontend smoke failed:\n{}{}".format(
        r.stdout, r.stderr)
    assert "FAIL" not in r.stdout, r.stdout
