"""全量测试入口：unittest discover + 结果摘要。

用法: python -B tools/run_build_tests.py
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    # 子进程输出含非 GBK 字符（✓ 等），控制台默认 cp936 下子测试进程会直接
    # UnicodeEncodeError；统一强制 UTF-8。父进程自身输出同样重配置。
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
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
        env=env,
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
