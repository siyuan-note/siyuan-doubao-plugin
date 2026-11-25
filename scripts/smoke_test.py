#!/usr/bin/env python3
# SiYuan - https://github.com/siyuan-note/siyuan
# Copyright (c) 2020-present, b3log.org
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Zero-dependency smoke test for the SiYuan CLI connector.

Reproduces the checks Doubao performs when the plugin loads:

    1. ``siyuan --version``                  -> CLI installed and on PATH
    2. ``siyuan workspace list -f json``     -> workspaces discovered
    3. ``siyuan -w <ws> notebook list -f json`` -> data readable

No API token, no HTTP server, nothing but the Python standard library.

Usage:
    python3 scripts/smoke_test.py
    python3 scripts/smoke_test.py --workspace "D:/SiYuan"
    python3 scripts/smoke_test.py --command "/path/to/SiYuan-Kernel"

Exit code 0 means the CLI connector would load and see real notebook data.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

VERSION_RE = re.compile(r"siyuan version \d+\.\d+\.\d+")
COMMAND = "siyuan"


class SmokeError(RuntimeError):
    pass


def run(command: str, args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [command, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as err:
        raise SmokeError(
            f"{command!r} not found on PATH; install SiYuan 3.8+ and add the kernel directory to PATH"
        ) from err
    except subprocess.TimeoutExpired as err:
        raise SmokeError(f"{command} {' '.join(args)} timed out after {timeout:g}s") from err


def check(command: str, workspace: str | None, timeout: float) -> None:
    print(f"command {command}")

    version = run(command, ["--version"], timeout)
    if version.returncode != 0:
        raise SmokeError(f"--version failed ({version.returncode}): {(version.stderr or version.stdout).strip()[:200]}")
    match = VERSION_RE.search(version.stdout or version.stderr)
    if not match:
        raise SmokeError(f"unexpected --version output: {(version.stdout or '').strip()[:200]!r}")
    print(f"version {match.group(0)}")

    listed = run(command, ["workspace", "list", "-f", "json"], timeout)
    if listed.returncode != 0:
        raise SmokeError(f"workspace list failed ({listed.returncode}): {listed.stderr.strip()[:200]}")
    try:
        workspaces = json.loads(listed.stdout)
    except json.JSONDecodeError as err:
        raise SmokeError(f"workspace list did not return JSON: {listed.stdout[:200]!r} ({err})") from err
    paths = [w.get("path") for w in workspaces if isinstance(w, dict) and w.get("path")]
    print(f"workspaces {len(paths)} registered")
    for path in paths[:5]:
        print(f"         {path}")
    if len(paths) > 5:
        print(f"         ... and {len(paths) - 5} more")

    if workspace:
        selected = workspace
    elif paths:
        selected = paths[-1]
    else:
        selected = os.environ.get("SIYUAN_WORKSPACE_PATH") or os.path.join(os.path.expanduser("~"), "SiYuan")
    print(f"using    {selected}")

    prefix = [command, "-w", selected, "-f", "json"]
    notebooks = run(prefix[0], prefix[1:] + ["notebook", "list"], timeout)
    if notebooks.returncode != 0:
        raise SmokeError(
            f"notebook list failed ({notebooks.returncode}): {notebooks.stderr.strip()[:200]}"
        )
    try:
        data = json.loads(notebooks.stdout)
    except json.JSONDecodeError as err:
        raise SmokeError(f"notebook list did not return JSON: {notebooks.stdout[:200]!r} ({err})") from err
    count = len(data) if isinstance(data, list) else 0
    print(f"notebooks {count} available")
    if not count:
        raise SmokeError("the workspace has no notebooks; check that this is the right workspace")
    print("OK")


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test the SiYuan CLI connector used by the plugin.")
    parser.add_argument(
        "--command",
        default=os.environ.get("SIYUAN_CLI", COMMAND),
        help=f"CLI executable (default: %(default)s, or SIYUAN_CLI)",
    )
    parser.add_argument(
        "--workspace",
        default=os.environ.get("SIYUAN_WORKSPACE_PATH"),
        help="workspace path to use (default: last registered, or SIYUAN_WORKSPACE_PATH)",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="per-command timeout in seconds")
    args = parser.parse_args()

    try:
        check(args.command, args.workspace, args.timeout)
    except SmokeError as err:
        print(f"FAILED {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
