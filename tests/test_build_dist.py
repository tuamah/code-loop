#!/usr/bin/env python3
"""The packaging guard must itself be guarded.

CI's only defence against `dist/` and `code-loop.zip` falling behind the source is
`build-dist.py --check`. A check that cannot fail is worse than no check: it reports
success over drift. These tests introduce each kind of drift into a throwaway copy of
the repository and assert the check rejects it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_TARGET = "dist/openai-plugin/skills/code-loop"


def run_check(project: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/build-dist.py", "--check"],
        cwd=project, text=True, capture_output=True,
    )


def run_build(project: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/build-dist.py"],
        cwd=project, text=True, capture_output=True, check=True,
    )


class BuildDistTests(unittest.TestCase):
    """Each test works on its own copy, so none of them can touch the real repository."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name) / "code-loop"
        shutil.copytree(
            ROOT, self.project,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
        )
        run_build(self.project)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_freshly_built_packages_pass(self) -> None:
        result = run_check(self.project)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("packages match the source tree", result.stdout)

    def test_build_is_deterministic(self) -> None:
        archive = (self.project / "code-loop.zip").read_bytes()
        run_build(self.project)
        self.assertEqual(archive, (self.project / "code-loop.zip").read_bytes())

    def test_changed_source_file_is_detected(self) -> None:
        # The real failure mode: someone edits a module and forgets to rebuild.
        target = self.project / "scripts" / "nogap_verify_binding.py"
        target.write_text(target.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
        result = run_check(self.project)
        self.assertEqual(result.returncode, 1)
        self.assertIn("differs from source: scripts/nogap_verify_binding.py", result.stderr)

    def test_module_missing_from_package_is_detected(self) -> None:
        # This is what actually shipped: 14 runtime modules absent from the plugins.
        (self.project / SKILL_TARGET / "scripts" / "nogap_decision.py").unlink()
        result = run_check(self.project)
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing from package: scripts/nogap_decision.py", result.stderr)

    def test_file_deleted_from_source_does_not_survive_in_the_package(self) -> None:
        (self.project / "references" / "risk-matrix.md").unlink()
        run_build(self.project)
        self.assertFalse((self.project / SKILL_TARGET / "references" / "risk-matrix.md").exists())

    def test_stray_file_in_package_is_detected(self) -> None:
        (self.project / SKILL_TARGET / "scripts" / "leftover.py").write_text("stale\n", encoding="utf-8")
        result = run_check(self.project)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not in the source manifest: scripts/leftover.py", result.stderr)

    def test_stale_archive_is_detected(self) -> None:
        target = self.project / "SKILL.md"
        target.write_text(target.read_text(encoding="utf-8") + "\ndrift\n", encoding="utf-8")
        shutil.copyfile(target, self.project / SKILL_TARGET / "SKILL.md")
        shutil.copyfile(
            target,
            self.project / "dist/claude-marketplace/plugins/code-loop-plugin/skills/code-loop/SKILL.md",
        )
        result = run_check(self.project)
        self.assertEqual(result.returncode, 1, "trees matched, so only the archive can still be stale")
        self.assertIn("code-loop.zip: differs from source in archive: code-loop/SKILL.md", result.stderr)

    def test_archive_keeps_directory_structure(self) -> None:
        # The committed archive had been flattened: 168 files in one namespace, with
        # five different README.md entries overwriting each other on extraction.
        with zipfile.ZipFile(self.project / "code-loop.zip") as bundle:
            names = [n for n in bundle.namelist() if not n.endswith("/")]
        self.assertEqual(len(names), len(set(names)), "archive must not contain colliding names")
        self.assertTrue(all(n.startswith("code-loop/") for n in names))
        self.assertIn("code-loop/scripts/nogap_decision.py", names)
        self.assertIn("code-loop/.code-loop-template/task.yaml", names)

    def test_packaged_cli_exposes_the_same_commands_as_the_source(self) -> None:
        # The symptom that made the drift visible: the packaged nogap.py offered 11
        # subcommands while the source offered 20.
        def usage(script: Path) -> str:
            return subprocess.run(
                [sys.executable, str(script), "--help"], text=True, capture_output=True, check=True,
            ).stdout.split("options:")[0]

        self.assertEqual(
            usage(self.project / "scripts" / "nogap.py"),
            usage(self.project / SKILL_TARGET / "scripts" / "nogap.py"),
        )

    def test_compiled_artifacts_are_never_packaged(self) -> None:
        cache = self.project / "scripts" / "__pycache__"
        cache.mkdir(exist_ok=True)
        (cache / "nogap.cpython-312.pyc").write_bytes(b"\x00compiled")
        run_build(self.project)
        self.assertEqual(run_check(self.project).returncode, 0)
        self.assertFalse((self.project / SKILL_TARGET / "scripts" / "__pycache__").exists())


if __name__ == "__main__":
    unittest.main()
