"""Pydantic schemas for the Ross.AI API layer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RouteMode = Literal["auto", "manual"]


LangCode = Literal["en", "ar"]


class AuditOptions(BaseModel):
    mode: RouteMode = "auto"
    agents: list[str] | None = None
    lang: LangCode = "en"


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    contract_text: str | None = None
    history: list[ChatTurn] | None = None
    mode: RouteMode = "auto"
    agents: list[str] | None = None
    lang: LangCode = "en"


class ReviseRequest(BaseModel):
    contract_text: str = Field(..., min_length=1)
    domain: str = Field(..., min_length=1)
    flag_ids: list[str] | None = None
    lang: LangCode = "en"


class DraftRequest(BaseModel):
    contract_type: str = Field(..., min_length=1)
    domain: str = Field(..., min_length=1)
    requirements: str | None = None
    lang: LangCode = "en"


class IntentRequest(BaseModel):
    text: str = Field(..., min_length=1)
    has_contract: bool = False
    has_audit: bool = False


class AgentInfo(BaseModel):
    domain: str
    label: str
    live: bool
    description: str


class ErrorResponse(BaseModel):
    detail: str
