"""Local, deterministic FAQ retrieval.

The original project depended on a remote embedding endpoint. For a customer-service
FAQ with a few dozen rows, a local hashed TF-IDF-style representation is faster,
cheaper and much easier to version and test. Gemini is still used for final wording.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np


TOKEN_RE = re.compile(r"[a-z0-9]+(?:\'[a-z0-9]+)?", re.I)
STOPWORDS = {
    "a", "an", "and", "are", "be", "can", "could", "do", "does", "for", "from",
    "have", "how", "i", "if", "in", "is", "it", "me", "my", "of", "on", "or",
    "please", "the", "this", "to", "we", "what", "when", "where", "will", "you",
    "your", "any", "there", "they", "with", "would", "should", "about",
}


def normalize_text(text: str) -> str:
    return " ".join(str(text).lower().strip().split())


def tokens(text: str) -> list[str]:
    return [token for token in TOKEN_RE.findall(normalize_text(text)) if token not in STOPWORDS]


def _stable_bucket(token: str, dimensions: int) -> int:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "little") % dimensions


class LocalRetriever:
    """Builds and searches a small local FAQ index without a network call."""

    def __init__(self, dimensions: int = 2048) -> None:
        self.dimensions = dimensions

    def _vector(self, text: str) -> np.ndarray:
        words = tokens(text)
        vector = np.zeros(self.dimensions, dtype=np.float32)

        # Word features.
        for word in words:
            vector[_stable_bucket("w:" + word, self.dimensions)] += 1.0

        # Bigrams make short FAQ paraphrases more distinguishable.
        for left, right in zip(words, words[1:]):
            vector[_stable_bucket(f"b:{left}_{right}", self.dimensions)] += 0.75

        norm = np.linalg.norm(vector)
        return vector / norm if norm else vector

    def build(self, questions: list[str], responses: list[str]) -> dict[str, Any]:
        vectors = [self._vector(f"{q} {r}") for q, r in zip(questions, responses)]
        return {
            "format": 2,
            "dimensions": self.dimensions,
            "questions": questions,
            "responses": responses,
            "embeddings": [v.tolist() for v in vectors],
        }

    def search(self, index: dict[str, Any], question: str, top_k: int = 3) -> list[dict[str, Any]]:
        query = self._vector(question)
        matrix = np.asarray(index["embeddings"], dtype=np.float32)
        scores = matrix @ query

        # A small exact-token overlap boost helps FAQ-style questions.
        query_tokens = set(tokens(question))
        results = []
        for i, base_score in enumerate(scores):
            source_tokens = set(tokens(index["questions"][i]))
            union = query_tokens | source_tokens
            overlap = len(query_tokens & source_tokens) / len(union) if union else 0
            score = float(base_score) + 0.20 * overlap
            results.append(
                {
                    "index": i,
                    "question": index["questions"][i],
                    "response": index["responses"][i],
                    "score": min(score, 1.0),
                }
            )

        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:top_k]


def save_index(index: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index), encoding="utf-8")


def load_index(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError("No active knowledge base exists yet.")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != 2:
        raise ValueError("Knowledge base format is unsupported or corrupted.")
    if not data.get("questions") or len(data["questions"]) != len(data.get("embeddings", [])):
        raise ValueError("Knowledge base is empty or corrupted.")
    return data
