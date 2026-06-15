import pytest

from tests.leak_helpers import FORBIDDEN_KEY_FRAGMENTS
from tests.leak_helpers import assert_no_metadata_leak


def test_forbidden_key_fragments_include_task_id() -> None:
    assert "task_id" in FORBIDDEN_KEY_FRAGMENTS


@pytest.mark.parametrize(
    "value",
    [
        "task_1234567890abcdef",
        "note_1234567890abcdef",
        "pattern_1234567890abcdef",
        "pref_cand_1234567890abcdef",
    ],
)
def test_string_values_do_not_leak_internal_identifiers(value: str) -> None:
    with pytest.raises(AssertionError):
        assert_no_metadata_leak({"items": [value]})
