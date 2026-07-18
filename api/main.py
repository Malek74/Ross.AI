"""FastAPI entrypoint for the Ross.AI Egyptian-law contract auditor."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import ValidationError

from api.schemas import AuditOptions, ChatRequest, DraftRequest, IntentRequest, ReviseRequest
from src.agents.orchestrator import ParalegalOrchestrator
from src.agents.registry import get_agent, list_agents
from src.contract_loader import load_contract
from src.cost_tracker import tracker

app = FastAPI(title="Ross.AI Egyptian-Law Contract Auditor", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Highlight-Count"],
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


def _parse_audit_options(options: str | None, mode: str, agents: str | None, lang: str = "en") -> AuditOptions:
    payload: dict[str, Any] = {"mode": mode, "agents": _parse_agents(agents), "lang": lang}
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


def _map_llm_error(exc: Exception) -> HTTPException | None:
    """Translate provider errors into friendly HTTP responses."""
    msg = str(exc)
    if "403" in msg and "limit" in msg.lower():
        return HTTPException(
            status_code=429,
            detail="API credit limit reached. Credits reset at the start of the next billing cycle (usually monthly). Please top up or wait for renewal.",
        )
    if "429" in msg or "rate limit" in msg.lower():
        return HTTPException(
            status_code=429,
            detail="Rate limit hit. Please wait a moment and try again.",
        )
    if "401" in msg or "unauthorized" in msg.lower():
        return HTTPException(
            status_code=401,
            detail="API key is invalid or expired. Please check your OPENROUTER_API_KEY.",
        )
    return None


def _run_orchestrator(lang: str = "en", **kwargs: Any) -> dict[str, Any]:
    try:
        return ParalegalOrchestrator().run(lang=lang, **kwargs)
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if message.startswith("Unknown domain") else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        mapped = _map_llm_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise


async def _extract_uploaded_contract(file: UploadFile) -> str:
    suffix = Path(file.filename or "").suffix or ".txt"
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded contract file is empty.")

    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(contents)
        tmp.close()  # release the handle BEFORE load_contract opens it (Windows locks otherwise)
        try:
            contract = load_contract(tmp.name)
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="Could not decode uploaded text file as UTF-8.") from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Could not extract contract text: {exc}") from exc
    finally:
        Path(tmp.name).unlink(missing_ok=True)

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
    lang: Annotated[str, Form()] = "en",
) -> dict[str, Any]:
    audit_options = _parse_audit_options(options, mode, agents, lang)
    contract_text = await _extract_uploaded_contract(file)
    return _run_orchestrator(
        contract=contract_text,
        task="audit",
        mode=audit_options.mode,
        agents=audit_options.agents,
        lang=audit_options.lang,
    )


@app.post("/chat")
def chat(request: ChatRequest) -> dict[str, Any]:
    return _run_orchestrator(
        question=request.question,
        contract=request.contract_text or "",
        task="chat",
        mode=request.mode,
        agents=request.agents,
        lang=request.lang,
        history=[t.model_dump() for t in request.history] if request.history else None,
    )


def _sse_from_events(events):
    """Wrap any ('event_type', data) generator as an SSE StreamingResponse."""
    def generate():
        try:
            for event_type, data in events:
                yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        except Exception as exc:
            msg = str(exc)
            if "403" in msg and "limit" in msg.lower():
                error = "API credit limit reached. Please top up or wait for renewal."
            elif "429" in msg or "rate" in msg.lower():
                error = "Rate limit hit. Please wait a moment and try again."
            elif "401" in msg or "unauthorized" in msg.lower():
                error = "API key is invalid or expired."
            else:
                error = msg
            yield f"event: error\ndata: {json.dumps({'detail': error}, ensure_ascii=False)}\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


def _sse_stream(kwargs: dict[str, Any]):
    return _sse_from_events(ParalegalOrchestrator().run_streaming(**kwargs))


@app.post("/audit/stream")
async def audit_contract_stream(
    file: Annotated[UploadFile, File(...)],
    options: Annotated[str | None, Form()] = None,
    mode: Annotated[str, Form()] = "auto",
    agents: Annotated[str | None, Form()] = None,
    lang: Annotated[str, Form()] = "en",
):
    audit_options = _parse_audit_options(options, mode, agents, lang)
    contract_text = await _extract_uploaded_contract(file)
    return _sse_stream({
        "contract": contract_text,
        "task": "audit",
        "mode": audit_options.mode,
        "agents": audit_options.agents,
        "lang": audit_options.lang,
    })


@app.post("/chat/stream")
def chat_stream(request: ChatRequest):
    return _sse_stream({
        "question": request.question,
        "contract": request.contract_text or "",
        "task": "chat",
        "mode": request.mode,
        "agents": request.agents,
        "lang": request.lang,
        "history": [t.model_dump() for t in request.history] if request.history else None,
    })


@app.get("/agents")
def agents() -> list[dict[str, Any]]:
    return list_agents()


def _resolve_stream_agent(domain: str, method: str):
    """Return the agent's streaming method, or raise the right HTTP error."""
    agent = get_agent(domain)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Unknown domain '{domain}'.")
    stream_fn = getattr(agent, method, None)
    if stream_fn is None:
        raise HTTPException(status_code=501, detail=f"The {domain} specialist does not support this yet.")
    return stream_fn


