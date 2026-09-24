# D6 — RUNTIME_STRUCTURE Schema Contract (`P9_RUNTIME_STRUCTURE`)

Status: **Rev 2 — REPAIR applied, still not accepted.** This document fixes the semantics of a new
artifact type before any resolver or schema code exists, per `docs/f2b-semantic-contract-
proposal.md` §3.1: "It MUST NOT be designed incidentally inside a resolver." No production file
changes until this contract is reviewed and accepted; `RUNTIME_STRUCTURE` stays in
`DEFERRED_KINDS` until then.

`P9_GOVERNANCE` stays untouched and conceptually separate: governance says who owns what and what
policy applies. `P9_RUNTIME_STRUCTURE` says what components exist, how they connect, and what
trust/execution boundaries separate them. Neither artifact may duplicate the other's fields; a
boundary that needs a policy points at `P9_GOVERNANCE` by ref, it never copies policy content in.

## 1. Closed enums

### 1.1 `Plane` (6 values, from `docs/nogapcode-runtime.md` § Planes — no new names)

```
CONTROL_DECISION
EXECUTION
TOOL_CAPABILITY
VERIFICATION_EVIDENCE
STATE_EVENT
OBSERVABILITY
```

### 1.2 `AuthorityRole` (5 values, from `docs/nogapcode-runtime.md` § Authority Model — no new names)

```
execution
verification
acceptance
human
tool
```

### 1.3 `BoundaryType`

```
authority
trust
execution
verification
state
```

### 1.4 `EnforcementStatus`

```
ENFORCED
DOCUMENTED_ONLY
```

## 2. `P9_RUNTIME_STRUCTURE` field contract

```
required_fields:
  - components
  - boundaries
  - plane_status
  - runtime_structure_version
```

`runtime_structure_version` MUST be one of a closed contract-version set, not an arbitrary
non-empty string: `{"1"}` at this contract's freeze (a future contract revision that changes the
schema shape adds its own new value to this set — it is never widened silently by a resolver). A
value outside the set is `INVALID`, not `MISSING`: the field is present, its content is wrong.

### 2.0 `plane_status` (top-level, REPAIR — replaces the rejected `boundaries[].plane` field)

```
plane_status: map[Plane -> EnforcementStatus]
```

Exactly the 6 keys of `Plane` (§1.1), each mapped to one `EnforcementStatus` value (§1.4). This is
the sole declaration of which Planes are actually represented in this runtime version and which are
documented intent only. It is declared once, top-level, never derived from or duplicated onto
`boundaries[]` — a boundary's own Plane membership is always read by dereferencing its endpoint
components' `plane` field (§2.1), never stored redundantly on the boundary itself, so there is one
source of truth for "what Plane is this" per entity (components declare it; boundaries derive it).

### 2.1 `components[]` (each entry)

| field | type | constraint |
|---|---|---|
| `component_id` | string | non-empty; unique within the artifact |
| `plane` | string | one of `Plane` (§1.1) — the sole declaration point for Plane membership (see §2.0) |
| `implementation_ref` | string | see §2.3 for syntax; MUST resolve to a real path inside the repository at validation time (see §3.3) — not a free-text description |
| `authority_roles` | list[string] | non-empty; each value one of `AuthorityRole` (§1.2); MUST NOT contain both `execution` and `acceptance` (see §3.6) |

### 2.2 `boundaries[]` (each entry)

| field | type | constraint |
|---|---|---|
| `boundary_id` | string | non-empty; unique within the artifact |
| `source_component_id` | string | MUST equal some `components[].component_id` in the same artifact (see §3.4) |
| `target_component_id` | string | MUST equal some `components[].component_id` in the same artifact (see §3.4) |
| `boundary_type` | string | one of `BoundaryType` (§1.3) |
| `permitted_flows` | list[string] | non-empty; free-text tokens naming what may cross (e.g. `"claims_only"`, `"no_accept"`) — vocabulary not closed at this contract level, left to the authoring artifact; a resolver never rejects on token content, only on the field being present and non-empty |
| `enforcement_status` | string | one of `EnforcementStatus` (§1.4) |
| `enforcement_ref` | string or null | REQUIRED (non-null, non-empty, resolvable) when `enforcement_status == ENFORCED`; MUST be `null` when `enforcement_status == DOCUMENTED_ONLY` — a non-null value there is itself `INVALID` (see §3.5) |

