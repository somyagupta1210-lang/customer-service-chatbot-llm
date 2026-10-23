"""Customer-service chatbot service."""

from __future__ import annotations

import time
from typing import Any

try:
    from google import genai
    from google.genai import types
except ImportError:  # Local/demo mode can run without the optional Gemini package.
    genai = None
    types = None

from .config import settings
from .knowledge_base import KnowledgeBaseManager
from .monitoring import RequestMetrics, record_request
from .retrieval import LocalRetriever
from .security import detect_prompt_injection, mask_sensitive_data


SAFE_FALLBACK = "I don't know based on the available FAQ."


class CustomerServiceChatbot:
    def __init__(self) -> None:
        self.kb = KnowledgeBaseManager()
        self.retriever = LocalRetriever()
        self.client = (
            genai.Client(api_key=settings.gemini_api_key)
            if settings.gemini_api_key and genai is not None else None
        )

    def answer(self, question: str, top_k: int = 3) -> dict[str, Any]:
        started = time.perf_counter()
        failed = False
        escalated = False

        if detect_prompt_injection(question):
            escalated = True
            result = {
                "answer": "I can help with customer-service questions, but I can't follow requests to reveal or override system instructions.",
                "source_question": "",
                "score": 0.0,
                "escalated": True,
            }
            record_request(
                RequestMetrics((time.perf_counter() - started) * 1000, 0.0, False, True),
                question,
            )
            return result

        safe_question = mask_sensitive_data(question)
        index = self.kb.load_active_index()
        results = self.retriever.search(index, safe_question, top_k=top_k)
        if not results:
            failed = True
            answer = SAFE_FALLBACK
            latency = (time.perf_counter() - started) * 1000
            record_request(RequestMetrics(latency, 0.0, True, True), question)
            return {"answer": answer, "source_question": "", "score": 0.0, "escalated": True}

        best = results[0]
        score = float(best["score"])

        # If retrieval is weak, do not ask an LLM to guess.
        if score < settings.retrieval_threshold:
            answer = SAFE_FALLBACK
            escalated = True
        elif not self.client:
            # Local/demo mode still works when no API key is configured.
            answer = best["response"]
        else:
            context = "\n\n---\n\n".join(
                f"FAQ QUESTION: {item['question']}\nFAQ ANSWER: {item['response']}"
                for item in results
            )
            prompt = f"""You are a customer-service Q&A assistant for an e-learning company.

Use ONLY the FAQ context below. Never invent prices, policies, links, guarantees or
course details. If the context is insufficient, reply exactly:
"{SAFE_FALLBACK}"

Keep the answer concise and helpful.

FAQ CONTEXT:
{mask_sensitive_data(context)}

USER QUESTION:
{safe_question}
"""
            try:
                response = self.client.models.generate_content(
                    model=settings.generation_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(temperature=0.1),
                )
                answer = (response.text or "").strip() or best["response"]
            except Exception:
                # A provider outage must not turn a good FAQ match into a crash.
                answer = best["response"]
                failed = True

        latency = (time.perf_counter() - started) * 1000
        record_request(RequestMetrics(latency, score, failed, escalated), question)
        return {
            "answer": answer,
            "source_question": best["question"],
            "score": score,
            "escalated": escalated,
        }
