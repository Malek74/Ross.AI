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


def _apply_revisions(contract: str, revisions: list[dict[str, Any]]) -> str:
    """Return the original contract with each revised clause spliced in at its offset.

    Uses the offsets recorded by validate_quote (quote_match.start/end) so the rest of
    the document — headings, numbering, spacing — is preserved byte-for-byte. Falls back
    to a plain string replace when an offset is missing.
    """
    if not contract:
        return ""
    spans: list[tuple[int, int, str]] = []
    for rev in revisions:
        match = rev.get("quote_match") or {}
        start, end = match.get("start"), match.get("end")
        revised = rev.get("revised_clause", "")
        if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(contract):
            spans.append((start, end, revised))
    doc = contract
    if spans:
        # Apply from the last offset backwards so earlier offsets stay valid.
        for start, end, revised in sorted(spans, key=lambda s: s[0], reverse=True):
            doc = doc[:start] + revised + doc[end:]
        return doc
    # No usable offsets — best-effort textual replacement.
    for rev in revisions:
        original = rev.get("original_clause", "")
        if original and original in doc:
            doc = doc.replace(original, rev.get("revised_clause", ""), 1)
    return doc


def _assemble_draft(drafts: list[dict[str, Any]]) -> str:
    """Assemble drafted clauses into one numbered document body."""
    parts: list[str] = []
    for i, draft in enumerate(drafts, 1):
        text = (draft.get("clause_text") or "").strip()
        if text:
            parts.append(f"{i}. {text}")
    return "\n\n".join(parts)


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
        """Synchronous entry point — drains the streaming loop and returns the final result."""
        result: dict[str, Any] = {}
        for event_type, data in self._agent_loop_stream(
            goal=goal, contract=contract, question=question, mode=mode, lang=lang
        ):
            if event_type == "done":
                result = data
        return result

    def _agent_loop_stream(
        self,
        *,
        goal: str,
        contract: str,
        question: str | None,
        mode: Literal["audit", "chat", "revise", "draft"],
        lang: str = "en",
    ):
        """LLM-in-a-loop that yields ("step", info) events as it works, then ("done", result)."""
        index = self._load_index()
        tools = DomainTools(index=index, contract=contract)
        rubric = self._load_playbook()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt(rubric, mode, lang)},
            {"role": "user", "content": self._input_prompt(contract, question, mode)},
        ]

        final_text = ""
        trace: list[dict[str, Any]] = []
        nudges = 0
        yield ("step", {"action": "thinking", "detail": "Planning..."})

        for step in range(settings.agent_max_steps):
            response = create_completion(
                model=settings.llm_model, messages=messages, tools=tools.definitions(mode=mode),
                tool_choice="auto", temperature=0.0, max_tokens=4096, extra_body=settings.extra_body,
            )
            tracker.record(response, endpoint=f"specialist:{self.name}")
            message = response.choices[0].message
            if message.content:
                final_text = message.content
            messages.append(message.model_dump(exclude_none=True))

            if not message.tool_calls:
                # The model narrated instead of acting. If it hasn't produced anything
                # terminal yet, push it to use its tools rather than ending on prose.
                produced = bool(tools.flags or tools.revisions or tools.drafts) or tools.finished_summary is not None
                if not produced and nudges < 2:
                    nudges += 1
                    messages.append({"role": "user", "content": self._nudge(mode)})
                    yield ("step", {"action": "thinking", "detail": "Working..."})
                    continue
                break
            for call in message.tool_calls:
                yield ("step", self._describe_tool_step(call.function.name))
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
        yield ("done", self._build_result(mode, tools, contract, trace, final_text))

    def _build_result(self, mode, tools, contract, trace, final_text) -> dict[str, Any]:
        result: dict[str, Any] = {
            "domain": self.name, "mode": mode, "summary": final_text,
            "flags": tools.flags, "trace": trace,
            "status": "finished" if tools.finished_summary is not None else "step_limit_or_text_response",
        }
        if tools.revisions:
            # Remap tool-internal keys to the shape the frontend/API contract expects.
            result["revisions"] = [
                {
                    "clause_original": r["original_clause"],
                    "clause_revised": r["revised_clause"],
                    "article_ref": r["article_ref"],
                    "rationale": r["rationale"],
                }
                for r in tools.revisions
            ]
            # Reworked full contract: splice each revised clause back into the original
            # text at its recorded offset, preserving all original formatting.
            reworked = _apply_revisions(contract, tools.revisions)
            if reworked:
                result["revised_document"] = reworked
        if tools.drafts:
            result["drafts"] = [
                {
                    "topic": d.get("topic"),
                    "text": d["clause_text"],
                    "article_ref": d["article_ref"],
                    "rationale": d["rationale"],
                }
                for d in tools.drafts
            ]
            assembled = _assemble_draft(tools.drafts)
            if assembled:
                result["drafted_document"] = assembled
        return result

    def draft_stream(self, contract_type: str, requirements: str = "", lang: str = "en"):
        """Streaming variant of draft(): yields ("step", info) events then ("done", result)."""
        prompt = f"Draft a {contract_type} contract compliant with Egyptian {self.name} law."
        if requirements:
            prompt += f" Requirements: {requirements}"
        yield from self._agent_loop_stream(goal=prompt, contract="", question=prompt, mode="draft", lang=lang)

    def revise_stream(self, contract: str, flag_ids: list[str] | None = None, lang: str = "en"):
        """Streaming variant of revise(): yields ("step", info) events then ("done", result)."""
        yield from self._agent_loop_stream(
            goal=f"Revise the flagged clauses in this contract to comply with {self.name} law. Preserve the original intent. Use revise_clause for each fix, citing the governing article.",
            contract=contract, question=None, mode="revise", lang=lang,
        )

    @staticmethod
    def _nudge(mode: str) -> str:
        actions = {
            "draft": "call search_statutes to find governing articles, then draft_clause for EACH clause, then finish",
            "revise": "call search_statutes then revise_clause for EACH flagged clause, then finish",
            "audit": "call search_statutes then flag_risk for each issue, then finish",
            "chat": "call search_statutes to gather authority, then finish with your answer",
        }
        return (
            "Do not narrate your plan in prose. Act now using tool calls only: "
            + actions.get(mode, actions["audit"])
            + ". Respond with tool calls, not text."
        )

    @staticmethod
    def _describe_tool_step(tool_name: str) -> dict[str, str]:
        details = {
            "search_statutes": "Searching statutes...",
            "get_article": "Reading an article...",
            "flag_risk": "Flagging a risk...",
            "revise_clause": "Revising a clause...",
            "draft_clause": "Drafting a clause...",
            "validate_draft": "Validating a clause...",
            "finish": "Finalizing...",
        }
        return {"action": tool_name, "detail": details.get(tool_name, f"Running {tool_name}...")}

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
