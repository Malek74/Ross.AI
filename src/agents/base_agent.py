"""
agents/base_agent.py
====================
DomainAgent: an LLM-in-a-tool-use-loop that audits a contract against
one domain's statute index + playbook rubric.

This is an AGENT, not a workflow:
  - Goal-driven (not a fixed checklist loop)
  - Autonomous tool selection (the LLM picks which tool to call next)
  - Bounded by max_steps and evidence validation at the tool boundary
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.llm_client import get_client, settings
from src.playbook_loader import load_playbook, format_rubric
from src.prompt_templates import SPECIALIST_SYSTEM, SPECIALIST_USER
from src.agents.tools import TOOL_SCHEMAS, ToolContext, execute_tool

logger = logging.getLogger(__name__)


@dataclass
class AuditResult:
    domain: str
    flags: list[dict]
    summary: str
    steps: int
    tool_trace: list[dict]
    elapsed_s: float


@dataclass
class DomainAgent:
    name: str
    index_path: str
    playbook_path: str
    domain_label: str = ""
    law_ref: str = ""

    _index: Any = field(default=None, init=False, repr=False)
    _playbook: dict = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self):
        if not self.domain_label:
            self.domain_label = self.name.title() + " Code"
        if not self.law_ref:
            self.law_ref = "Egyptian Civil Code (Law 131/1948)"

    @property
    def index(self):
        if self._index is None:
            from src.embeddings import DomainIndex
            self._index = DomainIndex.load(self.name)
        return self._index

    @property
    def playbook(self):
        if not self._playbook:
            self._playbook = load_playbook(self.playbook_path)
        return self._playbook

    def run(self, contract_text: str, *, max_steps: int | None = None) -> AuditResult:
        max_steps = max_steps or settings.agent_max_steps
        rubric = format_rubric(self.playbook)

        system_prompt = SPECIALIST_SYSTEM.format(
            domain_label=self.domain_label,
            law_ref=self.law_ref,
            rubric=rubric,
        )
        user_prompt = SPECIALIST_USER.format(
            contract_text=contract_text,
            domain_label=self.domain_label,
        )

        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        ctx = ToolContext(
            domain_index=self.index,
            contract_text=contract_text,
        )

        client = get_client()
        tool_trace: list[dict] = []
        t0 = time.time()

        for step in range(max_steps):
            resp = client.chat.completions.create(
                model=settings.llm_model,
                messages=messages,
                tools=TOOL_SCHEMAS,
                temperature=0.0,
                max_tokens=4096,
                extra_body=settings.extra_body,
            )

            msg = resp.choices[0].message
            messages.append(_message_to_dict(msg))

            if not msg.tool_calls:
                break

            for tc in msg.tool_calls:
                fn_name = tc.function.name
                try:
                    fn_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    fn_args = {}

                result = execute_tool(fn_name, fn_args, ctx)

                trace_entry = {
                    "step": step,
                    "tool": fn_name,
                    "args": fn_args,
                    "result_preview": _preview(result),
                }
                tool_trace.append(trace_entry)
                logger.info("Step %d: %s(%s) → %s", step, fn_name, _compact(fn_args), _preview(result))

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

            if ctx.finished:
                break

        elapsed = time.time() - t0

        return AuditResult(
            domain=self.name,
            flags=ctx.flags,
            summary=ctx.finish_summary or f"Completed in {step + 1} steps",
            steps=step + 1,
            tool_trace=tool_trace,
            elapsed_s=round(elapsed, 2),
        )


@dataclass
class StubAgent:
    name: str

    def run(self, contract_text: str, **kwargs) -> dict:
        return {
            "domain": self.name,
            "status": "recognized_not_available",
            "message": f"The {self.name} specialist is registered but not yet available.",
        }


def _message_to_dict(msg) -> dict:
    d: dict[str, Any] = {"role": msg.role}
    if msg.content:
        d["content"] = msg.content
    if msg.tool_calls:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ]
    return d


def _preview(obj: dict, max_len: int = 120) -> str:
    s = json.dumps(obj, ensure_ascii=False)
    return s[:max_len] + "…" if len(s) > max_len else s


def _compact(obj: dict) -> str:
    parts = []
    for k, v in obj.items():
        sv = str(v)
        if len(sv) > 40:
            sv = sv[:37] + "…"
        parts.append(f"{k}={sv!r}")
    return ", ".join(parts)
