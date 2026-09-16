"""Run every root test module in isolated Qt processes for Stage F."""

import os
import re
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    files = sorted(root.glob("test_*.py"))
    groups = [files[index:index + 8] for index in range(0, len(files), 8)]
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONUTF8"] = "1"
    def run_group(group, label):
        names = [path.name for path in group]
        print(f"GROUP {label}: {', '.join(names)}", flush=True)
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", *names],
                cwd=root, env=env, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=600,
            )
        except subprocess.TimeoutExpired:
            print(f"RESULT {label}: timeout", flush=True)
            result = None
        if result is not None:
            tail = (result.stdout + result.stderr)[-5000:]
            print(f"RESULT {label}: exit={result.returncode}\n{tail}", flush=True)
        if result is None or result.returncode != 0:
            # Split only native exits/timeouts. A normal pytest assertion
            # failure must remain a failure, even if a retry might pass.
            has_pytest_failure = result is not None and re.search(
                r"\d+ failed|=+ (?:FAILURES|ERRORS) =+", result.stdout
            )
            if len(group) > 1 and not has_pytest_failure:
                middle = len(group) // 2
                left_count, left_failures = run_group(group[:middle], f"{label}.1")
                right_count, right_failures = run_group(group[middle:], f"{label}.2")
                return left_count + right_count, left_failures + right_failures
            return 0, [(names[0], "timeout" if result is None else result.returncode)]
        match = re.search(r"(\d+) passed", result.stdout)
        return (int(match.group(1)) if match else 0), []

    failures = []
    passed = 0
    for number, group in enumerate(groups, 1):
        count, group_failures = run_group(group, f"{number}/{len(groups)}")
        passed += count
        failures.extend(group_failures)
    print(f"TOTAL modules={len(files)} passed={passed} failed_groups={failures}", flush=True)
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
