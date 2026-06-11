"""Minimal irreversible redaction for OmniMemory content."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    detector: str
    secret: bytes


@dataclass(frozen=True)
class RedactionResult:
    data: bytes
    status: str
    detectors: tuple[str, ...]


@dataclass(frozen=True)
class _RegexDetector:
    name: str
    pattern: re.Pattern[bytes]
    secret_group: int = 0


_MIN_ENV_SECRET_LENGTH = 8

_REGEX_PACK = (
    _RegexDetector(
        "pem_private_key",
        re.compile(
            rb"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    _RegexDetector("aws_access_key", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
    _RegexDetector(
        "github_token",
        re.compile(rb"\b(?:ghp_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    ),
    _RegexDetector(
        "openai_token",
        re.compile(rb"\b(?:sk-[A-Za-z0-9_-]{20,}|sk-proj-[A-Za-z0-9_-]{20,})\b"),
    ),
    _RegexDetector(
        "jwt",
        re.compile(rb"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
    _RegexDetector(
        "auth_header",
        re.compile(rb"(?i)\bAuthorization:\s*(?:Bearer|Basic)\s+([A-Za-z0-9._~+/\-=]{12,})"),
        secret_group=1,
    ),
    _RegexDetector(
        "url_credentials",
        re.compile(rb"https?://([^/\s:@]+:[^/\s@]+)@"),
        secret_group=1,
    ),
    _RegexDetector(
        "secret_assignment",
        re.compile(rb"(?i)\b(?:api[_-]?key|secret|token|password)\b\s*[:=]\s*['\"]?([^'\"\s,}]{8,})['\"]?"),
        secret_group=1,
    ),
)


def redact(payload: bytes) -> RedactionResult:
    try:
        findings: list[Finding] = []
        redacted = _apply_env_reverse_lookup(payload, findings)
        redacted = _apply_regex_pack(redacted, findings)
    except Exception:
        return RedactionResult(
            data=_stub_for_redaction_failure(payload),
            status="withheld",
            detectors=("withheld",),
        )

    detectors = _unique_detectors(findings)
    status = "redacted" if detectors else "clean"
    return RedactionResult(data=redacted, status=status, detectors=detectors)


def redact_minimal(payload: bytes) -> RedactionResult:
    return redact(payload)


def _apply_regex_pack(data: bytes, findings: list[Finding]) -> bytes:
    regex_findings: list[Finding] = []
    for detector in _REGEX_PACK:
        for match in detector.pattern.finditer(data):
            secret = match.group(detector.secret_group)
            if secret:
                regex_findings.append(Finding(detector.name, secret))

    findings.extend(regex_findings)
    return _replace_findings(data, regex_findings)


def _apply_env_reverse_lookup(data: bytes, findings: list[Finding]) -> bytes:
    env_findings = [
        Finding("env", value.encode("utf-8", errors="ignore"))
        for value in os.environ.values()
        if _looks_like_env_secret(value) and value.encode("utf-8", errors="ignore") in data
    ]
    findings.extend(env_findings)
    return _replace_findings(data, env_findings)


def _looks_like_env_secret(value: str) -> bool:
    return len(value) >= _MIN_ENV_SECRET_LENGTH and not value.isspace()


def _replace_findings(data: bytes, findings: list[Finding]) -> bytes:
    redacted = data
    for finding in sorted(findings, key=lambda item: len(item.secret), reverse=True):
        redacted = redacted.replace(finding.secret, _placeholder(finding.detector, finding.secret))
    return redacted


def _placeholder(detector: str, secret: bytes) -> bytes:
    digest = hashlib.sha256(secret).hexdigest()[:8]
    return f"⟨REDACTED:{detector}:{digest}⟩".encode("utf-8")


def _stub_for_redaction_failure(payload: bytes) -> bytes:
    stub = {
        "error": "redaction_failed",
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "byte_len": len(payload),
    }
    return json.dumps(stub, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _unique_detectors(findings: list[Finding]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(finding.detector for finding in findings))
