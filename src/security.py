"""Security helpers: authentication, prompt-injection protection and data masking."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


INJECTION_PATTERNS = [
    r"\bignore\s+(all\s+)?previous\s+instructions\b",
    r"\bdisregard\s+(all\s+)?previous\s+instructions\b",
    r"\bignore\s+the\s+system\s+prompt\b",
    r"\breveal\s+(the\s+)?system\s+prompt\b",
    r"\bshow\s+(me\s+)?your\s+hidden\s+instructions\b",
    r"\bdeveloper\s+message\b",
    r"\bdisable\s+(your\s+)?safety\b",
    r"\bforget\s+your\s+instructions\b",
    r"\bprint\s+your\s+api\s*key\b",
]

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")
CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
API_KEY_RE = re.compile(r"\b(?:AIza[0-9A-Za-z_-]{20,}|sk-[A-Za-z0-9_-]{20,})\b")


@dataclass(frozen=True)
class User:
    username: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def authenticate(username: str, password: str, admin_username: str, admin_password: str) -> User | None:
    if username == admin_username and hash_password(password) == hash_password(admin_password):
        return User(username=username, role="admin")
    if username == "user" and password == "user":
        return User(username="user", role="user")
    return None


def require_admin(user: User | None) -> None:
    if user is None or not user.is_admin:
        raise PermissionError("Administrator access is required for this action.")


def detect_prompt_injection(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    return any(re.search(pattern, normalized) for pattern in INJECTION_PATTERNS)


def mask_sensitive_data(text: str) -> str:
    masked = EMAIL_RE.sub("[EMAIL REDACTED]", text)
    masked = PHONE_RE.sub("[PHONE REDACTED]", masked)
    masked = CARD_RE.sub("[CARD REDACTED]", masked)
    masked = API_KEY_RE.sub("[API KEY REDACTED]", masked)
    return masked
