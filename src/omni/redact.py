"""Minimal irreversible redaction for OmniMemory content."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


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
_MAX_FULL_REDACTION_BYTES = 1024 * 1024
_TRUNCATED_EDGE_BYTES = 256 * 1024
_TRUNCATED_BOUNDARY_GUARD_BYTES = 4 * 1024
_SECRET_ENV_KEY_HINTS = ("AUTH", "CREDENTIAL", "KEY", "PASSWORD", "SECRET", "TOKEN")
_PRIVATE_KEY_BEGIN_RE = re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_PRIVATE_KEY_END_RE = re.compile(rb"-----END [A-Z ]*PRIVATE KEY-----")
_COMMON_LOW_ENTROPY_ENV_VALUES = {
    "admin",
    "administrator",
    "changeme",
    "changeit",
    "default",
    "example",
    "letmein",
    "none",
    "null",
    "password",
    "qwerty",
    "secret",
    "test",
    "testing",
    "undefined",
}
_ALWAYS_REDACT_DETECTORS = {
    "auth_header",
    "aws_access_key",
    "github_token",
    "jwt",
    "openai_token",
    "pem_private_key",
    "secret_assignment",
    "slack_webhook",
    "url_credentials",
}

SKIPLIST_PATTERNS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa*",
    "id_ed25519*",
    "*.kdbx",
    "*credentials*",
    ".netrc",
    ".npmrc",
    "*.tfstate",
    "secrets.*",
)

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
        re.compile(
            rb"(?i)\bAuthorization:\s*(?:Bearer|Basic)\s+([A-Za-z0-9._~+/\-=]{12,})"
        ),
        secret_group=1,
    ),
    _RegexDetector(
        "slack_webhook",
        re.compile(
            rb"https://hooks\.slack\.com/services/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+"
        ),
    ),
    _RegexDetector(
        "url_credentials",
        re.compile(rb"https?://([^/\s:@]+:[^/\s@]+)@"),
        secret_group=1,
    ),
    _RegexDetector(
        "secret_assignment",
        re.compile(
            rb"(?i)(?:api[_-]?key|secret|token|password)\b['\"]?\s*[:=]\s*['\"]?([^'\"\\\s,}]{8,})['\"]?"
        ),
        secret_group=1,
    ),
    _RegexDetector(
        "high_entropy",
        re.compile(
            rb"(?i)(?:--(?:token|api-key|secret|password)\s+|X-Api-Key:\s*)([A-Za-z0-9._~+/\-=]{24,})"
        ),
        secret_group=1,
    ),
)


def redact(payload: bytes, allow_values: Iterable[str | bytes] | None = None) -> RedactionResult:
    try:
        allow_bytes = _allow_bytes(allow_values)
        if len(payload) > _MAX_FULL_REDACTION_BYTES:
            return _redact_truncated(payload, allow_bytes)

        findings: list[Finding] = []
        redacted = _apply_env_reverse_lookup(payload, findings, allow_bytes)
        redacted = _apply_regex_pack(redacted, findings, allow_bytes)
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


def redact_path(
    path: Path | str, allow_values: Iterable[str | bytes] | None = None
) -> RedactionResult:
    file_path = Path(path)
    payload = file_path.read_bytes()
    if is_skiplisted_path(file_path):
        return RedactionResult(
            data=_stub_for_withheld_path(file_path, payload),
            status="withheld",
            detectors=("skiplist",),
        )
    return redact(payload, allow_values=allow_values)


def is_skiplisted_path(path: Path | str) -> bool:
    name = Path(path).name
    lowered = name.lower()
    return any(fnmatch.fnmatchcase(lowered, pattern.lower()) for pattern in SKIPLIST_PATTERNS)


def _apply_regex_pack(
    data: bytes, findings: list[Finding], allow_values: set[bytes] | None = None
) -> bytes:
    regex_findings: list[Finding] = []
    for detector in _REGEX_PACK:
        for match in detector.pattern.finditer(data):
            secret = match.group(detector.secret_group)
            if secret and _should_redact_secret(secret, detector.name, allow_values or set()):
                regex_findings.append(Finding(detector.name, secret))

    findings.extend(regex_findings)
    return _replace_findings(data, regex_findings)


def _apply_env_reverse_lookup(
    data: bytes, findings: list[Finding], allow_values: set[bytes] | None = None
) -> bytes:
    allowed = allow_values or set()
    env_findings = [
        Finding("env", value.encode("utf-8", errors="ignore"))
        for key, value in os.environ.items()
        if _looks_like_env_secret(key, value)
        and value.encode("utf-8", errors="ignore") not in allowed
        and value.encode("utf-8", errors="ignore") in data
    ]
    findings.extend(env_findings)
    return _replace_findings(data, env_findings)


def _looks_like_env_secret(key: str, value: str) -> bool:
    upper_key = key.upper()
    stripped = value.strip()
    return (
        len(stripped) >= _MIN_ENV_SECRET_LENGTH
        and stripped
        and any(hint in upper_key for hint in _SECRET_ENV_KEY_HINTS)
        and stripped.lower() not in _COMMON_LOW_ENTROPY_ENV_VALUES
        and not _looks_like_path_value(stripped)
    )


def _looks_like_path_value(value: str) -> bool:
    stripped = value.strip()
    if re.match(r"^[A-Za-z]:[\\/]", stripped):
        return True
    if stripped.startswith(("/", "\\\\")):
        return True
    if ";" in stripped and re.search(r"[A-Za-z]:[\\/]", stripped):
        return True
    return False


def _should_redact_secret(secret: bytes, detector: str, allow_values: set[bytes]) -> bool:
    if secret in allow_values:
        return False
    if _looks_like_redaction_placeholder(secret):
        return False
    if detector == "secret_assignment" and _looks_like_function_call(secret):
        return False
    if detector in _ALWAYS_REDACT_DETECTORS:
        return True
    if detector == "high_entropy" and not _looks_high_entropy(secret):
        return False
    if detector == "high_entropy":
        return True
    return True


def _looks_like_function_call(secret: bytes) -> bool:
    return re.fullmatch(rb"[A-Za-z_][A-Za-z0-9_.]*\(.*\)", secret) is not None


def _looks_high_entropy(secret: bytes) -> bool:
    if len(secret) < 24:
        return False
    if len(set(secret)) < 12:
        return False
    return _shannon_entropy(secret) >= 3.5


def _shannon_entropy(secret: bytes) -> float:
    counts = {byte: secret.count(byte) for byte in set(secret)}
    total = len(secret)
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


def _looks_like_redaction_placeholder(secret: bytes) -> bool:
    raw = rb"\xe2\x9f\xa8REDACTED:[A-Za-z0-9_:-]+\xe2\x9f\xa9"
    escaped = rb"\\u27e8REDACTED:[A-Za-z0-9_:-]+\\u27e9"
    return re.fullmatch(rb"(?:" + raw + rb"|" + escaped + rb")", secret) is not None


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


def _stub_for_withheld_path(path: Path, payload: bytes) -> bytes:
    stub = {
        "error": "skiplisted_path_withheld",
        "path_sha256": hashlib.sha256(str(path).encode("utf-8")).hexdigest(),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "byte_len": len(payload),
    }
    return json.dumps(stub, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _redact_truncated(payload: bytes, allow_values: set[bytes]) -> RedactionResult:
    findings: list[Finding] = []
    prefix = payload[:_TRUNCATED_EDGE_BYTES]
    suffix = payload[-_TRUNCATED_EDGE_BYTES:]
    private_key_ranges = _private_key_ranges(payload)
    redacted_prefix = _withhold_partial_private_key_sample(
        _line_safe_prefix(_redact_chunk(prefix, findings, allow_values)),
        findings,
        private_key_ranges,
        0,
        len(prefix),
    )
    redacted_suffix = _withhold_partial_private_key_sample(
        _line_safe_suffix(_redact_chunk(suffix, findings, allow_values)),
        findings,
        private_key_ranges,
        len(payload) - len(suffix),
        len(payload),
    )
    body = {
        "error": "payload_truncated",
        "byte_len": len(payload),
        "prefix": redacted_prefix.decode("utf-8", errors="replace"),
        "suffix": redacted_suffix.decode("utf-8", errors="replace"),
    }
    detectors = _unique_detectors(findings)
    return RedactionResult(
        data=json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
        status="truncated",
        detectors=detectors,
    )


def _line_safe_prefix(prefix: bytes) -> bytes:
    newline = prefix.rfind(b"\n")
    if newline == -1:
        return prefix[:-_TRUNCATED_BOUNDARY_GUARD_BYTES]
    return prefix[: newline + 1]


def _line_safe_suffix(suffix: bytes) -> bytes:
    newline = suffix.find(b"\n")
    if newline == -1:
        return suffix[_TRUNCATED_BOUNDARY_GUARD_BYTES:]
    return suffix[newline + 1 :]


def _withhold_partial_private_key_sample(
    sample: bytes,
    findings: list[Finding],
    private_key_ranges: list[tuple[int, int]],
    sample_start: int,
    sample_end: int,
) -> bytes:
    if not sample:
        return sample
    has_begin = _PRIVATE_KEY_BEGIN_RE.search(sample) is not None
    has_end = _PRIVATE_KEY_END_RE.search(sample) is not None
    boundary_overlap = any(
        key_start < sample_end
        and sample_start < key_end
        and (key_start < sample_start or key_end > sample_end)
        for key_start, key_end in private_key_ranges
    )
    if has_begin == has_end and not boundary_overlap:
        return sample
    findings.append(Finding("pem_private_key", b"partial_private_key"))
    return _stub_for_truncated_private_key_sample(sample)


def _private_key_ranges(payload: bytes) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    first_begin = _PRIVATE_KEY_BEGIN_RE.search(payload)
    first_end = _PRIVATE_KEY_END_RE.search(payload)
    if first_end is not None and (
        first_begin is None or first_end.start() < first_begin.start()
    ):
        ranges.append((0, first_end.end()))

    index = 0
    while True:
        begin = _PRIVATE_KEY_BEGIN_RE.search(payload, index)
        if begin is None:
            break
        end = _PRIVATE_KEY_END_RE.search(payload, begin.end())
        if end is None:
            ranges.append((begin.start(), len(payload)))
            break
        ranges.append((begin.start(), end.end()))
        index = end.end()
    return ranges


def _stub_for_truncated_private_key_sample(sample: bytes) -> bytes:
    stub = {
        "error": "truncated_private_key_withheld",
        "sample_sha256": hashlib.sha256(sample).hexdigest(),
        "byte_len": len(sample),
    }
    return json.dumps(stub, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _allow_bytes(values: Iterable[str | bytes] | None) -> set[bytes]:
    if values is None:
        return set()
    allowed: set[bytes] = set()
    for value in values:
        if isinstance(value, bytes):
            allowed.add(value)
        else:
            allowed.add(value.encode("utf-8"))
    return allowed


def _redact_chunk(chunk: bytes, findings: list[Finding], allow_values: set[bytes]) -> bytes:
    redacted = _apply_env_reverse_lookup(chunk, findings, allow_values)
    return _apply_regex_pack(redacted, findings, allow_values)


def _unique_detectors(findings: list[Finding]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(finding.detector for finding in findings))
