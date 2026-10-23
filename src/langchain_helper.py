"""Compatibility layer for the original course project.

Older versions imported create_vector_db(), get_answer() and knowledge_base_exists()
from this module. Keeping these names means existing notebooks/scripts continue to work
while the real implementation now lives in focused service modules.
"""

from __future__ import annotations

from datetime import datetime

from .chatbot import CustomerServiceChatbot
from .config import settings
from .update_pipeline import UpdatePipeline

_pipeline = UpdatePipeline()
_chatbot = CustomerServiceChatbot()


def create_vector_db() -> int:
    """Build and activate the FAQ knowledge base during the configured maintenance window."""
    start_hour, start_minute = map(int, settings.maintenance_start.split(":"))
    maintenance_now = datetime.now().replace(
        hour=start_hour,
        minute=start_minute,
        second=0,
        microsecond=0,
    )
    result = _pipeline.run(now=maintenance_now)

    if result["status"] in {"active", "unchanged"}:
        return len(_pipeline.kb.load_active_index()["questions"])

    raise RuntimeError(f"Knowledge-base update did not activate: {result}")


def knowledge_base_exists() -> bool:
    """Return True when an active version is available."""
    return _pipeline.kb.active_version() is not None


def get_answer(question: str, top_k: int = 3) -> dict:
    """Preserve the original get_answer() API for existing code."""
    return _chatbot.answer(question, top_k=top_k)
