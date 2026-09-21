#!/usr/bin/env python3
"""Rebuild the distributed copies of the skill from the source tree - and verify they match.

`dist/` and `code-loop.zip` are copies of files that already exist at the repository
root. Copies drift: before this script existed, the packaged plugins were missing 14 of
the 21 runtime modules, so `nogap.py` in `dist/` exposed 11 subcommands while the source
exposed 20 - every M6/M7/M8 capability was absent from what users actually install. The
archive was worse than stale: it had been built without directory paths, flattening 168
files into one namespace where five different `README.md` entries collided.

Nothing here is generated or transformed. Every packaged file is a byte-identical copy
of its source, so `--check` can be an exact comparison rather than a heuristic, and CI
can fail the moment source and package disagree.

    python scripts/build-dist.py            # rewrite dist/ and code-loop.zip
    python scripts/build-dist.py --check    # verify only; non-zero exit on drift
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# What a consumer of the skill needs. Deliberately NOT the whole repository: tests,
# benchmarks, CI workflows, and the packaging outputs themselves stay out.
SKILL_PATHS = [
    "AGENTS.md",
    "README.md",
    "SKILL.md",
    ".code-loop-template",
    "agents",
    "council",
    "dashboard",
    "docs",
    "references",
    "runtime",
    "scripts",
]

# The two plugin trees. Each gets the same skill payload; their own manifests
# (.codex-plugin/, .claude-plugin/) live outside these directories and are never touched.
SKILL_TARGETS = [
    "dist/openai-plugin/skills/code-loop",
    "dist/claude-marketplace/plugins/code-loop-plugin/skills/code-loop",
]

# The standalone archive additionally carries the licence and the editor rule files,
# because it is what someone downloads and unpacks by hand rather than installs.
ARCHIVE_PATH = "code-loop.zip"
ARCHIVE_PREFIX = "code-loop"
ARCHIVE_PATHS = SKILL_PATHS + ["LICENSE", ".clinerules", ".cursor", ".windsurf"]

EXCLUDED_DIRS = {"__pycache__"}
EXCLUDED_SUFFIXES = {".pyc"}

# Fixed so a rebuild of unchanged sources produces a byte-identical archive: without it
# every run would embed the current time and --check could never be an exact comparison.
ARCHIVE_TIMESTAMP = (2026, 1, 1, 0, 0, 0)


def _is_excluded(path: Path) -> bool:
    return bool(EXCLUDED_DIRS.intersection(path.parts)) or path.suffix in EXCLUDED_SUFFIXES


def collect(paths: list[str]) -> list[str]:
    """Source-relative file paths for a manifest, sorted for stable output."""
    files: list[str] = []
    for entry in paths:
        source = ROOT / entry
        if source.is_file():
            files.append(entry)
        elif source.is_dir():
            files.extend(
                str(path.relative_to(ROOT))
                for path in source.rglob("*")
                if path.is_file() and not _is_excluded(path)
            )
        else:
            raise SystemExit(f"FAIL: packaged path does not exist in the source tree: {entry}")
    return sorted(files)


def sync_tree(target: Path, files: list[str]) -> None:
    """Replace the target with an exact copy of the manifest.

    The tree is removed first so a file deleted from the source cannot survive in the
    package: a stale module left behind is exactly the drift this script exists to stop.
    """
    if target.exists():
        shutil.rmtree(target)
    for name in files:
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)


def check_tree(target: Path, files: list[str]) -> list[str]:
    expected = set(files)
    problems = []
    for name in sorted(expected):
        destination = target / name
        if not destination.is_file():
            problems.append(f"missing from package: {name}")
        elif not filecmp.cmp(ROOT / name, destination, shallow=False):
            problems.append(f"differs from source: {name}")
    if target.is_dir():
        for path in sorted(target.rglob("*")):
            if path.is_file() and not _is_excluded(path):
                name = str(path.relative_to(target))
                if name not in expected:
                    problems.append(f"not in the source manifest: {name}")
    return problems


def write_archive(archive: Path, files: list[str]) -> None:
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in files:
            info = zipfile.ZipInfo(f"{ARCHIVE_PREFIX}/{name}", date_time=ARCHIVE_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            bundle.writestr(info, (ROOT / name).read_bytes())


def check_archive(archive: Path, files: list[str]) -> list[str]:
    if not archive.is_file():
        return [f"missing archive: {archive.name}"]
    expected = {f"{ARCHIVE_PREFIX}/{name}": (ROOT / name).read_bytes() for name in files}
    problems = []
    with zipfile.ZipFile(archive) as bundle:
        present = {name for name in bundle.namelist() if not name.endswith("/")}
        for name, payload in expected.items():
            if name not in present:
                problems.append(f"missing from archive: {name}")
            elif bundle.read(name) != payload:
                problems.append(f"differs from source in archive: {name}")
        for name in sorted(present - set(expected)):
            problems.append(f"not in the source manifest, in archive: {name}")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="verify without writing; exit non-zero on drift")
    args = parser.parse_args()

    skill_files = collect(SKILL_PATHS)
    archive_files = collect(ARCHIVE_PATHS)

    if args.check:
        problems: list[str] = []
        for target in SKILL_TARGETS:
            problems.extend(f"{target}: {problem}" for problem in check_tree(ROOT / target, skill_files))
        problems.extend(f"{ARCHIVE_PATH}: {problem}" for problem in check_archive(ROOT / ARCHIVE_PATH, archive_files))
        if problems:
            print("FAIL: packaged copies do not match the source tree", file=sys.stderr)
            for problem in problems:
                print(f"  {problem}", file=sys.stderr)
            print("\nRun: python scripts/build-dist.py", file=sys.stderr)
            raise SystemExit(1)
        print(f"OK: packages match the source tree ({len(skill_files)} skill files, {len(archive_files)} archived)")
        return

    for target in SKILL_TARGETS:
        sync_tree(ROOT / target, skill_files)
        print(f"synced {target} ({len(skill_files)} files)")
    write_archive(ROOT / ARCHIVE_PATH, archive_files)
    print(f"wrote {ARCHIVE_PATH} ({len(archive_files)} files)")


if __name__ == "__main__":
    main()
