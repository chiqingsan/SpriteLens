"""全量测试入口：unittest discover + 结果摘要。

用法: python -B tools/run_build_tests.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    cmd = [
        sys.executable,
        "-B",
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests",
        "-p",
        "test_*.py",
        "-q",
    ]
    print("[run_build_tests]", " ".join(cmd[1:]))
    proc = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    print(output, end="" if output.endswith("\n") else "\n")
    if proc.returncode != 0:
        print("[run_build_tests] 失败")
        return proc.returncode
    matched = re.search(r"Ran (\d+) tests", output)
    count = matched.group(1) if matched else "?"
    print(f"[run_build_tests] 测试通过: {count} 项")
    return 0


if __name__ == "__main__":
    sys.exit(main())