@app.post("/revise/stream")
def revise_stream(request: ReviseRequest):
    stream_fn = _resolve_stream_agent(request.domain, "revise_stream")
    return _sse_from_events(stream_fn(request.contract_text, request.flag_ids, lang=request.lang))


@app.post("/draft/stream")
def draft_stream(request: DraftRequest):
    stream_fn = _resolve_stream_agent(request.domain, "draft_stream")
    return _sse_from_events(stream_fn(request.contract_type, request.requirements or "", lang=request.lang))


@app.post("/revise")
def revise(request: ReviseRequest) -> dict[str, Any]:
    agent = get_agent(request.domain)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Unknown domain '{request.domain}'.")
    revise_fn = getattr(agent, "revise", None)
    if revise_fn is None:
        raise HTTPException(status_code=501, detail=f"The {request.domain} specialist does not support revise yet.")
    try:
        return revise_fn(request.contract_text, request.flag_ids, lang=request.lang)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=f"The {request.domain} specialist corpus index is not available.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        mapped = _map_llm_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise


@app.post("/draft")
def draft(request: DraftRequest) -> dict[str, Any]:
    agent = get_agent(request.domain)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Unknown domain '{request.domain}'.")
    draft_fn = getattr(agent, "draft", None)
    if draft_fn is None:
        raise HTTPException(status_code=501, detail=f"The {request.domain} specialist does not support draft yet.")
    try:
        return draft_fn(request.contract_type, request.requirements or "", lang=request.lang)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=f"The {request.domain} specialist corpus index is not available.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        mapped = _map_llm_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise


@app.get("/cost")
def cost_summary() -> dict[str, Any]:
    return tracker.summary()


@app.post("/extract")
async def extract_text(
    file: Annotated[UploadFile, File(...)],
) -> dict[str, str]:
    text = await _extract_uploaded_contract(file)
    return {"text": text}


_INTENT_PROMPT = """\
You route user requests in an Egyptian-law contract assistant. Messages may be in Arabic or English.
Output STRICT JSON only: {{"intent": "...", "domain": "..."}}

intents:
- "audit": check/review a contract for legal risks
- "revise": modify, fix, improve, or suggest changes to an EXISTING contract (e.g. "رشح تعديلات بالعقد", "fix the flagged clauses")
- "draft": create a NEW contract or new clauses from scratch
- "general": greetings, small talk, or meta questions about the assistant itself — what it is, who it is, what it can do (e.g. "what can you do", "who are you", "hi", "مرحبا", "ماذا تستطيع أن تفعل")
- "chat": a substantive legal question about Egyptian law or a submitted contract

domain: the best-fit legal domain — "civil", "commercial", "labour", or null if unclear.

Context: user has_contract={has_contract}, has_audit={has_audit}.
If has_contract is false, "revise" and "audit" are impossible — prefer "draft" or "chat"."""


