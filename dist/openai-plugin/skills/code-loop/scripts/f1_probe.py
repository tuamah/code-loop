#!/usr/bin/env python3
"""Normalized probe surface for the F1 contracts.

This is test tooling, not a guard. It changes how a probe *reads* the contracts and nothing about
what the contracts say.

Three consecutive review rounds reported a false GAP — A2's worker clause, the
`predicate_identity -> obligation_class -> required authority` chain, and the `is a PASS`
supersession condition. All three were real and in force; the probes matched raw text while the
documents wrap at 100 columns, and one of them carried a `> ` blockquote marker on its
continuation line. A probe that fails on a line break is a probe that will eventually pass on a
missing rule for the same reason.

So: unwrap prose, strip blockquote markers, and leave everything else exactly as it is.

**What is deliberately NOT normalized.** Sections are never merged and text is never reordered —
that would hide an anchor collision or a duplicate section, which are the defects rounds 19 and 20
were built to catch. Fenced blocks and tables keep their line structure, because a Stage 2 clause
list and a schema table mean something as lines. The normalizer joins wrapped prose within one
block of one section, and does nothing else.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = {
    "T1A": ROOT / "docs" / "f1-t1a-trust-core.md",
    "T1B": ROOT / "docs" / "f1-t1b-policy-obligations.md",
}


def sections(text: str) -> list[tuple[str, str]]:
    """(heading, body) per section, in document order. Boundaries are preserved exactly."""
    out, heading, buf = [], "", []
    for line in text.splitlines():
        if line.startswith("#"):
            if heading or buf:
                out.append((heading, "\n".join(buf)))
            heading, buf = line, []
        else:
            buf.append(line)
    out.append((heading, "\n".join(buf)))
    return out


def unwrap(body: str) -> str:
    """Join wrapped prose lines; leave fences and tables alone."""
    out, para, fenced = [], [], False
    for line in body.splitlines():
        if line.startswith("```"):
            fenced = not fenced
            if para:
                out.append(" ".join(para))
                para = []
            out.append(line)
            continue
        if fenced or line.lstrip().startswith("|") or re.match(r"^ {4,}\S", line):
            if para:
                out.append(" ".join(para))
                para = []
            out.append(line)
            continue
        stripped = re.sub(r"^\s*>\s?", "", line).strip()
        if stripped:
            para.append(stripped)
        else:
            if para:
                out.append(" ".join(para))
                para = []
            out.append("")
    if para:
        out.append(" ".join(para))
    return "\n".join(out)


def normalized(name: str) -> str:
    """The document with prose unwrapped, section boundaries and block structure intact."""
    text = DOCS[name].read_text(encoding="utf-8")
    return "\n".join(f"{h}\n{unwrap(b)}" for h, b in sections(text))


def f1() -> str:
    return normalized("T1A") + "\n" + normalized("T1B")


def block(name: str, first_line_startswith: str) -> str:
    """One fenced block, by the start of its first line. Line structure preserved."""
    for b in re.findall(r"```\n(.*?)\n```", DOCS[name].read_text(encoding="utf-8"), re.S):
        if b.splitlines()[0].strip().startswith(first_line_startswith):
            return b
    return ""


def stage2(message_type: str) -> str:
    """One message type's Stage 2 clause, unwrapped."""
    body = block("T1A", "STAGE 1 — every message")
    chunk = re.search(rf"\n {message_type}\s{{2,}}(.*?)(?=\n [A-Z]+\s{{2,}}|\Z)", body, re.S)
    return " ".join(chunk.group(1).split()) if chunk else ""


def probe(label: str, needle: str, haystack: str) -> tuple[str, bool]:
    return label, " ".join(needle.split()) in " ".join(haystack.split())


def report(title: str, results: list[tuple[str, bool]], width: int = 40) -> int:
    print(f"\n{title}\n")
    for label, ok in results:
        print(f"  {label:{width}} {'BLOCKED' if ok else '*** GAP'}")
    return sum(1 for _, ok in results if not ok)
