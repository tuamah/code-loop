#!/usr/bin/env python3
"""Backend-backed NoGapCode dashboard server."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from nogap_connections import (
    build_connections_payload,
    complete_openrouter_login,
    connect_cli,
    delete_openrouter_key,
    start_openrouter_login,
    store_openrouter_key,
)


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = ROOT / "dashboard"
RUNTIME_DIRS = ("gates", "claims", "evidence", "events", "decisions", "lessons", "literature")
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
REGISTRY_PATH = ROOT / ".nogap" / "projects.json"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def runtime_root(project: Path) -> Path:
    root = project.resolve()
    if root.name == "runtime":
        return root
    if (root / "runtime").exists():
        return root / "runtime"
    return root / ".code-loop" / "runtime"


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def project_id(path: Path) -> str:
    import hashlib

    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:12]


def project_entry(path: Path, name: str | None = None) -> dict[str, str]:
    resolved = path.resolve()
    return {"id": project_id(resolved), "name": name or resolved.name, "path": str(resolved)}


def load_project_registry(default_project: Path) -> list[dict[str, str]]:
    data = read_json(REGISTRY_PATH) or {}
    projects = data.get("projects", [])
    valid: list[dict[str, str]] = []
    if isinstance(projects, list):
        for item in projects:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            name = item.get("name")
            if isinstance(path, str) and path:
                valid.append(project_entry(Path(path), str(name) if name else None))
    default = project_entry(default_project)
    if not any(item["id"] == default["id"] for item in valid):
        valid.insert(0, default)
    return valid


def save_project_registry(projects: list[dict[str, str]]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps({"projects": projects}, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def projects_payload(selected: Path) -> dict[str, Any]:
    projects = load_project_registry(selected)
    selected_id = project_id(selected)
    return {"selected_id": selected_id, "projects": projects}


def add_project(path_value: str, selected: Path, name: str | None = None) -> dict[str, Any]:
    if not isinstance(path_value, str) or not path_value.strip():
        raise ValueError("project path is required")
    if len(path_value) > 500:
        raise ValueError("project path is too long")
    path = Path(os.path.expanduser(path_value.strip())).resolve()
    if not path.is_dir():
        raise ValueError("project path must be an existing directory")
    projects = load_project_registry(selected)
    entry = project_entry(path, name)
    projects = [item for item in projects if item["id"] != entry["id"]]
    projects.append(entry)
    save_project_registry(projects)
    DashboardHandler.project = path
    return projects_payload(path)


def select_project(project_id_value: str, selected: Path) -> dict[str, Any]:
    projects = load_project_registry(selected)
    for item in projects:
        if item["id"] == project_id_value:
            path = Path(item["path"])
            if not path.is_dir():
                raise ValueError("selected project path no longer exists")
            DashboardHandler.project = path.resolve()
            return projects_payload(DashboardHandler.project)
    raise ValueError("unknown project id")


def open_project_folder(project: Path) -> dict[str, Any]:
    path = project.resolve()
    if not path.is_dir():
        raise ValueError("project path does not exist")
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return {"status": "opened", "path": str(path)}
    return {"status": "unsupported", "path": str(path)}


def read_json_dir(directory: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not directory.is_dir():
        return items
    for path in sorted(directory.glob("*.json")):
        item = read_json(path)
        if item is not None:
            items.append(item)
    return items


def read_events(directory: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not directory.is_dir():
        return events
    for path in sorted(directory.glob("*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def status_from_evidence(items: list[dict[str, Any]]) -> str:
    statuses = {str(item.get("status", "")).lower() for item in items}
    if "failed" in statuses:
        return "FAILED"
    if statuses & {"blocked", "inconclusive"}:
        return "PENDING"
    if "passed" in statuses:
        return "PASSED"
    return "PENDING"


def gate_rows(gates: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for gate in gates:
        gate_id = str(gate.get("id", "gate"))
        gate_hash = gate.get("hash")
        gate_evidence = [
            item for item in evidence
            if item.get("provenance", {}).get("gate_hash") == gate_hash
        ]
        rows.append({
            "name": gate_id.replace("-", " ").title(),
            "detail": f"{gate.get('status', 'unknown')} gate v{gate.get('version', '?')}",
            "status": status_from_evidence(gate_evidence) if gate_evidence else str(gate.get("status", "pending")).upper(),
            "passed": sum(1 for item in gate_evidence if item.get("status") == "passed"),
            "failed": sum(1 for item in gate_evidence if item.get("status") == "failed"),
        })
    return rows


def recent_decisions(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(decisions, key=lambda item: str(item.get("created_at", "")), reverse=True)
    return [{
        "title": str(item.get("reason", item.get("id", "Decision")))[:80],
        "project": str(item.get("run_id", "")),
        "by": str(item.get("actor_id") or item.get("decided_by", "")),
        "status": str(item.get("decision", "abstain")).upper(),
        "time": str(item.get("created_at", ""))[:10] or "unknown",
    } for item in ordered[:5]]


def recent_activity(events: list[dict[str, Any]], evidence: list[dict[str, Any]], decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    activity: list[dict[str, Any]] = []
    for event in events:
        activity.append({
            "type": str(event.get("type", "EVENT")),
            "title": str(event.get("type", "Runtime event")).replace("_", " ").title(),
            "detail": str(event.get("payload", {}).get("decision", event.get("actor", ""))),
            "actor": str(event.get("actor", "")),
            "created_at": str(event.get("created_at", "")),
        })
    for item in evidence:
        provenance = item.get("provenance", {})
        activity.append({
            "type": "VERIFICATION_EVIDENCE_RECORDED",
            "title": f"Evidence {str(item.get('status', '')).title()}",
            "detail": str(item.get("kind", "evidence")),
            "actor": str(provenance.get("actor_id") or provenance.get("created_by", "")),
            "created_at": str(provenance.get("created_at", "")),
        })
    for item in decisions:
        activity.append({
            "type": "DECISION_" + str(item.get("decision", "abstain")).upper(),
            "title": "Decision Made",
            "detail": str(item.get("decision", "abstain")).upper(),
            "actor": str(item.get("actor_id") or item.get("decided_by", "")),
            "created_at": str(item.get("created_at", "")),
        })
    activity.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return activity[:5]


def record_items(items: list[dict[str, Any]], title_key: str, status_key: str = "status") -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in items:
        provenance = item.get("provenance", {})
        rows.append({
            "title": str(item.get(title_key) or item.get("id") or "record")[:120],
            "detail": str(item.get("id", "")),
            "status": str(item.get(status_key, "record")).upper(),
            "actor": str(provenance.get("actor_id") or provenance.get("created_by") or item.get("actor_id") or ""),
        })
    return rows


def build_payload(project: Path) -> dict[str, Any]:
    root = runtime_root(project)
    run = read_json(root / "run.json") or {}
    gates = read_json_dir(root / "gates")
    claims = read_json_dir(root / "claims")
    evidence = read_json_dir(root / "evidence")
    decisions = read_json_dir(root / "decisions")
    lessons = read_json_dir(root / "lessons")
    literature = read_json_dir(root / "literature")
    events = read_events(root / "events")
    since = utc_now() - timedelta(days=30)
    recent_decision_count = sum(
        1 for item in decisions
        if (parse_time(item.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= since
    )
    failed_authoritative = [
        item for item in evidence
        if item.get("provenance", {}).get("authority") in {"verification", "human"}
        and item.get("status") in {"failed", "blocked", "inconclusive"}
    ]
    accept_count = sum(1 for item in decisions if item.get("decision") == "accept")
    trust_score = max(0, min(100, 100 - (len(failed_authoritative) * 12) - max(0, len(claims) - accept_count) * 2))
    runtime_exists = root.is_dir() and all((root / name).is_dir() for name in RUNTIME_DIRS)
    return {
        "project": {
            "path": str(project.resolve()),
            "runtime_path": str(root),
            "runtime_exists": runtime_exists,
            "run_id": run.get("id", "no-runtime"),
            "objective": run.get("objective", "No active NoGapCode runtime found."),
        },
        "summary": {
            "projects": 1 if runtime_exists else 0,
            "open_items": sum(1 for claim in claims if claim.get("status") in {"unverified", "supported"}),
            "pending_verifications": sum(1 for item in evidence if item.get("status") in {"blocked", "inconclusive"}),
            "decisions_30d": recent_decision_count,
        },
        "metrics": {
            "executions": sum(1 for event in events if event.get("type") in {"AGENT_DISPATCHED", "PATCH_CREATED", "TOOL_CALLED"}),
            "verifications": len(evidence),
            "decisions": len(decisions),
            "knowledge": len(lessons) + len(literature),
        },
        "gates": gate_rows(gates, evidence),
        "decisions": recent_decisions(decisions),
        "activity": recent_activity(events, evidence, decisions),
        "records": {
            "claims": record_items(claims, "text"),
            "evidence": record_items(evidence, "kind"),
            "lessons": record_items(lessons, "text"),
            "literature": record_items(literature, "claim", "decision"),
            "events": [{
                "title": str(item.get("type", "event")).replace("_", " ").title(),
                "detail": str(item.get("id", "")),
                "status": "EVENT",
                "actor": str(item.get("actor", "")),
            } for item in events],
        },
        "system": {
            "runtime": "online" if runtime_exists else "no-runtime",
            "model_router": "gpt-5.6-terra plans",
            "agent_runtime": "gpt-5.4 executes",
            "arbiter": "5.6-sol judges",
            "trust_score": trust_score,
        },
    }


def validate_runtime(project: Path) -> dict[str, Any]:
    command = [sys.executable, str(ROOT / "scripts" / "nogap.py"), "validate", str(project.resolve())]
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "failed",
            "command": "python scripts/nogap.py validate <project>",
            "detail": type(exc).__name__,
        }
    output = (result.stdout or result.stderr).strip()
    return {
        "status": "passed" if result.returncode == 0 else "failed",
        "command": "python scripts/nogap.py validate <project>",
        "detail": output[:2000],
    }


class DashboardHandler(BaseHTTPRequestHandler):
    project: Path = ROOT

    def log_message(self, format: str, *args: Any) -> None:
        return

    def send_bytes(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
            return

    def send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_bytes(status, body, "application/json; charset=utf-8")

    def read_json_body(self) -> dict[str, Any]:
        length_header = self.headers.get("Content-Length", "0")
        try:
            length = int(length_header)
        except ValueError as exc:
            raise ValueError("invalid content length") from exc
        if length < 0 or length > 8192:
            raise ValueError("request body is too large")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid JSON body") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def same_origin_post(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = self.headers.get("Host", "")
        parsed = urlparse(origin)
        return parsed.scheme == "http" and parsed.netloc == host

    def loopback_callback_url(self) -> str:
        host = self.headers.get("Host", "127.0.0.1")
        hostname = host.rsplit(":", 1)[0].strip("[]")
        if hostname not in LOOPBACK_HOSTS:
            raise ValueError("connection login must be started from a loopback dashboard host")
        return f"http://{host}/api/connections/openrouter/callback"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/dashboard":
            self.send_json(HTTPStatus.OK, build_payload(self.project))
            return
        if parsed.path == "/api/connections":
            self.send_json(HTTPStatus.OK, build_connections_payload())
            return
        if parsed.path == "/api/projects":
            self.send_json(HTTPStatus.OK, projects_payload(self.project))
            return
        if parsed.path == "/api/connections/openrouter/callback":
            params = parse_qs(parsed.query)
            try:
                payload = complete_openrouter_login(
                    params.get("code", [""])[0],
                    params.get("state", [""])[0],
                )
                body = (
                    "<!doctype html><meta charset='utf-8'>"
                    "<title>NoGapCode OpenRouter Connected</title>"
                    "<body style='font-family:system-ui;background:#070b12;color:#f6f8fb'>"
                    "<h1>OpenRouter connected</h1>"
                    f"<p>Status: {payload['status']}. You can return to NoGapCode.</p>"
                    "</body>"
                ).encode("utf-8")
                self.send_bytes(HTTPStatus.OK, body, "text/html; charset=utf-8")
            except (ValueError, RuntimeError) as exc:
                body = (
                    "<!doctype html><meta charset='utf-8'>"
                    "<title>NoGapCode OpenRouter Login Failed</title>"
                    "<body style='font-family:system-ui;background:#070b12;color:#f6f8fb'>"
                    "<h1>OpenRouter login failed</h1>"
                    f"<p>{str(exc)}</p>"
                    "</body>"
                ).encode("utf-8")
                self.send_bytes(HTTPStatus.BAD_REQUEST, body, "text/html; charset=utf-8")
            return
        rel = "index.html" if parsed.path in {"", "/"} else parsed.path.lstrip("/")
        target = (DASHBOARD_DIR / rel).resolve()
        if DASHBOARD_DIR.resolve() not in target.parents and target != DASHBOARD_DIR.resolve():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_bytes(HTTPStatus.OK, target.read_bytes(), content_type)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not self.same_origin_post():
            self.send_json(HTTPStatus.FORBIDDEN, {"error": "cross-origin connection request rejected"})
            return
        try:
            if parsed.path == "/api/connections/openrouter":
                payload = self.read_json_body()
                self.send_json(HTTPStatus.OK, store_openrouter_key(str(payload.get("api_key", ""))))
                return
            if parsed.path == "/api/connections/openrouter/connect":
                self.send_json(HTTPStatus.OK, start_openrouter_login(self.loopback_callback_url()))
                return
            if parsed.path == "/api/connections/openrouter/test":
                self.send_json(HTTPStatus.OK, build_connections_payload(test_provider="openrouter"))
                return
            if parsed.path == "/api/connections/openrouter/disconnect":
                self.send_json(HTTPStatus.OK, delete_openrouter_key())
                return
            if parsed.path == "/api/connections/codex/connect":
                self.send_json(HTTPStatus.OK, connect_cli("codex"))
                return
            if parsed.path == "/api/connections/codex/test":
                self.send_json(HTTPStatus.OK, build_connections_payload())
                return
            if parsed.path == "/api/connections/claude/connect":
                self.send_json(HTTPStatus.OK, connect_cli("claude"))
                return
            if parsed.path == "/api/connections/claude/test":
                self.send_json(HTTPStatus.OK, build_connections_payload())
                return
            if parsed.path == "/api/runtime/validate":
                self.send_json(HTTPStatus.OK, validate_runtime(self.project))
                return
            if parsed.path == "/api/projects":
                payload = self.read_json_body()
                self.send_json(HTTPStatus.OK, add_project(
                    str(payload.get("path", "")),
                    self.project,
                    str(payload.get("name", "")) if payload.get("name") else None,
                ))
                return
            if parsed.path == "/api/projects/select":
                payload = self.read_json_body()
                self.send_json(HTTPStatus.OK, select_project(str(payload.get("id", "")), self.project))
                return
            if parsed.path == "/api/projects/open":
                self.send_json(HTTPStatus.OK, open_project_folder(self.project))
                return
        except ValueError as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        except RuntimeError as exc:
            self.send_json(HTTPStatus.NOT_IMPLEMENTED, {"error": str(exc)})
            return
        self.send_error(HTTPStatus.NOT_FOUND)


def serve(project: Path, host: str, port: int) -> None:
    DashboardHandler.project = project.resolve()
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"NoGapCode dashboard serving http://{host}:{port}/ for {DashboardHandler.project}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", nargs="?", default=".")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve(Path(args.project), args.host, args.port)


if __name__ == "__main__":
    main()
