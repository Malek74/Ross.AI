"""Goal-driven paralegal that consults domain specialists as tools."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from src.agents.classifier import classify_domains
from src.agents.registry import REGISTRY
from src.agents.synthesizer import synthesize_flags
from src.llm_client import get_client, settings
from src.prompt_templates import ORCHESTRATOR_SYSTEM, ORCHESTRATOR_USER

TaskMode = Literal["audit", "chat"]
RouteMode = Literal["auto", "manual"]


@dataclass
class OrchestrationState:
    contract: str
    question: str | None
    task: TaskMode
    allowed_domains: set[str]
    classification: list[dict[str, Any]] = field(default_factory=list)
    consultations: dict[str, dict[str, Any]] = field(default_factory=dict)
    final_memo: dict[str, Any] | None = None
    finished: bool = False


class ParalegalOrchestrator:
    """An LLM agent whose tools are classification and domain specialists."""

    def __init__(self, registry: dict[str, dict] | None = None) -> None:
        self.registry = registry or REGISTRY

    def run(
        self,
        *,
        contract: str = "",
        question: str | None = None,
        mode: RouteMode = "auto",
        agents: list[str] | None = None,
        task: TaskMode = "audit",
    ) -> dict[str, Any]:
        """Pursue a cited audit or legal-chat goal through specialist tool calls."""
        if task == "audit" and not contract:
            raise ValueError("An audit requires contract text.")
        if task == "chat" and not question:
            raise ValueError("A chat request requires a question.")
        if mode not in {"auto", "manual"}:
            raise ValueError("mode must be 'auto' or 'manual'.")

        selected = agents or []
        unknown = [domain for domain in selected if domain not in self.registry]
        if unknown:
            raise ValueError(f"Unknown domain(s): {', '.join(unknown)}")
        if mode == "manual" and not selected:
            raise ValueError("Manual mode requires at least one selected domain.")

        allowed = set(selected) if mode == "manual" else set(self.registry)
        state = OrchestrationState(contract, question, task, allowed)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt(mode, task, selected)},
            {"role": "user", "content": self._input_prompt(contract, question, task)},
        ]

        client = get_client()
        trace: list[dict[str, Any]] = []
        final_text = ""
        for step in range(settings.agent_max_steps):
            response = client.chat.completions.create(
                model=settings.llm_model,
                messages=messages,
                tools=self._tool_schemas(mode),
                tool_choice="auto",
                temperature=0.0,
                max_tokens=2048,
                extra_body=settings.extra_body,
            )
            message = response.choices[0].message
            if message.content:
                final_text = message.content
            messages.append(message.model_dump(exclude_none=True))
            if not message.tool_calls:
                break

            for call in message.tool_calls:
                result = self._execute_tool(call.function.name, call.function.arguments or "{}", state, mode)
                trace.append({"step": step + 1, "tool": call.function.name, "result": result})
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)})
            if state.finished:
                final_text = state.final_memo["summary"]
                break

        memo = state.final_memo or self._build_memo(state, final_text or "The paralegal reached its step limit before completing a cited memo.")
        return {
            "routing": {
                "mode": mode,
                "classification": state.classification,
                "consulted": list(state.consultations),
                "stubbed": [domain for domain, result in state.consultations.items() if result.get("status") == "recognized_not_available"],
            },
            "task": task,
            "summary": memo["summary"],
            "flags_by_domain": memo["flags_by_domain"],
            "specialist_results": state.consultations,
            "trace": trace,
            "status": "finished" if state.finished else "step_limit_or_text_response",
        }

    def _tool_schemas(self, mode: RouteMode) -> list[dict[str, Any]]:
        schemas = [
            {
                "type": "function",
                "function": {
                    "name": "consult_specialist",
                    "description": "Ask a legal-domain specialist to audit or answer the current request. Consult only a domain justified by the request.",
                    "parameters": {
                        "type": "object",
                        "properties": {"domain": {"type": "string", "enum": list(self.registry)}, "reason": {"type": "string"}},
                        "required": ["domain", "reason"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "synthesize",
                    "description": "Merge consulted specialist evidence into one concise cited memo; do not add uncited legal claims.",
                    "parameters": {
                        "type": "object",
                        "properties": {"summary": {"type": "string"}},
                        "required": ["summary"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "finish",
                    "description": "Finish after consulting sufficient specialists and synthesizing the result.",
                    "parameters": {
                        "type": "object",
                        "properties": {"summary": {"type": "string"}},
                        "required": ["summary"],
                        "additionalProperties": False,
                    },
                },
            },
        ]
        if mode == "auto":
            schemas.insert(0, {
                "type": "function",
                "function": {
                    "name": "classify",
                    "description": "Obtain a cheap-model domain-routing hint. It informs but does not constrain which specialist may be consulted.",
                    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
                },
            })
        return schemas

    def _execute_tool(self, name: str, raw_arguments: str, state: OrchestrationState, mode: RouteMode) -> dict[str, Any]:
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return {"error": "Tool arguments were not valid JSON."}
        if name == "classify":
            source = state.question or state.contract
            state.classification = classify_domains(source, self.registry)
            return {"domains": state.classification}
        if name == "consult_specialist":
            domain = arguments.get("domain")
            if domain not in state.allowed_domains:
                return {"error": f"Domain '{domain}' is not allowed in manual routing mode."}
            if domain in state.consultations:
                return {"cached": True, "result": state.consultations[domain]}
            entry = self.registry.get(domain)
            if entry is None:
                return {"error": f"Unknown domain '{domain}'."}
            if not entry.get("live", False):
                result = {
                    "domain": domain,
                    "status": "recognized_not_available",
                    "message": f"The {domain} specialist is registered but its corpus index is not ready.",
                }
                state.consultations[domain] = result
                return {"domain": domain, "result": result}
            agent = entry["agent"]
            try:
                result = agent.run(state.contract) if state.task == "audit" else agent.answer(state.question or "", state.contract or None)
            except FileNotFoundError:
                result = {
                    "domain": domain,
                    "status": "recognized_not_available",
                    "message": f"The {domain} specialist's corpus index is not available.",
                }
            state.consultations[domain] = result
            return {"domain": domain, "result": result}
        if name == "synthesize":
            state.final_memo = self._build_memo(state, arguments.get("summary", ""))
            return state.final_memo
        if name == "finish":
            state.final_memo = self._build_memo(state, arguments.get("summary", ""))
            state.finished = True
            return {"finished": True, **state.final_memo}
        return {"error": f"Unknown tool '{name}'."}

    def _build_memo(self, state: OrchestrationState, summary: str) -> dict[str, Any]:
        return synthesize_flags(state.consultations, fallback_summary=summary)

    def _system_prompt(self, mode: RouteMode, task: TaskMode, selected: list[str]) -> str:
        
        availability = [
            {"domain": domain, "live": entry["live"], "description": entry["description"]}
            for domain, entry in self.registry.items()
        ]
        routing_constraint = (
            f"Manual routing allows only: {selected}."
            if mode == "manual"
            else "Auto routing may consult any registered domain."
        )
        return ORCHESTRATOR_SYSTEM.format(
            task=task,
            routing_constraint=routing_constraint,
            registry_json=json.dumps(availability, ensure_ascii=False),
        )

    @staticmethod
    def _input_prompt(contract: str, question: str | None, task: TaskMode) -> str:
        body_parts: list[str] = []
        if question:
            body_parts.append(f"User question:\n{question}")
        if contract:
            body_parts.append(f"Contract:\n{contract}")
        return ORCHESTRATOR_USER.format(
            task=task,
            body="\n\n".join(body_parts),
        )
