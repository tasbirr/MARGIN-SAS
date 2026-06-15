#!/usr/bin/env python3
"""Run the project test scripts with a local Flask server available."""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER_URL = "http://127.0.0.1:5000/"


def server_is_ready() -> bool:
    try:
        with urllib.request.urlopen(SERVER_URL, timeout=2) as response:
            return 200 <= response.status < 500
    except (OSError, urllib.error.URLError):
        return False


def start_server_if_needed() -> subprocess.Popen[str] | None:
    if server_is_ready():
        return None

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        [sys.executable, "run_server.py"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    deadline = time.time() + 20
    while time.time() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ""
            raise RuntimeError(f"Server exited early with code {proc.returncode}\n{output}")
        if server_is_ready():
            return proc
        time.sleep(0.5)

    proc.terminate()
    output = proc.stdout.read() if proc.stdout else ""
    raise RuntimeError(f"Server did not become ready at {SERVER_URL}\n{output}")


def run_tests() -> int:
    tests = sorted((ROOT / "tests").glob("test_*.py"))
    failures: list[str] = []

    for test_path in tests:
        rel = test_path.relative_to(ROOT)
        print(f"\n=== {rel} ===", flush=True)
        result = subprocess.run([sys.executable, str(rel)], cwd=ROOT)
        if result.returncode != 0:
            failures.append(str(rel))

    if failures:
        print("\nFailed tests:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("\nAll test scripts passed.")
    return 0


def main() -> int:
    server_proc: subprocess.Popen[str] | None = None
    try:
        server_proc = start_server_if_needed()
        return run_tests()
    finally:
        if server_proc is not None and server_proc.poll() is None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
