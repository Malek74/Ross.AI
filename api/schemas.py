"""Pydantic schemas for the Ross.AI API layer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RouteMode = Literal["auto", "manual"]


class AuditOptions(BaseModel):
    mode: RouteMode = "auto"
    agents: list[str] | None = None


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    contract_text: str | None = None
    mode: RouteMode = "auto"
    agents: list[str] | None = None


class ReviseRequest(BaseModel):
    contract_text: str = Field(..., min_length=1)
    domain: str = Field(..., min_length=1)
    flag_ids: list[str] | None = None


class DraftRequest(BaseModel):
    contract_type: str = Field(..., min_length=1)
    domain: str = Field(..., min_length=1)
    requirements: str | None = None


class AgentInfo(BaseModel):
    domain: str
    label: str
    live: bool
    description: str


class ErrorResponse(BaseModel):
    detail: str