No `plane` field on `boundaries[]` (REPAIR, Rev 2): a boundary's Plane membership is derived by a
resolver by dereferencing `source_component_id`/`target_component_id` into `components[].plane` —
never stored on the boundary, so it cannot disagree with its own endpoints.

### 2.3 `implementation_ref` / `enforcement_ref` syntax

Both fields hold a **repository-relative path or dotted module path**, not a description:

- Repository-relative path form: relative to the repo root, using `/` separators, no leading `/`,
  no `..` path segments (traversal outside the repo root is rejected as `INVALID`, not silently
  normalized).
- Dotted module form: a Python-importable dotted path resolvable under `scripts/` (e.g.
  `nogap_verification.required_commands_from_gate`), same traversal restriction applies to the
  module's underlying file.
- Existence-only guarantee: a resolver checks that the referenced path/module **exists** in the
  repository at validation time. This proves the reference is not fabricated; it does NOT prove the
  referenced code actually implements the claimed behavior — that functional claim is outside this
  contract's scope and is not asserted here.

## 3. Validation invariants (all fail-closed; each maps to one failure class in §4)

1. **V-DUP-COMPONENT**: `component_id` values in `components[]` are pairwise unique.
2. **V-DUP-BOUNDARY**: `boundary_id` values in `boundaries[]` are pairwise unique.
3. **V-ENDPOINT**: every `boundaries[].source_component_id` and `boundaries[].target_component_id`
   resolves to an existing `component_id` in the same artifact's `components[]`.
4. **V-IMPL-REF**: every `components[].implementation_ref` resolves to a real, existing module or
   path in the repository (existence check at validation time — a string that merely looks
   plausible does not pass).
5. **V-ENFORCEMENT-REF**: if `boundaries[].enforcement_status == ENFORCED`, then `enforcement_ref`
   is required (non-null, non-empty) and MUST resolve (same existence check as V-IMPL-REF, per
   §2.3). If `enforcement_status == DOCUMENTED_ONLY`, `enforcement_ref` MUST be `null` — a non-null
   value on a `DOCUMENTED_ONLY` boundary is itself `INVALID` (REPAIR, Rev 2: a "documented-only"
   boundary carrying a ref would suggest unaudited enforcement exists; the contract refuses to let
   that ambiguity be expressible at all).