@app.post("/intent")
def classify_intent(request: IntentRequest) -> dict[str, Any]:
    from src.llm_client import chat_classifier

    system = _INTENT_PROMPT.format(has_contract=request.has_contract, has_audit=request.has_audit)
    try:
        raw = chat_classifier([
            {"role": "system", "content": system},
            {"role": "user", "content": request.text[:2000]},
        ]).strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        parsed = json.loads(raw)
        intent = parsed.get("intent")
        domain = parsed.get("domain")
        if intent not in {"audit", "revise", "draft", "chat", "general"}:
            intent = None
        if domain not in {"civil", "commercial", "labour"}:
            domain = None
        return {"intent": intent, "domain": domain}
    except Exception:
        return {"intent": None, "domain": None}


_SEVERITY_COLORS = {
    "high": (0.86, 0.15, 0.15),
    "medium": (0.96, 0.62, 0.04),
    "low": (0.23, 0.51, 0.96),
}

_AR_NOISE = None  # compiled lazily


def _norm_ar(word: str) -> str:
    """Normalize an Arabic/Latin word for fuzzy matching across PDF encodings."""
    import re
    import unicodedata

    global _AR_NOISE
    if _AR_NOISE is None:
        _AR_NOISE = re.compile(r"[ً-ْٰـ]")
    w = unicodedata.normalize("NFKC", word)
    w = _AR_NOISE.sub("", w)
    for src, dst in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ٱ", "ا"), ("ى", "ي"), ("ة", "ه")):
        w = w.replace(src, dst)
    return "".join(c for c in w if c.isalnum() or c == "%").lower()


def _find_span_rects(page, span: str):
    """Locate an evidence span on a page by fuzzy word-bag matching; return word rects."""
    from collections import Counter

    span_words = [_norm_ar(w) for w in span.split()]
    span_words = [w for w in span_words if w]
    if not span_words:
        return []
    words = page.get_text("words")
    if not words:
        return []
    page_norms = [_norm_ar(w[4]) for w in words]
    n = len(span_words)
    span_counter = Counter(span_words)
    best_ratio, best_range = 0.0, None
    for i in range(max(1, len(page_norms) - n + 1)):
        window = page_norms[i : i + n]
        matches = sum((Counter(window) & span_counter).values())
        ratio = matches / n
        if ratio > best_ratio:
            best_ratio, best_range = ratio, (i, min(i + n, len(words)))
    if best_ratio >= 0.55 and best_range:
        import pymupdf
        return [pymupdf.Rect(words[k][:4]) for k in range(best_range[0], best_range[1])]
    return []


@app.post("/highlight")
async def highlight_pdf(
    file: Annotated[UploadFile, File(...)],
    flags: Annotated[str, Form()],
) -> Response:
    """Return the original PDF with evidence spans highlighted, color-coded by severity."""
    import pymupdf

    try:
        items = json.loads(flags)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="flags must be valid JSON.") from exc

    contents = await file.read()
    try:
        doc = pymupdf.open(stream=contents, filetype="pdf")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not open PDF: {exc}") from exc

    total = 0
    for item in items:
        span = (item.get("evidence_span") or "").strip()
        if not span:
            continue
        color = _SEVERITY_COLORS.get(str(item.get("severity") or "medium").lower(), _SEVERITY_COLORS["medium"])
        words = span.split()
        needles = [span]
        for n in (10, 6, 4):
            if len(words) > n:
                needles.append(" ".join(words[:n]))
        for page in doc:
            quads = []
            for needle in needles:
                quads = page.search_for(needle, quads=True)
                if quads:
                    break
            if not quads:
                # exact search failed (ligatures / presentation forms) — fuzzy word match
                rects = _find_span_rects(page, span)
                if rects:
                    annot = page.add_highlight_annot(rects)
                    annot.set_colors(stroke=color)
                    annot.update()
                    total += 1
                    break
                continue
            annot = page.add_highlight_annot(quads)
            annot.set_colors(stroke=color)
            annot.update()
            total += 1
            break

    out = doc.tobytes()
    doc.close()
    return Response(
        content=out,
        media_type="application/pdf",
        headers={"X-Highlight-Count": str(total)},
    )


@app.get("/export/{doc_id}")
def export_document(doc_id: str) -> None:
    raise HTTPException(status_code=501, detail=f"Export is not implemented yet for document '{doc_id}'.")
