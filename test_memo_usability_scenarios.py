"""Run the complete Stage F click-path scenarios in an isolated Qt process."""

import json
import os
import subprocess
import sys
from pathlib import Path


def test_all_memo_usability_scenarios(tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONUTF8"] = "1"
    env["TOMADESK_USABILITY_OUT"] = str(tmp_path)
    script = Path(__file__).parent / "tools" / "memo_usability_test.py"
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env, timeout=180,
    )
    report_path = tmp_path / "results.json"
    assert report_path.exists(), result.stdout[-3000:] + result.stderr[-3000:]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rows = report["results"]
    assert {f"S{number}" for number in range(1, 14)} <= {
        row["scenario"].split()[0] for row in rows
    }
    assert len(rows) >= 71
    assert not report["exceptions"], report["exceptions"]
    assert all(row["ok"] for row in rows), [row for row in rows if not row["ok"]]
    assert len(list((tmp_path / "shots").glob("*.png"))) >= 13
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
