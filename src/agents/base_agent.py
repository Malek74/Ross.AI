"""Reusable autonomous, tool-calling specialist for one legal domain."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import yaml

from src.agents.tools import DomainTools
from src.embeddings import DomainIndex
from src.llm_client import get_client, settings

_ROOT = Path(__file__).resolve().parents[2]


class DomainAgent:
    """An LLM specialist whose strategy is controlled by tool calls, not Python checks."""

    def __init__(
        self,
        name: str,
        index_path: str | Path,
        playbook_path: str | Path,
        domain_label: str = "",
        law_ref: str = "",
    ) -> None:
        self.name = name
        self.index_path = Path(index_path)
        self.playbook_path = Path(playbook_path)
        self.domain_label = domain_label or name.title()
        self.law_ref = law_ref or f"Egyptian {name.title()} Law"

    def run(self, contract: str) -> dict[str, Any]:
        """Audit a contract. The model decides retrieval and risk-flagging order."""
        return self._agent_loop(
            goal=f"Audit this contract under {self.name} law. Produce a cited risk report.",
            contract=contract,
            question=None,
            mode="audit",
        )

    def answer(self, question: str, contract: str | None = None) -> dict[str, Any]:
        """Answer a legal question using only this domain's corpus and optional contract."""
        return self._agent_loop(
            goal=f"Answer the user's question under {self.name} law with cited articles. State uncertainty when the available sources do not support an answer.",
            contract=contract or "",
            question=question,
            mode="chat",
        )

    def _agent_loop(self, *, goal: str, contract: str, question: str | None, mode: Literal["audit", "chat"]) -> dict[str, Any]:
        index = self._load_index()
        tools = DomainTools(index=index, contract=contract)
        rubric = self._load_playbook()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt(goal, rubric, mode)},
            {"role": "user", "content": self._input_prompt(contract, question, mode)},
        ]

        client = get_client()
        final_text = ""
        trace: list[dict[str, Any]] = []
        for step in range(settings.agent_max_steps):
            response = client.chat.completions.create(
                model=settings.llm_model, messages=messages, tools=tools.definitions(),
                tool_choice="auto", temperature=0.0, max_tokens=2048, extra_body=settings.extra_body,
            )
            message = response.choices[0].message
            if message.content:
                final_text = message.content
            messages.append(message.model_dump(exclude_none=True))

            if not message.tool_calls:
                break
            for call in message.tool_calls:
                try:
                    arguments = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    result = {"error": "Tool arguments were not valid JSON."}
                else:
                    result = tools.call(call.function.name, arguments)
                trace.append({"step": step + 1, "tool": call.function.name, "result": result})
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)})
            if tools.finished_summary is not None:
                final_text = tools.finished_summary
                break

        if not final_text:
            final_text = "The agent reached its step limit before producing a supported final answer."
        return {
            "domain": self.name, "mode": mode, "summary": final_text,
            "flags": tools.flags, "trace": trace,
            "status": "finished" if tools.finished_summary is not None else "step_limit_or_text_response",
        }

    def _load_index(self) -> DomainIndex:
        root = self.index_path if self.index_path.is_absolute() else _ROOT / self.index_path
        return DomainIndex.load(self.name, index_root=root.parent)

    def _load_playbook(self) -> dict[str, Any]:
        path = self.playbook_path if self.playbook_path.is_absolute() else _ROOT / self.playbook_path
        with path.open(encoding="utf-8") as file:
            return yaml.safe_load(file) or {}

    def _system_prompt(self, goal: str, rubric: dict[str, Any], mode: str) -> str:
        rubric_text = yaml.safe_dump(rubric, allow_unicode=True, sort_keys=False)
        return f"""You are the {self.domain_label} specialist in a grounded Egyptian-law paralegal.
LEGAL DOMAIN: {self.law_ref}
GOAL: {goal}
MODE: {mode}
Use tools to retrieve legal authority before making legal claims. You may only cite articles returned by a tool. Do not invent article numbers, contract terms, facts, or quotations. In audit mode, call flag_risk only for a real contract substring. In chat mode, do not create risk flags unless explicitly asked to audit. When evidence is insufficient, say so. Finish by calling finish.

RUBRIC (guidance, not a mandatory workflow):
{rubric_text}"""

    @staticmethod
    def _input_prompt(contract: str, question: str | None, mode: str) -> str:
        parts = [f"Requested mode: {mode}."]
        if question:
            parts.append(f"User question:\n{question}")
        if contract:
            parts.append(f"Submitted contract:\n{contract}")
        return "\n\n".join(parts)


class StubAgent:
    """Registry placeholder for a recognized legal domain without a usable corpus."""

    def __init__(self, name: str) -> None:
        self.name = name

    def run(self, contract: str, **_: Any) -> dict[str, Any]:
        return self._unavailable()

    def answer(self, question: str, contract: str | None = None, **_: Any) -> dict[str, Any]:
        return self._unavailable()

    def _unavailable(self) -> dict[str, Any]:
        return {
            "domain": self.name,
            "status": "recognized_not_available",
            "message": f"The {self.name} specialist is registered but not yet available.",
        }
