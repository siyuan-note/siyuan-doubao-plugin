#!/usr/bin/env python3
# SiYuan - https://github.com/siyuan-note/siyuan
# Copyright (c) 2020-present, b3log.org
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Validate the Doubao plugin package and build the uploadable zip.

The plugin exposes one CLI connector (``com.doubao/cli.json``) backed by the
SiYuan kernel's built-in ``siyuan`` command. No MCP server and no static
credentials are shipped: the kernel CLI reads the local workspace directly.

Rules follow the Doubao plugin protocol. ``plugin.json`` must sit at the
archive root, so the zip is flat.

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
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT / "dist"

# Files at the archive root, in readable order.
ROOT_FILES = ("plugin.json",)
# Directories copied recursively: skills/<name>/..., com.doubao/...
PACKAGE_DIRS = ("skills", "com.doubao")

CONNECTOR_NAME = "siyuan"
CLI_PATH = ROOT / "com.doubao" / "cli.json"
PLATFORMS = ("darwin", "linux", "win32", "default")
# A single plugin may declare at most one CLI, and MCP + CLI together at most five.
MAX_CLI = 1

NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
NPM_INSTALL_RE = re.compile(r"^\s*npm\s+(?:install|i|add)\s+-[gG]\s+\S")

# Platform limits: 16 MB total, at most 1024 entries, 2 MB per file.
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_ENTRIES = 1024
MAX_FILE_BYTES = 2 * 1024 * 1024
# Plugin icon: 512x512, 500 KiB.
ICON_EDGE = 512
MAX_ICON_BYTES = 500 * 1024

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


def image_size(path: Path) -> tuple[str, int, int] | None:
    """Return (format, width, height) for PNG or JPEG, else None."""
    head = path.read_bytes()[:32]
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        width, height = struct.unpack(">II", head[16:24])
        return "png", width, height
    if head[:2] == b"\xff\xd8":
        with path.open("rb") as handle:
            data = handle.read()
        pos = 2
        while pos + 9 < len(data):
            if data[pos] != 0xFF:
                pos += 1
                continue
            marker = data[pos + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3):
                height, width = struct.unpack(">HH", data[pos + 5:pos + 9])
                return "jpeg", width, height
            length = struct.unpack(">H", data[pos + 2:pos + 4])[0]
            if length < 2:
                return None
            pos += 2 + length
    return None


def localized_map(value: object, limit: int) -> str | None:
    """Check a {zh, en} text object; return an error description or None."""
    if not isinstance(value, dict) or not value:
        return "must be a non-empty {zh, en} object"
    for lang, text in value.items():
        if not isinstance(text, str) or not text.strip():
            return f"language {lang!r} must be a non-empty string"
        if len(text) > limit:
            return f"language {lang!r} is {len(text)} chars, over the {limit} limit"
    if not any(str(value.get(lang, "")).strip() for lang in ("zh", "en")):
        return "needs at least one non-empty zh or en value"
    return None


def check_icon(path: Path, label: str, report: Report) -> None:
    if not path.is_file():
        report.error(f"{label} does not exist in the package")
        return
    size = path.stat().st_size
    if size > MAX_ICON_BYTES:
        report.error(f"{label} is {size} bytes, over the 500 KiB icon limit")
    info = image_size(path)
    if info is None:
        report.error(f"{label} must be a PNG or JPEG image")
        return
    fmt, width, height = info
    if (width, height) != (ICON_EDGE, ICON_EDGE):
        report.error(f"{label} is {width}x{height}, platform requires {ICON_EDGE}x{ICON_EDGE}")


def check_plugin_json(path: Path, report: Report) -> tuple[str | None, dict]:
    meta = load_json(path, report)
    if meta is None:
        return None, {}
    version = meta.get("version")
    if not isinstance(version, str) or not SEMVER_RE.match(version):
        report.error(f"plugin.json version must be x.y.z, got {version!r}")

    name = meta.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name) or len(name) > 64:
        report.error(f"plugin.json name {name!r} is not a valid package id")
    elif "--" in name or ".." in name:
        report.error(f"plugin.json name {name!r} must not contain '--' or '..'")

    description = meta.get("description")
    if not isinstance(description, str) or not description.strip():
        report.error("plugin.json description must be a non-empty string")
    elif len(description) > 1024:
        report.error("plugin.json description is over the 1024 char limit")

    extensions = meta.get("extensions")
    if not isinstance(extensions, dict):
        report.error('plugin.json must declare extensions["com.doubao"]')
        return version if isinstance(version, str) else None, {}
    doubao = extensions.get("com.doubao")
    if not isinstance(doubao, dict):
        report.error('plugin.json is missing extensions["com.doubao"]')
        return version if isinstance(version, str) else None, {}

    for field, limit in (("displayName", 128), ("displayDescription", 1024)):
        problem = localized_map(doubao.get(field), limit)
        if problem:
            report.error(f"extensions.com.doubao.{field} {problem}")

    icon = doubao.get("icon")
    if not isinstance(icon, str) or not icon.startswith("./"):
        report.error(f'extensions.com.doubao.icon {icon!r} must be a "./" package path')
    else:
        check_icon(ROOT / icon.lstrip("./"), f"icon {icon}", report)

    if "mcpServers" in doubao:
        report.error("extensions.com.doubao.mcpServers is set but no mcp.json is shipped")
    if (ROOT / "mcp.json").exists():
        report.error("mcp.json must be removed: this plugin uses a local CLI connector")

    return version if isinstance(version, str) else None, doubao


