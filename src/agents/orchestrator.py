"""Goal-driven paralegal that consults domain specialists as tools."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Literal

from src.agents.classifier import classify_domains
from src.agents.registry import REGISTRY
from src.agents.synthesizer import synthesize_flags
from src.cost_tracker import tracker
from src.llm_client import create_completion, settings
from src.prompt_templates import ORCHESTRATOR_SYSTEM, ORCHESTRATOR_USER

TaskMode = Literal["audit", "chat"]
RouteMode = Literal["auto", "manual"]


@dataclass
class OrchestrationState:
    contract: str
    question: str | None
    task: TaskMode
    allowed_domains: set[str]
    lang: str = "en"
    classification: list[dict[str, Any]] = field(default_factory=list)
    consultations: dict[str, dict[str, Any]] = field(default_factory=dict)
    final_memo: dict[str, Any] | None = None
    finished: bool = False


class ParalegalOrchestrator:
    """An LLM agent whose tools are classification and domain specialists."""

    def __init__(self, registry: dict[str, dict] | None = None) -> None:
        self.registry = registry or REGISTRY
        self._state_lock = threading.Lock()

    def run(
        self,
        *,
        contract: str = "",
        question: str | None = None,
        mode: RouteMode = "auto",
        agents: list[str] | None = None,
        task: TaskMode = "audit",
        lang: str = "en",
        history: list[dict[str, str]] | None = None,
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
        state = OrchestrationState(contract, question, task, allowed, lang=lang)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt(mode, task, selected, lang)},
            {"role": "user", "content": self._input_prompt(contract, question, task, history)},
        ]

        trace: list[dict[str, Any]] = []
        final_text = ""
        repeat_count = 0
        last_tool_key = ""
        nudges = 0
        for step in range(settings.agent_max_steps):
            response = create_completion(
                model=settings.llm_model,
                messages=messages,
                tools=self._tool_schemas(mode),
                tool_choice="auto",
                temperature=0.0,
                max_tokens=2048,
                extra_body=settings.extra_body,
            )
            tracker.record(response, endpoint="orchestrator")
            message = response.choices[0].message
            if message.content:
                final_text = message.content
            messages.append(message.model_dump(exclude_none=True))
            if not message.tool_calls:
                if not state.consultations and nudges < 2:
                    nudges += 1
                    messages.append({"role": "user", "content": "You answered directly without consulting any specialist. You MUST call consult_specialist for every implicated domain, then finish. Do not answer in plain text."})
                    continue
                break

            specialist_calls = []
            other_calls = []
            for call in message.tool_calls:
                if call.function.name == "consult_specialist":
                    specialist_calls.append(call)
                else:
                    other_calls.append(call)

            for call in other_calls:
                try:
                    parsed_args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    parsed_args = {}
                tool_key = f"{call.function.name}:{parsed_args.get('domain', '')}"
                if tool_key == last_tool_key:
                    repeat_count += 1
                else:
                    repeat_count = 0
                    last_tool_key = tool_key
                if repeat_count >= 2:
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps({"error": "Repeated tool call. Call synthesize or finish now."}, ensure_ascii=False)})
                    continue
                result = self._execute_tool(call.function.name, call.function.arguments or "{}", state, mode)
                trace.append({"step": step + 1, "tool": call.function.name, "result": result})
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)})

            if specialist_calls:
                parallel_results = self._run_specialists_parallel(specialist_calls, state, mode, step)
                for call, (res, tr) in zip(specialist_calls, parallel_results):
                    trace.append(tr)
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(res, ensure_ascii=False)})

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

    def run_streaming(self, **kwargs: Any):
        """Yield (event_type, data) tuples as the orchestrator works, then yield the final result."""
        lang = kwargs.pop("lang", "en")
        contract = kwargs.get("contract", "")
        question = kwargs.get("question")
        task: TaskMode = kwargs.get("task", "audit")
        mode: RouteMode = kwargs.get("mode", "auto")
        agents = kwargs.get("agents")
        history = kwargs.get("history")

        if task == "audit" and not contract:
            raise ValueError("An audit requires contract text.")
        if task == "chat" and not question:
            raise ValueError("A chat request requires a question.")

        selected = agents or []
        unknown = [d for d in selected if d not in self.registry]
        if unknown:
            raise ValueError(f"Unknown domain(s): {', '.join(unknown)}")
        if mode == "manual" and not selected:
            raise ValueError("Manual mode requires at least one selected domain.")

        allowed = set(selected) if mode == "manual" else set(self.registry)
        state = OrchestrationState(contract, question, task, allowed, lang=lang)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt(mode, task, selected, lang)},
            {"role": "user", "content": self._input_prompt(contract, question, task, history)},
        ]

        trace: list[dict[str, Any]] = []
        final_text = ""
        repeat_count = 0
        last_tool_key = ""
        nudges = 0

        yield ("step", {"action": "thinking", "detail": "Planning analysis..."})

        for step in range(settings.agent_max_steps):
            response = create_completion(
                model=settings.llm_model,
                messages=messages,
                tools=self._tool_schemas(mode),
                tool_choice="auto",
                temperature=0.0,
                max_tokens=2048,
                extra_body=settings.extra_body,
            )
            tracker.record(response, endpoint="orchestrator")
            message = response.choices[0].message
            if message.content:
                final_text = message.content
            messages.append(message.model_dump(exclude_none=True))
            if not message.tool_calls:
                if not state.consultations and nudges < 2:
                    nudges += 1
                    messages.append({"role": "user", "content": "You answered directly without consulting any specialist. You MUST call consult_specialist for every implicated domain, then finish. Do not answer in plain text."})
                    continue
                break

            specialist_calls = []
            other_calls = []
            for call in message.tool_calls:
                if call.function.name == "consult_specialist":
                    specialist_calls.append(call)
                else:
                    other_calls.append(call)

            for call in other_calls:
                tool_name = call.function.name
                tool_args = call.function.arguments or "{}"
                try:
                    parsed_args = json.loads(tool_args)
                except json.JSONDecodeError:
                    parsed_args = {}

                tool_key = f"{tool_name}:{parsed_args.get('domain', '')}"
                if tool_key == last_tool_key:
                    repeat_count += 1
                else:
                    repeat_count = 0
                    last_tool_key = tool_key

                if repeat_count >= 2:
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps({"error": "Repeated tool call detected. You must call synthesize or finish now."}, ensure_ascii=False)})
                    continue

                step_info = self._describe_step(tool_name, parsed_args)
                yield ("step", step_info)

                result = self._execute_tool(tool_name, tool_args, state, mode)
                trace.append({"step": step + 1, "tool": tool_name, "result": result})
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)})

            if specialist_calls:
                for call in specialist_calls:
                    try:
                        parsed_args = json.loads(call.function.arguments or "{}")
                    except json.JSONDecodeError:
                        parsed_args = {}
                    yield ("step", self._describe_step("consult_specialist", parsed_args))

                parallel_results = self._run_specialists_parallel(specialist_calls, state, mode, step)
                for call, (res, tr) in zip(specialist_calls, parallel_results):
                    trace.append(tr)
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(res, ensure_ascii=False)})

            if state.finished:
                final_text = state.final_memo["summary"]
                break

        memo = state.final_memo or self._build_memo(state, final_text or "The paralegal reached its step limit.")
        result = {
            "routing": {
                "mode": mode,
                "classification": state.classification,
                "consulted": list(state.consultations),
                "stubbed": [d for d, r in state.consultations.items() if r.get("status") == "recognized_not_available"],
            },
            "task": task,
            "summary": memo["summary"],
            "flags_by_domain": memo["flags_by_domain"],
            "specialist_results": state.consultations,
            "trace": trace,
            "status": "finished" if state.finished else "step_limit_or_text_response",
        }
        yield ("done", result)

    @staticmethod
    def _describe_step(tool_name: str, args: dict) -> dict[str, str]:
        if tool_name == "classify":
            return {"action": "classify", "detail": "Detecting relevant legal domains..."}
        if tool_name == "consult_specialist":
            domain = args.get("domain", "unknown")
            reason = args.get("reason", "")
            return {"action": "consult", "detail": f"Consulting {domain} specialist", "domain": domain, "reason": reason}
        if tool_name == "synthesize":
            return {"action": "synthesize", "detail": "Merging specialist findings..."}
        if tool_name == "finish":
            return {"action": "finish", "detail": "Finalizing report..."}
        return {"action": tool_name, "detail": f"Running {tool_name}..."}

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

    def _run_specialists_parallel(
        self,
        calls: list,
        state: OrchestrationState,
        mode: RouteMode,
        step: int,
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """Execute multiple consult_specialist calls concurrently."""
        def _exec(call):
            result = self._execute_tool(call.function.name, call.function.arguments or "{}", state, mode)
            tr = {"step": step + 1, "tool": "consult_specialist", "result": result}
            return result, tr

        if len(calls) == 1:
            return [_exec(calls[0])]

        results: list[tuple[dict[str, Any], dict[str, Any]] | None] = [None] * len(calls)
        with ThreadPoolExecutor(max_workers=min(len(calls), 3)) as pool:
            futures = {pool.submit(_exec, call): i for i, call in enumerate(calls)}
            for future in as_completed(futures):
                idx = futures[future]
                results[idx] = future.result()
        return results  # type: ignore[return-value]

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
            with self._state_lock:
                if domain not in state.allowed_domains:
                    return {"error": f"Domain '{domain}' is not allowed in manual routing mode."}
                if domain in state.consultations:
                    return {"error": f"Domain '{domain}' was already consulted. Use the result already provided. Do NOT re-consult the same domain — call synthesize or finish instead."}
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
                state.consultations[domain] = {"status": "in_progress"}
            agent = entry["agent"]
            try:
                result = agent.run(state.contract, lang=state.lang) if state.task == "audit" else agent.answer(state.question or "", state.contract or None, lang=state.lang)
            except FileNotFoundError:
                result = {
                    "domain": domain,
                    "status": "recognized_not_available",
                    "message": f"The {domain} specialist's corpus index is not available.",
                }
            with self._state_lock:
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
        return synthesize_flags(state.consultations, fallback_summary=summary, lang=state.lang)

    def _system_prompt(self, mode: RouteMode, task: TaskMode, selected: list[str], lang: str = "en") -> str:
        availability = [
            {"domain": domain, "live": entry["live"], "description": entry["description"]}
            for domain, entry in self.registry.items()
        ]
        routing_constraint = (
            f"Manual routing allows only: {selected}."
            if mode == "manual"
            else "Auto routing may consult any registered domain."
        )
        lang_instruction = (
            "LANGUAGE: Respond in Arabic (العربية). Write the summary, rationale, and all user-facing text in Arabic."
            if lang == "ar"
            else "LANGUAGE: Respond in English."
        )
        return ORCHESTRATOR_SYSTEM.format(
            task=task,
            routing_constraint=routing_constraint,
            registry_json=json.dumps(availability, ensure_ascii=False),
        ) + "\n" + lang_instruction

    @staticmethod
    def _input_prompt(contract: str, question: str | None, task: TaskMode, history: list[dict[str, str]] | None = None) -> str:
        body_parts: list[str] = []
        if history:
            turns = "\n".join(f"{turn['role']}: {turn['content'][:1500]}" for turn in history[-10:])
            body_parts.append(f"Conversation so far (for context — answer only the latest question):\n{turns}")
        if question:
            body_parts.append(f"User question:\n{question}")
        if contract:
            body_parts.append(f"Contract:\n{contract}")
        return ORCHESTRATOR_USER.format(
            task=task,
            body="\n\n".join(body_parts),
        )
