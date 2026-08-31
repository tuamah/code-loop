#!/usr/bin/env python3
"""NoGapCode provider connection manager."""

from __future__ import annotations

import ctypes
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import secrets
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Protocol


OPENROUTER_TARGET = "nogap/openrouter/default"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_AUTH_URL = "https://openrouter.ai/auth"
OPENROUTER_KEYS_URL = "https://openrouter.ai/api/v1/auth/keys"
PROBE_TIMEOUT_SECONDS = 12
OPENROUTER_PENDING_AUTH: dict[str, str] = {}


class SecretStore(Protocol):
    def get(self, target: str) -> str | None:
        ...

    def set(self, target: str, secret: str) -> None:
        ...

    def delete(self, target: str) -> None:
        ...

    def available(self) -> bool:
        ...


class UnsupportedSecretStore:
    def get(self, target: str) -> str | None:
        return None

    def set(self, target: str, secret: str) -> None:
        raise RuntimeError("secure credential storage is unavailable on this platform")

    def delete(self, target: str) -> None:
        return

    def available(self) -> bool:
        return False


if sys.platform == "win32":
    LPBYTE = ctypes.POINTER(wintypes.BYTE)

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", LPBYTE),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", wintypes.LPVOID),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    PCREDENTIALW = ctypes.POINTER(CREDENTIALW)
    PPCREDENTIALW = ctypes.POINTER(PCREDENTIALW)

    _advapi32 = ctypes.WinDLL("Advapi32.dll")
    _advapi32.CredWriteW.argtypes = [PCREDENTIALW, wintypes.DWORD]
    _advapi32.CredWriteW.restype = wintypes.BOOL
    _advapi32.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, PPCREDENTIALW]
    _advapi32.CredReadW.restype = wintypes.BOOL
    _advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    _advapi32.CredDeleteW.restype = wintypes.BOOL
    _advapi32.CredFree.argtypes = [wintypes.LPVOID]
    _advapi32.CredFree.restype = None


class WindowsCredentialStore:
    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    def available(self) -> bool:
        return sys.platform == "win32"

    def get(self, target: str) -> str | None:
        if not self.available():
            return None
        credential = PCREDENTIALW()
        ok = _advapi32.CredReadW(target, self.CRED_TYPE_GENERIC, 0, ctypes.byref(credential))
        if not ok:
            return None
        try:
            item = credential.contents
            size = int(item.CredentialBlobSize)
            if size <= 0:
                return None
            blob = ctypes.string_at(item.CredentialBlob, size)
            return blob.decode("utf-16-le")
        finally:
            _advapi32.CredFree(credential)

    def set(self, target: str, secret: str) -> None:
        if not self.available():
            raise RuntimeError("Windows Credential Manager is unavailable")
        if not secret.strip():
            raise ValueError("secret must be non-empty")
        blob = secret.encode("utf-16-le")
        buffer = ctypes.create_string_buffer(blob)
        credential = CREDENTIALW()
        credential.Type = self.CRED_TYPE_GENERIC
        credential.TargetName = target
        credential.CredentialBlobSize = len(blob)
        credential.CredentialBlob = ctypes.cast(buffer, LPBYTE)
        credential.Persist = self.CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = "openrouter"
        ok = _advapi32.CredWriteW(ctypes.byref(credential), 0)
        if not ok:
            raise ctypes.WinError()

    def delete(self, target: str) -> None:
        if not self.available():
            return
        _advapi32.CredDeleteW(target, self.CRED_TYPE_GENERIC, 0)


def default_secret_store() -> SecretStore:
    if sys.platform == "win32":
        return WindowsCredentialStore()
    return UnsupportedSecretStore()


@dataclass
class Probe:
    name: str
    status: str
    detail: str = ""
    latency_ms: int | None = None

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"name": self.name, "status": self.status}
        if self.detail:
            data["detail"] = self.detail
        if self.latency_ms is not None:
            data["latency_ms"] = self.latency_ms
        return data