def check_cli_json(report: Report) -> None:
    cli = load_json(CLI_PATH, report)
    if cli is None:
        return
    connectors = cli.get("connectors")
    if not isinstance(connectors, dict) or not connectors:
        report.error("cli.json must declare a non-empty connectors object")
        return
    if len(connectors) > MAX_CLI:
        report.error(f"cli.json declares {len(connectors)} CLI connectors, at most {MAX_CLI} allowed")
    for name, config in connectors.items():
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            report.error(f"CLI connector name {name!r} must be non-empty with no surrounding whitespace")
        if name != CONNECTOR_NAME:
            report.error(f'CLI connector name must be "{CONNECTOR_NAME}", got {name!r}')
        if not isinstance(config, dict):
            report.error(f"CLI connector {name!r} must be a JSON object")
            continue

        install = config.get("install")
        if not isinstance(install, dict) or not install:
            report.error(f"CLI connector {name!r} must declare a non-empty install object")
        else:
            if not (set(install) & {"linux", "default"}):
                report.error(f"CLI connector {name!r} install must provide 'linux' or 'default'")
            for platform, commands in install.items():
                if platform not in PLATFORMS:
                    report.error(f"CLI connector {name!r} install has unknown platform {platform!r}")
                if not isinstance(commands, list) or not commands or not all(
                    isinstance(cmd, str) and cmd.strip() for cmd in commands
                ):
                    report.error(f"CLI connector {name!r} install.{platform} must be a non-empty string array")
                    continue
                if platform in ("linux", "default"):
                    for cmd in commands:
                        if not NPM_INSTALL_RE.match(cmd):
                            report.error(
                                f"CLI connector {name!r} install.{platform} must be an npm global install "
                                f"command on Linux, got {cmd!r}"
                            )

        for field in ("auth", "status"):
            value = config.get(field)
            if value is None:
                continue
            if not isinstance(value, dict) or not value:
                report.error(f"CLI connector {name!r} {field} must be a non-empty object when present")
                continue
            if not (set(value) & {"linux", "default"}):
                report.error(f"CLI connector {name!r} {field} must provide 'linux' or 'default'")
            for platform, commands in value.items():
                if platform not in PLATFORMS:
                    report.error(f"CLI connector {name!r} {field} has unknown platform {platform!r}")
                if not isinstance(commands, list) or not commands or not all(
                    isinstance(cmd, str) and cmd.strip() for cmd in commands
                ):
                    report.error(f"CLI connector {name!r} {field}.{platform} must be a non-empty string array")

        if "auth" in config:
            report.error(
                f"CLI connector {name!r} declares auth, but the SiYuan kernel CLI needs no credentials"
            )

        pattern = config.get("statusMatchRegex")
        if pattern is not None:
            if not isinstance(pattern, str) or not pattern:
                report.error(f"CLI connector {name!r} statusMatchRegex must be a non-empty string")
            else:
                try:
                    re.compile(pattern)
                except re.error as err:
                    report.error(f"CLI connector {name!r} statusMatchRegex is not a valid regex: {err}")

    auth_dir = ROOT / "com.doubao" / "auth"
    if auth_dir.exists():
        report.error("com.doubao/auth/ must be removed: static credentials are not used by the kernel CLI")
    if (ROOT / "mcp.json").exists():
        report.error("mcp.json must be removed: a CLI connector cannot coexist with this MCP service key")


def check_skills(report: Report) -> None:
    skills_dir = ROOT / "skills"
    entries = sorted(p for p in skills_dir.iterdir() if p.is_dir()) if skills_dir.is_dir() else []
    if not entries:
        report.error("skills/ has no skill directory")
        return
    for entry in entries:
        skill = entry / "SKILL.md"
        if not skill.is_file():
            report.error(f"missing {rel(skill)}")
            continue
        parts = skill.read_text(encoding="utf-8").split("---")
        if len(parts) < 3 or not parts[1].strip():
            report.error(f"{rel(skill)} has no YAML frontmatter")
            continue
        front = parts[1]
        name = re.search(r"^name:\s*(\S+)", front, re.MULTILINE)
        if not name or name.group(1) != entry.name:
            report.error(f"{rel(skill)} frontmatter name must match directory {entry.name!r}")
        if not re.search(r"^description:\s*\S", front, re.MULTILINE):
            report.error(f"{rel(skill)} frontmatter is missing description")
        for key in ("display_name", "display_description"):
            if not re.search(rf"^\s+{key}:\s*\S", front, re.MULTILINE):
                report.error(f"{rel(skill)} metadata is missing {key}")


def validate() -> tuple[Report, str | None]:
    report = Report()
    for name in ROOT_FILES:
        if not (ROOT / name).is_file():
            report.error(f"missing {name}")

    version, _ = check_plugin_json(ROOT / "plugin.json", report)
    check_cli_json(report)
    check_skills(report)

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
