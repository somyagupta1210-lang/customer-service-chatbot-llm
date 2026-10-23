"""Application configuration.

All operational settings can be changed through the .env file without editing code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    base_dir: Path = BASE_DIR
    dataset_path: Path = BASE_DIR / "dataset" / "dataset.csv"
    incoming_dir: Path = BASE_DIR / "knowledge_base" / "incoming"
    data_dir: Path = BASE_DIR / "data"
    versions_dir: Path = BASE_DIR / "data" / "versions"
    quarantine_dir: Path = BASE_DIR / "data" / "quarantine"
    runtime_dir: Path = BASE_DIR / "data" / "runtime"
    db_path: Path = BASE_DIR / "data" / "chatbot.db"
    generation_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    retrieval_threshold: float = _float_env("RETRIEVAL_THRESHOLD", 0.28)
    quality_accuracy_tolerance: float = _float_env("QUALITY_ACCURACY_TOLERANCE", 0.02)
    quality_grounding_tolerance: float = _float_env("QUALITY_GROUNDING_TOLERANCE", 0.02)
    maintenance_start: str = os.getenv("MAINTENANCE_WINDOW_START", "02:00")
    maintenance_end: str = os.getenv("MAINTENANCE_WINDOW_END", "04:00")
    scheduled_update_time: str = os.getenv("SCHEDULED_UPDATE_TIME", "02:00")
    retry_delays: tuple[int, ...] = tuple(
        int(x.strip()) for x in os.getenv("RETRY_DELAYS_MINUTES", "15,30,60").split(",")
        if x.strip().isdigit()
    ) or (15, 30, 60)
    health_check_minutes: int = _int_env("HEALTH_CHECK_MINUTES", 5)
    max_document_size_mb: int = _int_env("MAX_DOCUMENT_SIZE_MB", 10)
    max_latency_ms: int = _int_env("MAX_HEALTH_LATENCY_MS", 5000)
    admin_username: str = os.getenv("ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "change-me")
    app_name: str = "Customer Service Chatbot"


settings = Settings()
