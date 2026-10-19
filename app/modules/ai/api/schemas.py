from __future__ import annotations

from typing import Literal
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AiContext(BaseModel):
    """The object the question is asked about; the server loads it through an authorized tool."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["project", "door", "issue"]
    id: UUID


class AiRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)
    locale: Literal["ru", "he", "en"] = "ru"
    project_id: UUID | None = None
    context: AiContext | None = None

    @field_validator("message")
    @classmethod
    def nonblank_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message cannot be blank")
        return value


class AiSource(BaseModel):
    kind: Literal["project", "door", "issue", "installer"]
    id: UUID
    label: str
    path: str


class AiStep(BaseModel):
    tool: str
    ok: bool
    ms: int


class AiReply(BaseModel):
    run_id: UUID
    answer: str
    sources: list[AiSource]
    tools_used: list[str]
    provider_requests: int
    # The answer itself never writes: business actions are proposals confirmed separately.
    read_only: Literal[True] = True
    steps: list[AiStep] = []
    proposal_ids: list[UUID] = []
    provider: Literal["openai", "mock"] = "openai"
    # Version of the company rules the answer was produced under (None when none are set).
    rules_version: int | None = None


class AiStatus(BaseModel):
    ready: bool
    reason: Literal["ready", "disabled", "missing_api_key", "missing_model"]
    tools: list[str]
    read_only: Literal[True] = True
    provider: Literal["openai", "mock"] = "openai"
    actions_enabled: bool = False
    # Nobody has verified a real model run on this installation; the UI must say so.
    real_model_verified: Literal[False] = False
    # "background": the task is queued for the AI worker and the client polls it.
    execution: Literal["inline", "background"] = "inline"
    rules_version: int | None = None
    daily_limit: int = 0
    daily_used: int = 0


class AiRules(BaseModel):
    version: int
    text: str
    updated_at: datetime | None
    updated_by: str | None


class AiRulesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=4000)


class AiCheck(BaseModel):
    ok: bool
    provider: Literal["openai", "mock"]
    model: str | None
    latency_ms: int
    code: str | None = None
    answer_preview: str | None = None


class AiTaskRequest(AiRequest):
    request_id: UUID
    conversation_id: UUID | None = None


class AiRetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class AiConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class AiProposal(BaseModel):
    id: UUID
    task_id: UUID
    conversation_id: UUID
    tool_name: str
    status: Literal["PROPOSED", "CONFIRMED", "EXECUTED", "REJECTED", "EXPIRED", "FAILED", "CONFLICT"]
    arguments: dict
    preview: dict
    expected: dict
    result: dict | None
    error_code: str | None
    expires_at: datetime
    decided_at: datetime | None
    executed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AiTask(BaseModel):
    id: UUID
    conversation_id: UUID
    request_id: UUID
    message: str
    locale: Literal["ru", "he", "en"]
    project_id: UUID | None
    context: AiContext | None = None
    status: Literal["RUNNING", "COMPLETED", "FAILED", "INTERRUPTED", "CANCELLED"]
    attempt_count: int
    reply: AiReply | None
    error_code: str | None
    proposals: list[AiProposal] = []
    created_at: datetime
    updated_at: datetime


class AiConversation(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class AiConversationPage(BaseModel):
    items: list[AiConversation]
    has_more: bool


class AiTaskPage(BaseModel):
    items: list[AiTask]
    has_more: bool
