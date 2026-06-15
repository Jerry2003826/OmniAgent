"""Shared metadata-leak assertions for machine-facing read views."""

from __future__ import annotations

from typing import Any

FORBIDDEN_KEY_FRAGMENTS = (
    "run_id",
    "_cand_id",
    "note_id",
    "pattern_id",
    "evidence",
    "created_at",
    "updated_at",
    "confidence",
    "timestamp",
    "trust",
    "task_id",
)

FORBIDDEN_VALUE_FRAGMENTS = (
    "fact_",
    "failure_cand_",
    "exp_cand_",
    "pref_cand_",
    "task_",
    "note_",
    "pattern_",
)


def assert_no_metadata_leak(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_lower = str(key).lower()
            for forbidden in FORBIDDEN_KEY_FRAGMENTS:
                assert forbidden not in key_lower, f"leaked key: {key}"
            assert_no_metadata_leak(item)
    elif isinstance(value, list):
        for item in value:
            assert_no_metadata_leak(item)
    elif isinstance(value, str):
        lowered = value.lower()
        for forbidden in FORBIDDEN_VALUE_FRAGMENTS:
            assert forbidden not in lowered, f"leaked value: {value}"
