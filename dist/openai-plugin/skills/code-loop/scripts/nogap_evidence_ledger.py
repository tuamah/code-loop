#!/usr/bin/env python3
"""Shared evidence-ledger reader (D4-PRE-B2): pure ledger I/O, no imports from this codebase
except the neutral `nogap_errors` module.

`read_evidence_ledger()` is the ONE place that reads .code-loop/runtime/evidence/*.json.
nogap_research.py, nogap_failure.py, nogap_methodology.py and nogap_lifecycle.py all call it
instead of keeping their own copy.

It returns an `EvidenceLedger`, never a bare `None`/`set`/`dict`, so "the ledger does not exist"
and "the ledger exists and is empty" stay explicit at the API instead of being collapsed into one
ambiguous value that every caller has to reconstruct the distinction for. This replaces the old
`set[str] | None` sentinel (which meant "accept everything" at some call sites and, after an
`or set()`, "nothing exists" at others) with a small, unambiguous result object instead of
swapping one sentinel for another.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from nogap_errors import MethodologyValidationError

__all__ = ["EvidenceLedger", "MethodologyValidationError", "read_evidence_ledger"]


@dataclass(frozen=True)
class EvidenceLedger:
    """The result of reading the evidence ledger for one project.

    `exists` says whether .code-loop/runtime/evidence exists as a directory at all.
    `ids` maps each valid evidence id found there to the file it came from - {} both when the
    directory is absent (exists=False) and when it exists but holds no valid records
    (exists=True); the two are still distinguishable via `exists`, on purpose.
    """

    exists: bool
    ids: dict[str, Path] = field(default_factory=dict)

    def __contains__(self, evidence_id: str) -> bool:
        return evidence_id in self.ids


def read_evidence_ledger(project: Path) -> EvidenceLedger:
    """Read .code-loop/runtime/evidence/*.json into an EvidenceLedger.

    Raises MethodologyValidationError on an unreadable/malformed (non-JSON) record, and on a
    duplicate evidence id across two files. A record that parses but has no string "id" field is
    silently skipped (not a member of the ledger), matching the already-accepted D4-PRE-B1
    behaviour in nogap_lifecycle.py that this function generalises.
    """
    evidence_dir = project.resolve() / ".code-loop" / "runtime" / "evidence"
    if not evidence_dir.is_dir():
        return EvidenceLedger(exists=False, ids={})
    ids: dict[str, Path] = {}
    for path in sorted(evidence_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MethodologyValidationError(
                f"evidence ledger: unreadable/malformed evidence record {path}: {exc}"
            ) from exc
        if isinstance(data, dict) and isinstance(data.get("id"), str):
            evidence_id = data["id"]
            if evidence_id in ids:
                raise MethodologyValidationError(
                    f"evidence ledger: duplicate evidence id {evidence_id!r} in {ids[evidence_id]} and {path}"
                )
            ids[evidence_id] = path
    return EvidenceLedger(exists=True, ids=ids)