def masked_secret(secret: str | None) -> str:
    if not secret:
        return ""
    cleaned = secret.strip()
    if len(cleaned) <= 10:
        return "******"
    return f"{cleaned[:6]}******{cleaned[-4:]}"


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def provider_status(probes: list[Probe]) -> str:
    statuses = {probe.status for probe in probes}
    if "FAIL" in statuses:
        return "disconnected"
    if "WARN" in statuses:
        return "limited"
    return "connected"


def required_probe_status(probes: list[Probe], required: set[str]) -> str:
    by_name = {probe.name: probe.status for probe in probes}
    missing = required - set(by_name)
    if missing:
        return "limited"
    if any(by_name[name] == "FAIL" for name in required):
        return "disconnected"
    return "connected"


def run_command(argv: list[str], timeout: int = PROBE_TIMEOUT_SECONDS) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            argv,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def executable_probe(name: str, command: str) -> tuple[str | None, list[Probe]]:
    path = shutil.which(command)
    if path is None:
        return None, [Probe("runtime_executable", "FAIL", f"{command} not found on PATH")]
    probes = [Probe("runtime_executable", "PASS", path)]
    result = run_command([path, "--version"])
    if result is None:
        probes.append(Probe("version_probe", "WARN", "version command failed"))
        return path, probes
    version = (result.stdout or result.stderr).strip().splitlines()
    detail = version[0][:120] if version else f"{name} executable responded with {result.returncode}"
    probes.append(Probe("version_probe", "PASS" if result.returncode == 0 else "WARN", detail))
    return path, probes


def codex_connection() -> dict[str, Any]:
    path, probes = executable_probe("OpenAI Codex", "codex")
    if path is not None:
        login = run_command([path, "login", "status"])
        login_text = ((login.stdout if login else "") or (login.stderr if login else "")).strip()
        probes.append(Probe(
            "authentication",
            "PASS" if login and login.returncode == 0 and "Logged in" in login_text else "FAIL",
            login_text[:120] if login_text else "login status unavailable",
        ))
        doctor = run_command([path, "doctor", "--json"], timeout=20)
        if doctor and doctor.stdout.strip():
            try:
                report = json.loads(doctor.stdout)
                checks = report.get("checks", {}) if isinstance(report, dict) else {}
                for check_id, probe_name in [
                    ("runtime.provenance", "runtime_health"),
                    ("network.provider_reachability", "provider_reachability"),
                    ("network.websocket_reachability", "streaming"),
                ]:
                    check = checks.get(check_id, {}) if isinstance(checks, dict) else {}
                    status = "PASS" if check.get("status") == "ok" else "FAIL"
                    probes.append(Probe(probe_name, status, str(check.get("summary", ""))[:120]))
            except json.JSONDecodeError:
                probes.append(Probe("doctor_json", "WARN", "doctor output was not JSON"))
        else:
            probes.append(Probe("doctor_json", "WARN", "doctor --json unavailable"))
        probes.append(Probe("tool_calling", "WARN", "requires an execution probe in M6/M8"))
        probes.append(Probe("quota_available", "WARN", "not exposed by Codex CLI status"))
    status = required_probe_status(probes, {
        "runtime_executable",
        "version_probe",
        "authentication",
        "runtime_health",
        "provider_reachability",
        "streaming",
    })
    return {
        "id": "codex",
        "label": "OpenAI Codex",
        "kind": "AgentRuntime",
        "status": status,
        "credential_present": any(probe.name == "authentication" and probe.status == "PASS" for probe in probes),
        "auth_mode": "official-cli",
        "executable": path or "",
        "last_health_check": "",
        "probes": [probe.as_dict() for probe in probes],
        "trust_status": "READY" if status == "connected" else "NOT_READY",
    }


