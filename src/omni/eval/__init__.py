"""Read-only behavior evaluation for ingested runs."""

from omni.eval.classify import evaluate_dogfood, evaluate_run, review_dogfood
from omni.jsonio import as_json

__all__ = [
    "as_json",
    "evaluate_dogfood",
    "evaluate_run",
    "review_dogfood",
]
