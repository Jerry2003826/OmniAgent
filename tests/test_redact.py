from __future__ import annotations

import hashlib
import json
import re

import omni.redact as redact_mod


def test_env_reverse_lookup_redacts_environment_value(monkeypatch) -> None:
    monkeypatch.setenv("OMNI_TEST_SECRET", "super-secret-value-123")

    result = redact_mod.redact(b'{"token":"super-secret-value-123"}')

    assert result.status == "redacted"
    assert "env" in result.detectors
    assert b"super-secret-value-123" not in result.data
    assert b"\xe2\x9f\xa8REDACTED:env:" in result.data
    assert not hasattr(result, "original")


def test_env_reverse_lookup_ignores_path_like_environment_values(monkeypatch) -> None:
    monkeypatch.setenv("OMNI_TEMP_PATH", r"C:\Users\Jiarui Li\AppData\Local\Temp")
    payload = rb'{"cwd":"C:\\Users\\Jiarui Li\\AppData\\Local\\Temp\\omni-demo"}'

    result = redact_mod.redact(payload)

    assert result.status == "clean"
    assert result.detectors == ()
    assert result.data == payload


def test_regex_pack_redacts_each_minimal_detector() -> None:
    slack_webhook = (
        "https://hooks."
        "slack.com/services/"
        "T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX"
    )
    cases = [
        ("aws_access_key", "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"),
        ("github_token", "token=ghp_abcdefghijklmnopqrstuvwxyz1234567890"),
        ("github_token", "token=github_pat_11ABCDEFG0abcdefghijklmnopqrstuvwxyz1234567890"),
        ("openai_token", "OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz123456789012"),
        ("openai_token", "ANTHROPIC_API_KEY=sk-ant-api03-abcdefghijklmnopqrstuvwxyz123456789012"),
        (
            "jwt",
            "jwt=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiIxMjM0NTY3ODkwIn0.signaturepart",
        ),
        (
            "pem_private_key",
            "-----BEGIN RSA PRIVATE KEY-----\nMIIBOgIBAAJBANsecret\n-----END RSA PRIVATE KEY-----",
        ),
        ("auth_header", "Authorization: Bearer bearer-token-value-123456"),
        ("auth_header", "Authorization: Basic dXNlcjp2ZXJ5LXNlY3JldC12YWx1ZQ=="),
        ("url_credentials", "https://user:password@example.com/path"),
        ("slack_webhook", slack_webhook),
        ("secret_assignment", "password = very-secret-password-123456"),
        ("high_entropy", "--token 7c92d52a0a1b4e8faf4f0f21736e4a9df1fcd980"),
    ]

    for detector, payload in cases:
        result = redact_mod.redact(payload.encode("utf-8"))
        assert result.status == "redacted", detector
        assert detector in result.detectors
        assert payload.encode("utf-8") not in result.data
        assert f"⟨REDACTED:{detector}:".encode("utf-8") in result.data


def test_placeholders_are_stable_for_same_secret() -> None:
    secret = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"

    result = redact_mod.redact(f"{secret}\n{secret}".encode("utf-8"))
    rendered = result.data.decode("utf-8")

    placeholders = re.findall(r"⟨REDACTED:github_token:[0-9a-f]{8}⟩", rendered)
    assert len(placeholders) == 2
    assert len(set(placeholders)) == 1
    assert secret not in rendered


def test_redact_minimal_uses_same_redactor() -> None:
    payload = b"api_key=secret-api-key-value-123456"

    assert redact_mod.redact_minimal(payload) == redact_mod.redact(payload)


def test_redactor_exception_returns_stub_without_raw_payload(monkeypatch) -> None:
    payload = b"secret that must not be stored"

    def fail(_data: bytes, _findings: list[redact_mod.Finding]) -> bytes:
        raise RuntimeError("boom")

    monkeypatch.setattr(redact_mod, "_apply_regex_pack", fail)

    result = redact_mod.redact(payload)
    stub = json.loads(result.data.decode("utf-8"))

    assert result.status == "withheld"
    assert result.detectors == ("withheld",)
    assert stub == {
        "error": "redaction_failed",
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "byte_len": len(payload),
    }
    assert payload.decode("utf-8") not in result.data.decode("utf-8")


def test_large_payload_is_truncated_and_redacted() -> None:
    prefix_secret = b"api_key=large-secret-value-123456"
    suffix_secret = b"token=another-large-secret-value-7890"
    payload = prefix_secret + b"A" * (1024 * 1024 + 10) + suffix_secret

    result = redact_mod.redact(payload)

    assert result.status == "truncated"
    assert "secret_assignment" in result.detectors
    assert len(result.data) < len(payload)
    assert b"large-secret-value-123456" not in result.data
    assert b"another-large-secret-value-7890" not in result.data
    assert b"payload_truncated" in result.data


def test_false_positive_guards_and_allow_values_do_not_redact() -> None:
    allowed = "ghp_allowedallowedallowedallowedallowedallowed12"
    payload = "\n".join(
        [
            "commit 0123456789abcdef0123456789abcdef01234567",
            "HEAD detached at 0123456789abcdef0123456789abcdef01234567",
            "sha512-deadbeefcafebabedeadbeefcafebabedeadbeefcafebabedeadbeefcafebabe",
            "artifact=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            f"token={allowed}",
        ]
    ).encode("utf-8")

    result = redact_mod.redact(payload, allow_values={allowed})

    assert result.status == "clean"
    assert result.detectors == ()
    assert result.data == payload


def test_contextual_hex_api_key_or_token_is_redacted_unless_allowlisted() -> None:
    hex40 = "0123456789abcdef0123456789abcdef01234567"
    hex64 = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
    payload = f"api_key={hex40}\ntoken={hex64}".encode("utf-8")

    result = redact_mod.redact(payload)

    assert result.status == "redacted"
    assert "secret_assignment" in result.detectors
    assert hex40.encode("utf-8") not in result.data
    assert hex64.encode("utf-8") not in result.data

    allowed = redact_mod.redact(payload, allow_values={hex40, hex64})

    assert allowed.status == "clean"
    assert allowed.detectors == ()
    assert allowed.data == payload
