#!/usr/bin/env python3
"""Enumeration closure check for F1-T1A's CLOSED + CHECKED vocabularies.

T1A §-1 forbids security by remembered list: every security-significant enumeration must be
DERIVED from a property, CLOSED with a mechanical check, or explicitly NON-NORMATIVE. This
script is the mechanical check for the closed ones.

Round 20 attacked it along eight paths and six landed. All six had one root cause: **the guard
derived the universe, the canonical source, the representation and the content from the very
material it was checking.**

    truncation      delete HUMAN from all four sites          -> passed (11 became 10, consistently)
    fabrication     add a 12th type to all four sites         -> passed (a peer of the other eleven)
    substitution    a "revised action enum" placed earlier    -> passed (re.search took the first)
    representation  the same set as an indented code block    -> passed (never scanned)
    drift           widen a closed action enum with `bypass`  -> passed (presence, not content)
    self-exemption  declare a real enum ILLUSTRATIVE          -> passed (the governor scoped itself)

    shadow          a second block with the same first line   -> blocked (AM-35's bijection)
    laundering      a new block under a broad declared prefix -> blocked (AM-35's bijection)

So §-1 now carries a commitment block: the message-type universe and a digest per governed
enumeration, pinned in advance. Deleting, adding, widening or re-representing an enumeration
contradicts a line someone has to edit deliberately — the AM-37 rule applied to content.

    python scripts/check-f1-enumerations.py
    python scripts/check-f1-enumerations.py --update-commitment   # acknowledge reviewed edits
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
T1A = ROOT / "docs" / "f1-t1a-trust-core.md"


def digest(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()[:12]


def enumerations(text: str) -> list[tuple[str, str]]:
    """Every enumeration in the document, as (first line, full text).

    Fenced blocks, tables and indented code blocks. Round 20 moved a closed set into an indented
    block and it left the guard's sight entirely; a representation the guard does not read is a
    representation an enumeration can hide in.
    """
    found = []
    for block in re.findall(r"```\n(.*?)\n```", text, re.S):
        if block.startswith("COMMITMENT"):
            # The pin is not one of the things it pins: digesting a block that contains its own
            # digest cannot close. Its own integrity is the continuity guard's job — §-1 is a
            # digested section there, so an edit to this block fails that check instead.
            continue
        found.append((block.splitlines()[0].strip(), block))
    for header, body in re.findall(r"\n\|(.+?)\|\n\|[-| :]+\|\n((?:\|.*\n)*)", text):
        found.append((f"TABLE |{header.strip()}", header + "\n" + body))
    # Indented blocks: four-space runs that are not inside a fence and not list continuations.
    outside, fenced = [], False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
            outside.append("")
        else:
            outside.append("" if fenced else line)
    run: list[str] = []
    for line in outside + [""]:
        if re.match(r"^ {4,}\S", line):
            run.append(line)
        else:
            if len(run) >= 2:
                found.append((run[0].strip(), "\n".join(run)))
            run = []
    return found


def commitment(text: str) -> tuple[dict[str, str], int, str] | None:
    """§-1's pinned universe. Never derived from the enumerations it commits to."""
    block = re.search(r"```\nCOMMITMENT.*?\n(.*?)\n```", text, re.S)
    if not block:
        return None
    pinned, types, types_digest = {}, 0, ""
    for line in block.group(1).splitlines():
        m = re.match(r"^MESSAGE_TYPES:\s*(\d+)\s+([0-9a-f]{12})\s*$", line)
        if m:
            types, types_digest = int(m.group(1)), m.group(2)
            continue
        m = re.match(r"^([0-9a-f]{12}|PENDING)\s+(.+?)\s*$", line)
        if m:
            pinned[m.group(2)] = m.group(1)
    return pinned, types, types_digest


