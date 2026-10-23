"""Monitoring and health-check helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .config import settings
from .security import mask_sensitive_data
from .storage import recent_metrics, record_metric


@dataclass
class RequestMetrics:
    latency_ms: float
    confidence: float
    failed: bool
    escalated: bool


def record_request(metrics: RequestMetrics, question: str) -> None:
    details = {"question": mask_sensitive_data(question)}
    record_metric("latency_ms", metrics.latency_ms, details)
    record_metric("confidence", metrics.confidence, details)
    record_metric("failure", 1 if metrics.failed else 0, details)
    record_metric("escalation", 1 if metrics.escalated else 0, details)


def health_check(chatbot: Any) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = chatbot.answer("Do you provide any virtual internship?")
        latency_ms = (time.perf_counter() - started) * 1000
        healthy = bool(result.get("answer")) and latency_ms <= settings.max_latency_ms
        return {
            "healthy": healthy,
            "latency_ms": round(latency_ms, 2),
            "confidence": float(result.get("score", 0)),
            "reason": "ok" if healthy else "Health threshold failed",
        }
    except Exception as exc:
        return {"healthy": False, "latency_ms": None, "confidence": 0.0, "reason": str(exc)}


def dashboard_summary() -> dict[str, Any]:
    metrics = recent_metrics(200)
    by_name: dict[str, list[float]] = {}
    for row in metrics:
        by_name.setdefault(row["metric_name"], []).append(float(row["value"]))

    return {
        "requests": len(by_name.get("latency_ms", [])),
        "failures": int(sum(by_name.get("failure", []))),
        "escalations": int(sum(by_name.get("escalation", []))),
        "average_latency_ms": (
            sum(by_name.get("latency_ms", [])) / len(by_name["latency_ms"])
            if by_name.get("latency_ms") else 0
        ),
        "average_confidence": (
            sum(by_name.get("confidence", [])) / len(by_name["confidence"])
            if by_name.get("confidence") else 0
        ),
    }
