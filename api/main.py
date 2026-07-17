"""FastAPI entrypoint for the Ross.AI Egyptian-law contract auditor."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from api.schemas import AuditOptions, ChatRequest, DraftRequest, ReviseRequest
from src.agents.orchestrator import ParalegalOrchestrator
from src.agents.registry import get_agent, list_agents
from src.contract_loader import load_contract

app = FastAPI(title="Ross.AI Egyptian-Law Contract Auditor", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _parse_agents(value: str | None) -> list[str] | None:
    if value is None or not value.strip():
        return None
    raw = value.strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return [part.strip() for part in raw.split(",") if part.strip()]
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise HTTPException(status_code=422, detail="agents must be a JSON list of strings or a comma-separated string.")
    return parsed


def _parse_audit_options(options: str | None, mode: str, agents: str | None) -> AuditOptions:
    payload: dict[str, Any] = {"mode": mode, "agents": _parse_agents(agents)}
    if options:
        try:
            option_payload = json.loads(options)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail="options must be valid JSON.") from exc
        if not isinstance(option_payload, dict):
            raise HTTPException(status_code=422, detail="options must be a JSON object.")
        payload.update(option_payload)
    try:
        return AuditOptions(**payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc


def _run_orchestrator(**kwargs: Any) -> dict[str, Any]:
    try:
        return ParalegalOrchestrator().run(**kwargs)
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if message.startswith("Unknown domain") else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


async def _extract_uploaded_contract(file: UploadFile) -> str:
    suffix = Path(file.filename or "").suffix or ".txt"
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded contract file is empty.")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as temp_file:
        temp_file.write(contents)
        temp_file.flush()
        try:
            contract = load_contract(temp_file.name)
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="Could not decode uploaded text file as UTF-8.") from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Could not extract contract text: {exc}") from exc
    if not contract.text.strip():
        raise HTTPException(status_code=400, detail="No text could be extracted from the uploaded contract.")
    return contract.text


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/audit")
async def audit_contract(
    file: Annotated[UploadFile, File(...)],
    options: Annotated[str | None, Form()] = None,
    mode: Annotated[str, Form()] = "auto",
    agents: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    audit_options = _parse_audit_options(options, mode, agents)
    contract_text = await _extract_uploaded_contract(file)
    return _run_orchestrator(
        contract=contract_text,
        task="audit",
        mode=audit_options.mode,
        agents=audit_options.agents,
    )


@app.post("/chat")
def chat(request: ChatRequest) -> dict[str, Any]:
    return _run_orchestrator(
        question=request.question,
        contract=request.contract_text or "",
        task="chat",
        mode=request.mode,
        agents=request.agents,
    )


@app.get("/agents")
def agents() -> list[dict[str, Any]]:
    return list_agents()


@app.post("/revise")
def revise(request: ReviseRequest) -> dict[str, Any]:
    agent = get_agent(request.domain)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Unknown domain '{request.domain}'.")
    revise_fn = getattr(agent, "revise", None)
    if revise_fn is None:
        raise HTTPException(status_code=501, detail=f"The {request.domain} specialist does not support revise yet.")
    try:
        return revise_fn(request.contract_text, request.flag_ids)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=f"The {request.domain} specialist corpus index is not available.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/draft")
def draft(request: DraftRequest) -> dict[str, Any]:
    agent = get_agent(request.domain)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Unknown domain '{request.domain}'.")
    draft_fn = getattr(agent, "draft", None)
    if draft_fn is None:
        raise HTTPException(status_code=501, detail=f"The {request.domain} specialist does not support draft yet.")
    try:
        return draft_fn(request.contract_type, request.requirements or "")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=f"The {request.domain} specialist corpus index is not available.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/export/{doc_id}")
def export_document(doc_id: str) -> None:
    raise HTTPException(status_code=501, detail=f"Export is not implemented yet for document '{doc_id}'.")
