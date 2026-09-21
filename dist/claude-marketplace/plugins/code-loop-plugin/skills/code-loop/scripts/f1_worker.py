#!/usr/bin/env python3
"""F1-I7 — the isolated verification worker.

This file is what runs untrusted project code, so it is what an adversary controls. It is a
separate module, run as a separate process, and it holds no authority of any kind:

    no authority key, no signer, no registry write, no policy write, no trusted-state write,
    no verdict of its own

It reads a plan on stdin, runs the checks in its own ephemeral copy, and writes **bounded raw
observations** to stdout. It does not decide anything: a `verdict` field in its output is ignored,
because the controller re-derives the verdict from the observations (§2). That is the difference
between a worker and a signing oracle.

The worker may write to, or entirely destroy, its copy. The master is elsewhere and it cannot
reach it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

#: Bounded by construction (§2): the controller parses this output, so it is hostile input to the
#: TCB and must be size-bounded and schema-constrained before it gets there.
MAX_OUTPUT = 64 * 1024
MAX_CHECKS = 64
TIMEOUT_SECONDS = 300


def observe(workdir: Path, checks: list[dict]) -> list[dict]:
    """Run each check and report what happened. No judgement, only observation."""
    observations = []
    for check in checks[:MAX_CHECKS]:
        try:
            completed = subprocess.run(
                check["command"], cwd=workdir, shell=False, capture_output=True,
                text=True, timeout=TIMEOUT_SECONDS)
            observations.append({
                "check_id": check["check_id"], "exit_code": completed.returncode,
                "stdout_bytes": len(completed.stdout), "stderr_bytes": len(completed.stderr),
                "output_head": completed.stdout[:512],
            })
        except subprocess.TimeoutExpired:
            observations.append({"check_id": check["check_id"], "exit_code": None,
                                 "stdout_bytes": 0, "stderr_bytes": 0, "output_head": "",
                                 "timed_out": True})
        except OSError as exc:
            observations.append({"check_id": check["check_id"], "exit_code": None,
                                 "stdout_bytes": 0, "stderr_bytes": 0,
                                 "output_head": f"{type(exc).__name__}", "failed_to_start": True})
    return observations


def main() -> int:
    plan = json.loads(sys.stdin.read())
    payload = json.dumps({"observations": observe(Path(plan["workdir"]), plan["checks"])})
    if len(payload) > MAX_OUTPUT:
        payload = json.dumps({"observations": [], "truncated": True})
    sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