6. **V-ROLE-SEPARATION**: no single `components[]` entry's `authority_roles` contains both
   `execution` and `acceptance` (mirrors the runtime's own primary invariant, "Execution Authority
   MUST NOT be Acceptance Authority").
7. **V-VERIFIER-INDEPENDENCE** (REPAIR, Rev 2 — tied explicitly to the Authority Model, not a
   general "must be independent" phrase):
   - at least one `components[]` entry's `authority_roles` contains `verification`;
   - for every `components[]` entry whose `authority_roles` contains `verification`: that same
     entry's `authority_roles` MUST NOT also contain `execution` (an execution-role component
     cannot simultaneously be the independent verifier — this is what "independent" means
     operationally, per `docs/nogapcode-runtime.md` § Authority Model: `verification` "may produce
     authoritative verification evidence when independent from execution");
   - for every `components[]` entry whose `authority_roles` contains `verification`: if that same
     entry's `authority_roles` also contains `acceptance`, this is allowed ONLY when it also
     contains `human` (the Authority Model explicitly permits `human` to "act as verification or
     acceptance authority when recorded explicitly" — a non-human component combining
     `verification` and `acceptance` collapses independent verification into self-acceptance and is
     rejected).
8. **V-PLANE-COVERAGE** (REPAIR, Rev 2 — moved off `boundaries[]`, defined on `plane_status`):
   - `set(plane_status.keys()) == set(Plane)` (§1.1) — exactly the 6 Planes, no more, no fewer, as
     keys; a missing or extra key is `INVALID`.
   - every `plane_status[p] == EnforcementStatus.ENFORCED` entry MUST have at least one
     `components[]` entry with `plane == p` AND a valid, resolvable `implementation_ref` (per
     §2.3/V-IMPL-REF) — an `ENFORCED` Plane with no real backing component is `INVALID`, not
     silently accepted on the strength of the top-level declaration alone.
   - a `plane_status[p] == EnforcementStatus.DOCUMENTED_ONLY` entry requires no component and is
     never treated as raising trust — it is explicitly and only a statement that the Plane is not
     yet backed by anything checkable.
   - no fabricated/placeholder `components[]` entry may be used to turn a `DOCUMENTED_ONLY` Plane
     into an apparently-`ENFORCED` one; §2.3's existence-only guarantee bounds what "real component"
     means, and inventing one purely to satisfy this invariant is out of scope for any resolver
     (mirrors §5's exclusion of assumed components like `ToolProvider`).
9. **Plane is never inferred**: `plane` is always an explicit declaration on each `components[]`
   entry (§2.1) and on `plane_status` (§2.0). A resolver MUST NOT derive Plane membership from a
   file path, module name, or `implementation_ref` content. `boundaries[]` carries no `plane` field
   at all (Rev 2 REPAIR) — a boundary's Plane membership, if ever needed by a future consumer, is
   computed by dereferencing its endpoints' `components[].plane`, never stored redundantly.

## 4. Failure classes (verdict vocabulary, matching the existing `nogap_required_kinds.py` vocabulary)

| failure class | verdict status | triggered by |
|---|---|---|
| duplicate id | `INVALID` | V-DUP-COMPONENT or V-DUP-BOUNDARY |
| dangling endpoint | `INVALID` | V-ENDPOINT |
| unresolvable implementation reference | `INVALID` | V-IMPL-REF |
| enforced boundary without a resolvable enforcement reference | `INVALID` | V-ENFORCEMENT-REF |
| execution/acceptance role collision | `INVALID` | V-ROLE-SEPARATION |
| verifier not independent (collapses with execution, or with acceptance outside the `human` exception) | `INVALID` | V-VERIFIER-INDEPENDENCE |
| `plane_status` key set is not exactly the 6 Planes | `INVALID` | V-PLANE-COVERAGE |
| an `ENFORCED` Plane has no real, resolvable backing component | `INVALID` | V-PLANE-COVERAGE |
| `runtime_structure_version` outside the closed version set | `INVALID` | §2 |
| a `DOCUMENTED_ONLY` boundary carries a non-null `enforcement_ref` | `INVALID` | V-ENFORCEMENT-REF |
| any other malformed nested schema / unknown enum value | `INVALID` | (schema-level) |
| artifact absent / no `P9_RUNTIME_STRUCTURE` supplied / a required top-level field absent | `MISSING` | (standard, same as every other `WholeArtifact`-shaped kind) |
| resolved artifact is not `P9_RUNTIME_STRUCTURE` | `WRONG_TYPE` | (standard) |
| all schema + semantic invariants hold | `PASS` / `VALIDATED` | — |

No `STALE` outcome is defined for this kind at this contract level: nothing in the normative doc
or this survey identifies a supersession/lifecycle-status concept for `P9_RUNTIME_STRUCTURE` (same
reasoning `GOLDEN_GATES` used to deliberately omit STALE — not guessed, left absent because no
selector mechanism exists to make it meaningful).

## 5. Explicitly excluded from this contract (not invented)

- `ToolProvider`, `AgentRuntime`, `DecisionEngine` as assumed components — not declared unless a
  real `components[]` entry names them with a real `implementation_ref`.
- Any ordering/monotonicity semantics for `runtime_structure_version`.
- Any closed vocabulary for `permitted_flows` tokens.
- Any inference of `plane` from `implementation_ref`, file path, or module topology.
- A resolver deciding "which Plane matters more" — `V-PLANE-COVERAGE` treats all 6 Planes equally
  and fails closed on any of them.
- A `plane` field on `boundaries[]` (Rev 1 draft, rejected in REPAIR: would have created a second,
  potentially-conflicting source of truth alongside `components[].plane`).
- Fabricating a `components[]` entry to make an unimplemented Plane appear `ENFORCED`.

## 6. What happens after this contract is accepted

Only after this document is reviewed and accepted does implementation begin, in this order:
1. Add `P9_RUNTIME_STRUCTURE` to `scripts/nogap_artifact_types.py` (schema only, per §2).
2. Add a `RUNTIME_STRUCTURE` resolver to `scripts/nogap_required_kinds.py` that checks §3's
   invariants — the resolver enforces this contract, it does not define it (per §3.1 of the parent
   doc, already satisfied by writing this contract first).
3. Move `RUNTIME_STRUCTURE` from `DEFERRED_KINDS` to `ENFORCED_KINDS`.
4. Full targeted tests + mutation testing + regression, per this session's standing verification
   discipline.

None of step 1-4 is authorized by this document alone; each still requires its own explicit GO.
