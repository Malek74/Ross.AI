"""Reusable autonomous, tool-calling specialist for one legal domain."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import yaml

from src.agents.tools import DomainTools
from src.cost_tracker import tracker
from src.embeddings import DomainIndex
from src.llm_client import create_completion, settings
from src.prompt_templates import (
    SPECIALIST_SYSTEM_AUDIT,
    SPECIALIST_SYSTEM_CHAT,
    SPECIALIST_SYSTEM_REVISE,
    SPECIALIST_SYSTEM_DRAFT,
    SPECIALIST_USER_AUDIT,
    SPECIALIST_USER_CHAT,
    SPECIALIST_USER_CHAT_WITH_CONTRACT,
    SPECIALIST_USER_REVISE,
    SPECIALIST_USER_DRAFT,
)

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

    def run(self, contract: str, lang: str = "en") -> dict[str, Any]:
        """Audit a contract. The model decides retrieval and risk-flagging order."""
        return self._agent_loop(
            goal=f"Audit this contract under {self.name} law. Produce a cited risk report.",
            contract=contract,
            question=None,
            mode="audit",
            lang=lang,
        )

    def answer(self, question: str, contract: str | None = None, lang: str = "en") -> dict[str, Any]:
        """Answer a legal question using only this domain's corpus and optional contract."""
        return self._agent_loop(
            goal=f"Answer the user's question under {self.name} law with cited articles. State uncertainty when the available sources do not support an answer.",
            contract=contract or "",
            question=question,
            mode="chat",
            lang=lang,
        )

    def revise(self, contract: str, flag_ids: list[str] | None = None, lang: str = "en") -> dict[str, Any]:
        """Revise flagged clauses in a contract to comply with this domain's law."""
        return self._agent_loop(
            goal=f"Revise the flagged clauses in this contract to comply with {self.name} law. Preserve the original intent. Use revise_clause for each fix, citing the governing article.",
            contract=contract,
            question=None,
            mode="revise",
            lang=lang,
        )

    def draft(self, contract_type: str, requirements: str = "", lang: str = "en") -> dict[str, Any]:
        """Draft a new contract grounded in this domain's statute corpus."""
        prompt = f"Draft a {contract_type} contract compliant with Egyptian {self.name} law."
        if requirements:
            prompt += f" Requirements: {requirements}"
        return self._agent_loop(
            goal=prompt,
            contract="",
            question=prompt,
            mode="draft",
            lang=lang,
        )

    def _agent_loop(
        self,
        *,
        goal: str,
        contract: str,
        question: str | None,
        mode: Literal["audit", "chat", "revise", "draft"],
        lang: str = "en",
    ) -> dict[str, Any]:
        index = self._load_index()
        tools = DomainTools(index=index, contract=contract)
        rubric = self._load_playbook()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt(rubric, mode, lang)},
            {"role": "user", "content": self._input_prompt(contract, question, mode)},
        ]

        final_text = ""
        trace: list[dict[str, Any]] = []
        for step in range(settings.agent_max_steps):
            response = create_completion(
                model=settings.llm_model, messages=messages, tools=tools.definitions(mode=mode),
                tool_choice="auto", temperature=0.0, max_tokens=2048, extra_body=settings.extra_body,
            )
            tracker.record(response, endpoint=f"specialist:{self.name}")
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
        result: dict[str, Any] = {
            "domain": self.name, "mode": mode, "summary": final_text,
            "flags": tools.flags, "trace": trace,
            "status": "finished" if tools.finished_summary is not None else "step_limit_or_text_response",
        }
        if tools.revisions:
            result["revisions"] = tools.revisions
        if tools.drafts:
            result["drafts"] = tools.drafts
        return result

    def _load_index(self) -> DomainIndex:
        root = self.index_path if self.index_path.is_absolute() else _ROOT / self.index_path
        return DomainIndex.load(self.name, index_root=root.parent)

    def _load_playbook(self) -> dict[str, Any]:
        path = self.playbook_path if self.playbook_path.is_absolute() else _ROOT / self.playbook_path
        with path.open(encoding="utf-8") as file:
            return yaml.safe_load(file) or {}

    def _system_prompt(self, rubric: dict[str, Any], mode: str, lang: str = "en") -> str:
        rubric_text = yaml.safe_dump(rubric, allow_unicode=True, sort_keys=False)
        templates = {
            "audit": SPECIALIST_SYSTEM_AUDIT,
            "chat": SPECIALIST_SYSTEM_CHAT,
            "revise": SPECIALIST_SYSTEM_REVISE,
            "draft": SPECIALIST_SYSTEM_DRAFT,
        }
        template = templates.get(mode, SPECIALIST_SYSTEM_AUDIT)
        prompt = template.format(
            domain_label=self.domain_label,
            law_ref=self.law_ref,
            rubric=rubric_text,
        )
        if lang == "ar":
            prompt += "\n\nLANGUAGE: You MUST write ALL output in Arabic (العربية) — summaries, rationale, flag descriptions, everything user-facing."
        return prompt

    def _input_prompt(self, contract: str, question: str | None, mode: str) -> str:
        if mode == "audit":
            return SPECIALIST_USER_AUDIT.format(
                contract_text=contract,
                domain_label=self.domain_label,
            )
        if mode == "revise":
            return SPECIALIST_USER_REVISE.format(
                contract_text=contract,
                domain_label=self.domain_label,
            )
        if mode == "draft":
            return SPECIALIST_USER_DRAFT.format(
                question=question or "",
                domain_label=self.domain_label,
            )
        if question and contract:
            return SPECIALIST_USER_CHAT_WITH_CONTRACT.format(
                question=question,
                contract_text=contract,
            )
        return SPECIALIST_USER_CHAT.format(question=question or "")


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
