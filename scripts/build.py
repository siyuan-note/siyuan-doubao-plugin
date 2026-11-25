#!/usr/bin/env python3
# SiYuan - https://github.com/siyuan-note/siyuan
# Copyright (c) 2020-present, b3log.org
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Validate the Doubao plugin package and build the uploadable zip.

Doubao reads the root manifest from ``plugin.json`` at the archive root and
rejects a package wrapped in an extra directory, so the zip is flat.

Usage:
    python3 scripts/build.py           # validate, then write dist/siyuan-plugin-<version>.zip
    python3 scripts/build.py --check   # validate only, no archive (used by CI)
    python3 scripts/build.py --list    # print the files that would be packed
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT / "dist"

# Files at the archive root, in readable order.
ROOT_FILES = ("plugin.json", "mcp.json")
# Directories copied recursively: skills/<name>/..., com.doubao/...
PACKAGE_DIRS = ("skills", "com.doubao")

SERVER_KEY = "siyuan"
PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z0-9_]+)\}")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
HOSTNAME_RE = re.compile(r"^[A-Za-z0-9.-]+$")

# Platform limits: 16 MB total, at most 1024 entries, 2 MB per file.
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_ENTRIES = 1024
MAX_FILE_BYTES = 2 * 1024 * 1024

# 1980-01-01 is the earliest zip timestamp; fixing it keeps builds byte-identical.
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def emit(self) -> None:
        for message in self.warnings:
            print(f"warning: {message}")
        for message in self.errors:
            print(f"error: {message}")


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def load_json(path: Path, report: Report) -> dict | None:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        report.error(f"missing {rel(path)}")
    except json.JSONDecodeError as err:
        report.error(f"{rel(path)} is not valid JSON: {err}")
    return None


def iter_package_files() -> list[Path]:
    files = [ROOT / name for name in ROOT_FILES]
    for dirname in PACKAGE_DIRS:
        base = ROOT / dirname
        if base.is_dir():
            files.extend(sorted(path for path in base.rglob("*") if path.is_file()))
    return files


def collect_placeholders(node: object, found: set[str]) -> None:
    if isinstance(node, str):
        found.update(PLACEHOLDER_RE.findall(node))
    elif isinstance(node, dict):
        for value in node.values():
            collect_placeholders(value, found)
    elif isinstance(node, list):
        for value in node:
            collect_placeholders(value, found)


def localized(value: object) -> bool:
    """Accept either a plain string or {"zh": ..., "en": ...}."""
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return bool(str(value.get("zh", "")).strip())
    return False


def validate_auth_schema(path: Path, report: Report) -> set[str]:
    schema = load_json(path, report) or {}
    fields = schema.get("fields") or []
    keys: set[str] = set()
    if not isinstance(fields, list) or not fields:
        report.error(f"{rel(path)} must declare a non-empty fields array")
        return keys
    for field in fields:
        key = field.get("key")
        if not key:
            report.error(f"{rel(path)} has a field without key")
            continue
        if key in keys:
            report.error(f"{rel(path)} declares {key} twice")
        keys.add(key)
        for required in ("label", "type", "description"):
            if not localized(field.get(required)):
                report.error(f"{rel(path)} field {key} is missing {required}")
        if key.endswith("_HOST"):
            default = str(field.get("defaultValue", ""))
            if not HOSTNAME_RE.match(default):
                report.error(f"{rel(path)} field {key} default {default!r} is not a bare hostname")
        if key.endswith("_PORT"):
            default = str(field.get("defaultValue", ""))
            if not default.isdigit():
                report.error(f"{rel(path)} field {key} default {default!r} is not a port")
    if not any(field.get("type") == "password" for field in fields):
        report.error(f"{rel(path)} needs a password field for the API token")
    return keys