def main() -> int:
    if not T1A.is_file():
        print(f"FAIL: missing {T1A.relative_to(ROOT)}", file=sys.stderr)
        return 1
    text = T1A.read_text(encoding="utf-8")
    problems: list[str] = []

    # The manifest classifies; the bijection below makes each prefix name exactly one enumeration,
    # so a prefix is a usable handle on a canonical source (AM-35).
    manifest = re.search(r"```\n((?:GOVERNED|ILLUSTRATIVE)\s*::.*?)\n```", text, re.S)
    if not manifest:
        print("FAIL: §-1's closure manifest is missing — AM-33 requires it as the canonical source",
              file=sys.stderr)
        return 1
    declared: list[tuple[str, str]] = []
    roles: dict[str, str] = {}
    for line in manifest.group(1).splitlines():
        m = re.match(r"(GOVERNED|ILLUSTRATIVE)\s*::\s*(.+)::(.+)$", line)
        if m:
            # Split at the LAST separator: a prefix may itself contain "::" (NOGAP::PROJECT::v1),
            # and a non-greedy match truncated it to "NOGAP" — which is why a shadow block could
            # only ever be caught as an ambiguity rather than named.
            prefix = m.group(2).strip()
            role = m.group(3).split("—")[0].strip()
            declared.append((m.group(1), prefix))
            if m.group(1) == "GOVERNED":
                if role in roles:
                    problems.append(f"two governed enumerations claim the role {role!r}: "
                                    f"{roles[role]!r} and {prefix!r}; a role has one canonical source")
                roles[role] = prefix
    if not declared:
        problems.append("§-1's closure manifest has no parsable entries")

    found = enumerations(text)
    firsts = [f for f, _ in found]
    body_of: dict[str, str] = {}
    for kind, prefix in declared:
        hits = [(f, b) for f, b in found if f.startswith(prefix)]
        if len(hits) == 0:
            problems.append(f"manifest entry matches nothing — stale declaration: {prefix!r}")
        elif len(hits) > 1:
            problems.append(
                f"manifest prefix {prefix!r} matches {len(hits)} enumerations; it must identify "
                f"exactly one, or a new one enters undeclared behind it")
        elif kind == "GOVERNED":
            body_of[prefix] = hits[0][1]
    for first in firsts:
        matched = [p for _, p in declared if first.startswith(p)]
        if not matched:
            problems.append(f"undeclared enumeration, not in §-1's manifest: {first[:64]!r}")
        elif len(matched) > 1:
            problems.append(f"enumeration {first[:48]!r} is claimed by {len(matched)} manifest entries")

    # The canonical source is named by its manifest prefix, never found by document order. Round 20
    # placed a "revised action enum" earlier in the file and re.search made it canonical.
    def canonical(role: str) -> str:
        return body_of.get(roles.get(role, ""), "")

    domains = set(re.findall(r"NOGAP::([A-Z]+)::v1\s*\|\|", canonical("domain list")))

    actions: dict[str, list[str]] = {}
    for line in canonical("action enum").splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            actions[parts[0]] = [a.strip() for a in parts[1].split("|") if a.strip()]

    bodies = {m.group(1) for line in canonical("envelope + body schemas").splitlines()
              if (m := re.match(r"\s{2}([A-Z]+)\s{2,}\S", line))}
    stage2 = {m.group(1) for line in canonical("admissibility").splitlines()
              if (m := re.match(r"\s([A-Z]+)\s{2,}\S", line))}

    for name, got in (("domain list", domains), ("action enum", set(actions)),
                      ("body schema", bodies), ("Stage 2 clause", stage2)):
        if not got:
            problems.append(f"no {name} found under its manifest prefix — the canonical source is "
                            f"missing or reshaped")
    for name, got in (("action enum", set(actions)), ("body schema", bodies),
                      ("Stage 2 clause", stage2)):
        for missing in sorted(domains - got):
            problems.append(f"{missing}: has a signing domain but no {name}")
        for extra in sorted(got - domains):
            problems.append(f"{extra}: has a {name} but no signing domain")
    for message_type, verbs in sorted(actions.items()):
        if not verbs:
            problems.append(f"{message_type}: action enum is empty; a type with no action cannot "
                            f"be granted (AM-20)")

    # AM-38: the universe and the content of every governed enumeration are pinned in advance.
    # Consistency across four sites proves they agree, never that they are the agreed set.
    pin = commitment(text)
    updates: dict[str, str] = {}
    if pin is None:
        problems.append("§-1 carries no COMMITMENT block; without one the guard derives the "
                        "expected universe from material that may itself be truncated or forged")
    else:
        pinned, n_types, types_digest = pin
        actual_types = digest(" ".join(sorted(domains)))
        if len(domains) != n_types or actual_types != types_digest:
            problems.append(
                f"message-type universe is not the committed one: §-1 pins {n_types} types "
                f"({types_digest}), the document carries {len(domains)} ({actual_types})")
        for kind, prefix in declared:
            if kind != "GOVERNED":
                continue
            if prefix not in pinned:
                problems.append(f"governed enumeration is not pinned in §-1's commitment: {prefix!r}")
            elif prefix in body_of:
                now = digest(body_of[prefix])
                if pinned[prefix] != now:
                    updates[prefix] = now
        for prefix in pinned:
            if prefix not in {p for k, p in declared if k == "GOVERNED"}:
                problems.append(f"§-1 pins an enumeration the manifest no longer governs: {prefix!r}")
        n_illustrative = sum(1 for k, _ in declared if k == "ILLUSTRATIVE")
        m = re.search(r"^ILLUSTRATIVE_ENTRIES:\s*(\d+)\s*$", text, re.M)
        if not m:
            problems.append("§-1 does not pin how many ILLUSTRATIVE entries exist; without it the "
                            "manifest can exempt a real enumeration by declaring one more")
        elif int(m.group(1)) != n_illustrative:
            problems.append(f"§-1 pins {m.group(1)} ILLUSTRATIVE entries, the manifest carries "
                            f"{n_illustrative}; a new exemption must be declared deliberately")

    if "--update-commitment" in sys.argv and updates and not problems:
        out = text
        for prefix, new in updates.items():
            out = re.sub(rf"^([0-9a-f]{{12}}|PENDING)(\s+{re.escape(prefix)}\s*)$",
                         rf"{new}\g<2>", out, flags=re.M)
        m = re.search(r"^MESSAGE_TYPES:\s*\d+\s+[0-9a-f]{12}\s*$", out, re.M)
        if m:
            out = out[:m.start()] + f"MESSAGE_TYPES: {len(domains)} {digest(' '.join(sorted(domains)))}" + out[m.end():]
        T1A.write_text(out, encoding="utf-8")
        print(f"acknowledged {len(updates)} reviewed enumeration change(s): " + ", ".join(sorted(updates)))
        return 0
    for prefix, now in sorted(updates.items()):
        problems.append(f"governed enumeration changed: {prefix!r} (§-1 pins {pinned[prefix]}, now "
                        f"{now}). Review it; if the change is editorial, re-run with "
                        f"--update-commitment to acknowledge it.")

    if problems:
        print("FAIL: F1-T1A closed vocabularies disagree", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print("\nSee T1A §-1: a CLOSED + CHECKED enumeration must have one canonical source, every "
              "dependent site must agree, and its universe and content are pinned in advance.",
              file=sys.stderr)
        return 1

    print(f"OK: F1-T1A closed vocabularies agree ({len(domains)} committed message types; domain, "
          f"action enum, body schema and Stage 2 clause present for each; "
          f"{len(body_of)} governed enumerations match their pinned digests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