def cli_connection(provider_id: str, label: str, command: str) -> dict[str, Any]:
    path, probes = executable_probe(label, command)
    if path is not None:
        probes.append(Probe("authentication", "WARN", "official CLI auth status probe is provider-specific"))
    status = provider_status(probes)
    return {
        "id": provider_id,
        "label": label,
        "kind": "AgentRuntime",
        "status": status,
        "credential_present": path is not None,
        "auth_mode": "official-cli",
        "executable": path or "",
        "last_health_check": "",
        "probes": [probe.as_dict() for probe in probes],
        "trust_status": "READY" if status == "connected" else "NOT_READY",
    }


def openrouter_secret(store: SecretStore) -> str | None:
    return store.get(OPENROUTER_TARGET) or os.environ.get("OPENROUTER_API_KEY")


def openrouter_connection(store: SecretStore | None = None, test: bool = False) -> dict[str, Any]:
    active_store = store or default_secret_store()
    secret = openrouter_secret(active_store)
    probes = [Probe("secure_store", "PASS" if active_store.available() else "WARN", "OS credential store")]
    probes.append(Probe("authentication", "PASS" if secret else "FAIL", "credential present" if secret else "missing credential"))
    model_count = 0
    if test and secret:
        request = urllib.request.Request(
            OPENROUTER_MODELS_URL,
            headers={"Authorization": f"Bearer {secret}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=PROBE_TIMEOUT_SECONDS) as response:
                raw = response.read(1024 * 1024)
            payload = json.loads(raw.decode("utf-8"))
            models = payload.get("data", []) if isinstance(payload, dict) else []
            model_count = len(models) if isinstance(models, list) else 0
            probes.append(Probe("model_discovery", "PASS", f"{model_count} models"))
            probes.append(Probe("streaming", "WARN", "not probed by models endpoint"))
            probes.append(Probe("tool_calling", "WARN", "requires model-specific probe"))
            probes.append(Probe("quota_available", "WARN", "not exposed by models endpoint"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            probes.append(Probe("model_discovery", "FAIL", type(exc).__name__))
    elif secret:
        probes.append(Probe("model_discovery", "WARN", "not tested yet"))
    status = required_probe_status(probes, {"authentication", "model_discovery"}) if test else provider_status(probes)
    return {
        "id": "openrouter",
        "label": "OpenRouter",
        "kind": "ModelProvider",
        "status": status,
        "credential_present": bool(secret),
        "credential_ref": OPENROUTER_TARGET if secret else "",
        "credential_hint": masked_secret(secret),
        "auth_mode": "api-key",
        "model_count": model_count,
        "last_health_check": "",
        "probes": [probe.as_dict() for probe in probes],
        "trust_status": "READY" if status == "connected" else "NOT_READY",
    }


def build_connections_payload(store: SecretStore | None = None, test_provider: str | None = None) -> dict[str, Any]:
    active_store = store or default_secret_store()
    providers = [
        codex_connection(),
        cli_connection("claude", "Claude Code", "claude"),
        openrouter_connection(active_store, test=test_provider == "openrouter"),
    ]
    return {
        "providers": providers,
        "models": [
            {"id": "gpt-5.6-terra", "role": "planner", "source": "Direct Codex", "status": providers[0]["status"]},
            {"id": "gpt-5.4", "role": "implementer", "source": "Direct Codex", "status": providers[0]["status"]},
            {"id": "gpt-5.6-sol", "role": "arbiter", "source": "Direct Codex", "status": providers[0]["status"]},
            {"id": "claude-code-default", "role": "agent-runtime", "source": "Direct Claude Code", "status": providers[1]["status"]},
            {"id": "deepseek/qwen/glm/minimax", "role": "model-provider", "source": "Via OpenRouter", "status": providers[2]["status"]},
        ],
        "policy_note": "Build-time roles: Terra plans, 5.4 executes, Sol judges. Provider, model, and AgentRuntime remain separate.",
    }


def store_openrouter_key(api_key: str, store: SecretStore | None = None, verify: bool = True) -> dict[str, Any]:
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("api_key is required")
    cleaned = api_key.strip()
    if len(cleaned) < 20:
        raise ValueError("api_key is too short")
    active_store = store or default_secret_store()
    if not active_store.available():
        raise RuntimeError("secure credential storage is unavailable")
    active_store.set(OPENROUTER_TARGET, cleaned)
    return openrouter_connection(active_store, test=verify)


def start_openrouter_login(
    callback_url: str,
    store: SecretStore | None = None,
    open_browser: bool = True,
) -> dict[str, Any]:
    active_store = store or default_secret_store()
    if not active_store.available():
        raise RuntimeError("secure credential storage is unavailable")
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    OPENROUTER_PENDING_AUTH[state] = verifier
    separator = "&" if "?" in callback_url else "?"
    callback_with_state = f"{callback_url}{separator}state={urllib.parse.quote(state)}"
    query = urllib.parse.urlencode({
        "callback_url": callback_with_state,
        "code_challenge": pkce_challenge(verifier),
        "code_challenge_method": "S256",
        "key_label": "NoGapCode Local",
    })
    auth_url = f"{OPENROUTER_AUTH_URL}?{query}"
    opened = webbrowser.open(auth_url, new=2) if open_browser else False
    return {
        "id": "openrouter",
        "label": "OpenRouter",
        "kind": "ModelProvider",
        "status": "auth_pending",
        "credential_present": bool(openrouter_secret(active_store)),
        "credential_ref": OPENROUTER_TARGET if openrouter_secret(active_store) else "",
        "credential_hint": masked_secret(openrouter_secret(active_store)),
        "auth_mode": "oauth-pkce",
        "auth_url": auth_url,
        "browser_opened": opened,
        "probes": [
            Probe("secure_store", "PASS", "OS credential store").as_dict(),
            Probe("browser_login", "WARN", "waiting for OpenRouter authorization callback").as_dict(),
        ],
        "trust_status": "NOT_READY",
    }


def complete_openrouter_login(
    code: str,
    state: str,
    store: SecretStore | None = None,
) -> dict[str, Any]:
    if not code or not state:
        raise ValueError("code and state are required")
    verifier = OPENROUTER_PENDING_AUTH.pop(state, None)
    if verifier is None:
        raise ValueError("unknown or expired OpenRouter login state")
    request = urllib.request.Request(
        OPENROUTER_KEYS_URL,
        data=json.dumps({
            "code": code,
            "code_verifier": verifier,
            "code_challenge_method": "S256",
        }).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=PROBE_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"OpenRouter OAuth exchange failed: {type(exc).__name__}") from exc
    key = payload.get("key") if isinstance(payload, dict) else None
    if not isinstance(key, str) or not key:
        raise RuntimeError("OpenRouter OAuth exchange did not return a key")
    return store_openrouter_key(key, store=store, verify=True)


def delete_openrouter_key(store: SecretStore | None = None) -> dict[str, Any]:
    active_store = store or default_secret_store()
    active_store.delete(OPENROUTER_TARGET)
    return openrouter_connection(active_store, test=False)


def connect_cli(provider: str) -> dict[str, Any]:
    if provider == "codex":
        payload = cli_connection("codex", "OpenAI Codex", "codex")
        path = shutil.which("codex")
        if path and not payload["credential_present"]:
            subprocess.Popen([path, "login"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            payload["status"] = "auth_pending"
        payload["action_required"] = "Use the official Codex CLI/app sign-in. NoGapCode will not request or copy session tokens."
        return payload
    if provider == "claude":
        payload = cli_connection("claude", "Claude Code", "claude")
        path = shutil.which("claude")
        if path:
            subprocess.Popen([path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            payload["status"] = "auth_pending"
        payload["action_required"] = "Use the official Claude Code login. NoGapCode will not request or copy session tokens."
        return payload
    raise ValueError(f"unknown CLI provider: {provider}")
