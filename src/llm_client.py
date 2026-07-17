"""
llm_client.py
=============
Single OpenRouter client used for BOTH chat completions (LLM) and embeddings.

Usage
-----
from src.llm_client import chat, embed, settings

# Chat
response = chat([{"role": "user", "content": "Hello"}])

# Embeddings  
vectors = embed(["Article text 1", "Article text 2"])
"""

from __future__ import annotations

import os
import textwrap
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ── Runtime settings (read from env, all overridable) ─────────────────────────

@dataclass
class Settings:
    api_key: str = field(
        default_factory=lambda: os.environ.get("OPENROUTER_API_KEY", "")
    )
    base_url: str = "https://openrouter.ai/api/v1"

    # Gemini Alternative
    gemini_api_key: str = field(
        default_factory=lambda: os.environ.get("GEMINI_API_KEY", "")
    )
    embedding_provider: str = field(
        default_factory=lambda: os.environ.get("EMBEDDING_PROVIDER", "openrouter")
    )

    # Models
    llm_model: str = field(
        default_factory=lambda: os.environ.get(
            "LLM_MODEL", "anthropic/claude-sonnet-4-5"
        )
    )
    classifier_model: str = field(
        default_factory=lambda: os.environ.get(
            "CLASSIFIER_MODEL", "google/gemini-flash-1.5"
        )
    )
    embedding_model: str = field(
        default_factory=lambda: os.environ.get(
            "EMBEDDING_MODEL", "qwen/qwen3-embedding-8b"
        )
    )

    # Retrieval
    top_k: int = field(
        default_factory=lambda: int(os.environ.get("RETRIEVAL_TOP_K", "8"))
    )
    agent_max_steps: int = field(
        default_factory=lambda: int(os.environ.get("AGENT_MAX_STEPS", "20"))
    )

    # OpenRouter switches
    allow_fallbacks: bool = field(
        default_factory=lambda: os.environ.get(
            "OPENROUTER_ALLOW_FALLBACKS", "true"
        ).lower()
        == "true"
    )

    @property
    def extra_body(self) -> dict[str, Any]:
        """Extra kwargs forwarded to every OpenRouter call."""
        return {"allow_fallbacks": self.allow_fallbacks}


settings = Settings()


def _build_client() -> OpenAI:
    if not settings.api_key:
        raise EnvironmentError(
            "OPENROUTER_API_KEY is not set. "
            "Copy .env.example → .env and add your key."
        )
    return OpenAI(
        api_key=settings.api_key,
        base_url=settings.base_url,
        default_headers={
            "HTTP-Referer": "https://github.com/Malek74/Ross.AI",
            "X-Title": "Ross.AI - Egyptian Contract Auditor",
        },
    )


_client: OpenAI | None = None
_gemini_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = _build_client()
    return _client


def get_gemini_client() -> OpenAI:
    global _gemini_client
    if _gemini_client is None:
        if not settings.gemini_api_key:
            raise EnvironmentError(
                "GEMINI_API_KEY is not set. "
                "Add it to your .env file to use Gemini for embeddings."
            )
        _gemini_client = OpenAI(
            api_key=settings.gemini_api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
        )
    return _gemini_client


# ── Chat completions ──────────────────────────────────────────────────────────

def chat(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    **kwargs: Any,
) -> str:
    """
    Call the OpenRouter chat endpoint.

    Parameters
    ----------
    messages : list of {"role": ..., "content": ...} dicts
    model : override the default LLM_MODEL
    temperature : default 0.0 for deterministic legal reasoning
    max_tokens : default 4096

    Returns
    -------
    str
        The assistant's text content.
    """
    client = get_client()
    resp = client.chat.completions.create(
        model=model or settings.llm_model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body=settings.extra_body,
        **kwargs,
    )
    return resp.choices[0].message.content or ""


def chat_classifier(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.0,
    max_tokens: int = 512,
    **kwargs: Any,
) -> str:
    """Use the cheap/fast classifier model for intake domain classification."""
    return chat(
        messages,
        model=settings.classifier_model,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )


# ── Embeddings ────────────────────────────────────────────────────────────────

_EMBED_BATCH_SIZE = 64  # OpenRouter embedding batch limit (conservative)


def embed(
    texts: list[str],
    *,
    model: str | None = None,
    batch_size: int = _EMBED_BATCH_SIZE,
) -> list[list[float]]:
    """
    Embed a list of texts using the configured embedding model.

    Automatically batches if len(texts) > batch_size.
    Empty strings are replaced with a single space to avoid API errors.

    Returns
    -------
    list[list[float]]
        One embedding vector per input text, in the same order.
    """
    if settings.embedding_provider == "gemini":
        client = get_gemini_client()
    else:
        client = get_client()

    emb_model = model or settings.embedding_model
    texts = [t if t.strip() else " " for t in texts]

    all_vectors: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = client.embeddings.create(model=emb_model, input=batch)
        ordered = sorted(resp.data, key=lambda x: x.index)
        all_vectors.extend(item.embedding for item in ordered)

    return all_vectors


def embed_one(text: str, **kwargs) -> list[float]:
    """Convenience: embed a single string."""
    return embed([text], **kwargs)[0]


# ── Smoke test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Settings loaded:")
    print(f"  LLM model        : {settings.llm_model}")
    print(f"  Classifier model : {settings.classifier_model}")
    print(f"  Embedding model  : {settings.embedding_model}")
    print(f"  top_k            : {settings.top_k}")
    print()

    # Test embedding (does NOT require API call if key missing — shows error gracefully)
    try:
        vec = embed_one("ما الذي يجعل العقد قابلاً للإبطال؟")
        print(f"Embedding dim: {len(vec)}")
        print(f"First 5 dims: {vec[:5]}")
    except EnvironmentError as e:
        print(f"[No API key] {e}")
