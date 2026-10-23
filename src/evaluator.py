"""Pre-activation quality checks.

The checks are deliberately model-independent. That makes them deterministic in CI
and prevents an unavailable LLM from silently approving a bad knowledge-base update.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .retrieval import LocalRetriever


@dataclass
class QualityReport:
    accuracy: float
    grounding: float
    passed: bool
    details: dict[str, Any]


def _expected_match(retrieved: dict[str, Any], expected_answer: str) -> bool:
    expected_words = set(expected_answer.lower().split())
    answer_words = set(retrieved["response"].lower().split())
    if not expected_words:
        return False
    overlap = len(expected_words & answer_words) / len(expected_words)
    return overlap >= 0.35


def evaluate_index(index: dict[str, Any], evaluation_set: list[dict[str, str]]) -> QualityReport:
    if not evaluation_set:
        return QualityReport(1.0, 1.0, True, {"reason": "No evaluation set supplied."})

    retriever = LocalRetriever(dimensions=int(index["dimensions"]))
    correct = 0
    grounded = 0

    for item in evaluation_set:
        results = retriever.search(index, item["question"], top_k=1)
        if not results:
            continue
        top = results[0]
        if top["score"] >= 0.20:
            grounded += 1
        if _expected_match(top, item["answer"]):
            correct += 1

    total = len(evaluation_set)
    accuracy = correct / total
    grounding = grounded / total
    return QualityReport(
        accuracy=accuracy,
        grounding=grounding,
        passed=True,
        details={"evaluated_questions": total, "correct": correct, "grounded": grounded},
    )


def compare_quality(
    baseline: QualityReport,
    candidate: QualityReport,
    accuracy_tolerance: float,
    grounding_tolerance: float,
) -> QualityReport:
    accuracy_drop = baseline.accuracy - candidate.accuracy
    grounding_drop = baseline.grounding - candidate.grounding
    passed = accuracy_drop <= accuracy_tolerance and grounding_drop <= grounding_tolerance

    return QualityReport(
        accuracy=candidate.accuracy,
        grounding=candidate.grounding,
        passed=passed,
        details={
            **candidate.details,
            "baseline_accuracy": baseline.accuracy,
            "baseline_grounding": baseline.grounding,
            "accuracy_drop": accuracy_drop,
            "grounding_drop": grounding_drop,
            "accuracy_tolerance": accuracy_tolerance,
            "grounding_tolerance": grounding_tolerance,
        },
    )
