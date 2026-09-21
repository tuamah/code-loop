#!/usr/bin/env python3
"""The F1 confirmatory review suite: semantic probes over the normalized contracts.

Test tooling, not a CI guard, and deliberately not wired into the workflow. The guards
(`check-f1-continuity.py`, `check-f1-enumerations.py`) prove the contracts did not drift
unacknowledged; this proves a named set of rules is present AND enforced at the point that
enforces it.

It reads through `f1_probe.py`, which unwraps prose without merging sections. Three review rounds
reported a false GAP from line wrapping alone, and one mutation in this suite's own verification
silently failed to apply for the same reason — a probe that breaks on a line break will eventually
pass on a missing rule.

Every probe here is mutation-tested: each was shown to report a GAP when the rule it checks is
deleted or weakened. A probe that has never failed proves nothing. Where a rule already has a
guard, this suite calls that guard rather than re-implementing it — a cruder duplicate of a rule
is a second source of truth, which is the defect AM-39 exists for.

    python scripts/f1-review-suite.py
"""

import sys, re, subprocess, importlib.util; sys.path.insert(0,'scripts')
from f1_probe import f1, normalized, stage2, block, probe, report, DOCS

N = f1(); fails = 0

fails += report("1) NINE SEMANTIC ATTACKS", [probe(k,v,N) for k,v in [
 ("A5  fresh-run laundering","ACCEPT requires a current authenticated PASS on every applicable obligation, for the exact candidate being accepted."),
 ("A7  fresh-task laundering","Obligations are **project-scoped on purpose**: that is what closes A7."),
 ("A9  trivial-change laundering","**Different bytes is not a fixed defect.**"),
 ("A10 applicability narrowing","**Narrowing is deactivation.**"),
 ("A11 task-relation laundering","No task relation, and no combination of them, changes which obligations a candidate must satisfy."),
 ("A13 pre-failure laundering","any guard conditioned on state observed at request time is timing-attackable"),
 ("A14 self-authorized downgrade","A protected object may not define the authority required to weaken its own protection."),
 ("A16 obligation omission at birth","Silence cannot prevent birth any more than it can cause deactivation."),
 ("A17 obligation-class laundering","A protected object may not choose its own protection class either."),
]])

fails += report("2) B2 LINEAGE MATRIX", [probe(k,v,N) for k,v in [
 ("new task, same project","obligations are PROJECT-scoped, not task-scoped"),
 ("new run, same task","`parent_run_commitments` for the same task, assembled by the TCB from its own records"),
 ("repair run on a prior candidate","for the exact candidate being accepted"),
 ("branch / sibling lineage","No inherited PASS, no credit from a sibling candidate, no clearing by novelty."),
 ("superseded candidate","**Supersession records, it never erases.**"),
 ("replay an old PASS into a descendant","A trivially altered descendant must re-satisfy every applicable obligation on itself"),
 ("omission of earlier runs","lineage lives in the TCB, so a caller that simply does not mention earlier runs changes nothing"),
 ("more runs -> easier gate","each one still gets a baseline-bound gate"),
]])

v2, d2 = stage2("VERIFY"), stage2("DECISION")
fails += report("3) B3 OVERRIDE MATRIX (answered AND enforced)", [
 ("who owns the act", "asserted by the verification authority in a signed `VERIFY`" in N),
 ("relation representable", "supersedes" in block("T1A","Common Signed Envelope")),
 ("cond 1 same obligation_id", "same obligation_id" in v2),
 ("cond 2 TCB-recorded descendant", "TCB-recorded descendant" in v2),
 ("cond 3 equal or stronger at head", "equal or stronger" in v2 and "THIS head" in v2),
 ("cond 4 verdict is a PASS", "this verdict is a PASS" in v2),
 ("cond 5 not already superseded", "not already superseded" in v2),
 ("acceptance rule enforced in Stage 2", "current PASS on every obligation" in d2 and "candidate_fingerprint" in d2),
 ("decider reports, never asserts", "the decider reports supersessions, never asserts them" in d2),
 ("raise-only, never lowers burden", "may only raise the burden of a decision, never lower it" in N),
 ("replay cannot become credit", "cannot be replayed into credit" in N),
 ("cannot erase adverse history", "Supersession records, it never erases" in N),
 ("cannot un-exist an obligation", "cannot make an obligation non-existent rather than non-applicable" in N),
], 38)

fails += report("4) R5 BOUNDARY", [
 ("declared, not inferred from order", "never infer it from the order of the records" in N),
 ("causal burden must be declared in T1B", "must **declare that burden here**" in N),
 ("states which claim is being made", "must state which one it is claiming" in N),
], 40)

types = set(re.findall(r"NOGAP::([A-Z]+)::v1\s*\|\|", block("T1A","NOGAP::PROJECT::v1")))
covered = {m.group(1) for l in block("T1A","STAGE 1 — every message").splitlines() if (m:=re.match(r"\s([A-Z]+)\s{2,}\S", l))}
# Do not re-implement the guard: ask it. A cruder duplicate of a rule is a second source of
# truth, which is the very defect AM-39 exists for.
sys.path.insert(0, "scripts")
import importlib
_enum = importlib.import_module("check-f1-enumerations".replace("-", "_")) if False else None
_spec = importlib.util.spec_from_file_location("enumguard", "scripts/check-f1-enumerations.py")
_g = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_g)
t1b_defines_schema = bool(_g.restated_schema(DOCS["T1A"].read_text(), DOCS["T1B"].read_text()))
fails += report("5) STRUCTURAL AUDITS", [
 ("forward representability (supersession)", "supersedes" in block("T1A","Common Signed Envelope")),
 ("forward representability (migration)", "NOGAP::MIGRATION::v1" in N),
 ("forward representability (predicate class)", "predicate_class_map_digest" in block("T1A","Common Signed Envelope")),
 (f"reverse representability {len(covered)}/{len(types)}", types == covered and len(types) > 0),
 ("semantic state/effect (verdict set)", "Statefulness is defined by effect, not by fields (AM-29)" in N),
 ("snapshot mutability", "S is a definition, not a list (AM-30)" in N),
 ("canonical schema uniqueness", "T1B defines no message schema" in N and not t1b_defines_schema),
], 40)

guards = [("enumeration closure T1A+T1B","check-f1-enumerations.py"), ("historical continuity","check-f1-continuity.py")]
fails += report("6) GUARDS", [(k, subprocess.run([sys.executable,f"scripts/{s}"],capture_output=True).returncode==0) for k,s in guards], 40)
print(f"\n{'='*58}\nRound 3 gaps: {fails}\n{'='*58}")
sys.exit(1 if fails else 0)