def validate() -> tuple[Report, str | None]:
    report = Report()

    for name in ROOT_FILES:
        if not (ROOT / name).is_file():
            report.error(f"missing {name}")

    meta = load_json(ROOT / "plugin.json", report)
    version = None
    if meta is not None:
        version = meta.get("version")
        if not isinstance(version, str) or not SEMVER_RE.match(version):
            report.error(f"plugin.json version must be x.y.z, got {version!r}")
        if meta.get("name") != SERVER_KEY:
            report.error(f'plugin.json name must be "{SERVER_KEY}", got {meta.get("name")!r}')
        if not localized(meta.get("displayName")):
            report.error("plugin.json displayName must be a string or {zh, en}")
        if not localized(meta.get("description")):
            report.error("plugin.json description must be a string or {zh, en}")
        icon = meta.get("icon")
        if not icon or not (ROOT / str(icon)).is_file():
            report.error(f"plugin.json icon {icon!r} does not exist in the package")
        if not meta.get("license"):
            report.warn("plugin.json has no license field")

    auth_keys: set[str] = set()
    auth_dir = ROOT / "com.doubao" / "auth"
    auth_files = sorted(auth_dir.glob("*.json")) if auth_dir.is_dir() else []
    if not auth_files:
        report.error("missing com.doubao/auth/*.json (static credentials schema)")
    for path in auth_files:
        auth_keys |= validate_auth_schema(path, report)

    mcp = load_json(ROOT / "mcp.json", report)
    if mcp is not None:
        servers = mcp.get("mcpServers") or {}
        if list(servers) != [SERVER_KEY]:
            report.error(f'mcp.json must declare exactly one server named "{SERVER_KEY}"')
        server = servers.get(SERVER_KEY) or {}
        url = server.get("url", "")
        if not (isinstance(url, str) and url.startswith("${") and "/mcp" in url):
            report.error("mcp.json server url must be a ${VAR} template ending in /mcp")
        if server.get("type") not in ("streamableHttp", "streamable-http"):
            report.error('mcp.json server type must be "streamableHttp"')

        used: set[str] = set()
        collect_placeholders(server, used)
        missing = sorted(used - auth_keys)
        unused = sorted(auth_keys - used) if auth_keys else []
        if missing:
            report.error(f"mcp.json references variables absent from auth schema: {missing}")
        if unused:
            report.warn(f"auth schema declares unused variables: {unused}")

    skill = ROOT / "skills" / SERVER_KEY / "SKILL.md"
    if not skill.is_file():
        report.error(f"missing skills/{SERVER_KEY}/SKILL.md")
    else:
        parts = skill.read_text(encoding="utf-8").split("---")
        front = parts[1] if len(parts) > 2 else ""
        if not front.strip():
            report.error(f"skills/{SERVER_KEY}/SKILL.md has no YAML frontmatter")
        for key in ("name:", "description:"):
            if key not in front:
                report.error(f"skills/{SERVER_KEY}/SKILL.md frontmatter is missing {key[:-1]}")
        if f"name: {SERVER_KEY}" not in front:
            report.warn(f"skills/{SERVER_KEY}/SKILL.md name should be {SERVER_KEY}")

    files = iter_package_files()
    total = 0
    for path in files:
        if not path.is_file():
            report.error(f"missing {rel(path)}")
            continue
        size = path.stat().st_size
        total += size
        if size > MAX_FILE_BYTES:
            report.error(f"{rel(path)} is {size} bytes, over the 2 MB per-file limit")
        if path.suffix in (".md", ".json", ".py", ".yml", ".yaml") and b"\r\n" in path.read_bytes():
            report.warn(f"{rel(path)} contains CRLF line endings; check .gitattributes")
    if len(files) > MAX_ENTRIES:
        report.error(f"{len(files)} entries, over the {MAX_ENTRIES} limit")
    if total > MAX_TOTAL_BYTES:
        report.error(f"package is {total} bytes, over the 16 MB limit")

    changelog = ROOT / "CHANGELOG.md"
    if version and changelog.is_file() and version not in changelog.read_text(encoding="utf-8"):
        report.warn(f"CHANGELOG.md has no entry for {version}")

    return report, version


def build(version: str) -> Path:
    DIST_DIR.mkdir(exist_ok=True)
    target = DIST_DIR / f"siyuan-plugin-{version}.zip"

    files = iter_package_files()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            info = zipfile.ZipInfo(rel(path), date_time=FIXED_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())

    print(f"built {rel(target)} ({target.stat().st_size} bytes)")
    print(f"sha256 {hashlib.sha256(target.read_bytes()).hexdigest()}")
    for path in files:
        print(f"  + {rel(path)}")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and pack the SiYuan Doubao plugin.")
    parser.add_argument("--check", action="store_true", help="validate only, do not build the archive")
    parser.add_argument("--list", action="store_true", help="list the files that would be packed")
    args = parser.parse_args()

    if args.list:
        for path in iter_package_files():
            print(rel(path))
        return 0

    report, version = validate()
    report.emit()
    if report.errors:
        print(f"\n{len(report.errors)} error(s); package is not releasable")
        return 1
    print(f"package is valid (version {version})")
    if not args.check:
        build(version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
