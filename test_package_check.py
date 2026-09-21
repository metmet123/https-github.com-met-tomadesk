import json
from pathlib import Path

from package_check import run_package_check


def test_package_diagnostic_roundtrip_and_report_is_not_overwritten(tmp_path):
    report = tmp_path / "check.json"
    assert run_package_check(report) == 0
    original = report.read_bytes()
    result = json.loads(original)
    assert result["ok"]
    assert "database_reopen" in result["checks"]
    assert "tomapet_webp_and_metadata" in result["checks"]
    assert report.with_suffix(".review.png").is_file()
    assert report.with_suffix(".summary.png").is_file()
    assert not list(tmp_path.glob("package-check-*"))
    assert run_package_check(report) == 2
    assert report.read_bytes() == original
