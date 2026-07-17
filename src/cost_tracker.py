"""Track cumulative OpenRouter API costs across the session."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

_COST_LOG = Path(__file__).parent.parent / "data" / "cost_log.jsonl"


@dataclass
class _Entry:
    timestamp: float
    model: str
    endpoint: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float


@dataclass
class CostTracker:
    entries: list[_Entry] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, response, *, endpoint: str = "chat") -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        cost = getattr(usage, "cost", None) or 0.0
        entry = _Entry(
            timestamp=time.time(),
            model=getattr(response, "model", "unknown"),
            endpoint=endpoint,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            total_tokens=getattr(usage, "total_tokens", 0) or 0,
            cost_usd=float(cost),
        )
        with self._lock:
            self.entries.append(entry)
            self._append_log(entry)

    @property
    def total_cost(self) -> float:
        with self._lock:
            return sum(e.cost_usd for e in self.entries)

    @property
    def call_count(self) -> int:
        with self._lock:
            return len(self.entries)

    def summary(self) -> dict:
        with self._lock:
            by_model: dict[str, dict] = {}
            for e in self.entries:
                m = by_model.setdefault(e.model, {
                    "calls": 0, "prompt_tokens": 0,
                    "completion_tokens": 0, "cost_usd": 0.0,
                })
                m["calls"] += 1
                m["prompt_tokens"] += e.prompt_tokens
                m["completion_tokens"] += e.completion_tokens
                m["cost_usd"] += e.cost_usd
            return {
                "total_cost_usd": sum(e.cost_usd for e in self.entries),
                "total_calls": len(self.entries),
                "total_tokens": sum(e.total_tokens for e in self.entries),
                "by_model": by_model,
            }

    @staticmethod
    def _append_log(entry: _Entry) -> None:
        try:
            _COST_LOG.parent.mkdir(parents=True, exist_ok=True)
            with _COST_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": entry.timestamp,
                    "model": entry.model,
                    "endpoint": entry.endpoint,
                    "prompt_tokens": entry.prompt_tokens,
                    "completion_tokens": entry.completion_tokens,
                    "cost_usd": entry.cost_usd,
                }) + "\n")
        except OSError:
            pass


tracker = CostTracker()
