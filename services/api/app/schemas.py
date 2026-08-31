from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ApprovalStatus = Literal["pending", "approved", "rejected"]
ExecutionState = Literal["not_started", "executing", "completed", "failed", "unknown"]


class ApprovalResponse(BaseModel):
    id: int
    task_type: str
    preview_content: str
    target: str
    status: ApprovalStatus
    execution_state: ExecutionState
    recipient: str | None = None
    subject: str | None = None
    title: str | None = None
    start: str | None = None
    end: str | None = None
    timezone: str | None = None
    attendees: list[str] | None = None
    calendar_id: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None
    executed_at: datetime | None = None
    result_message: str | None = None


class ApprovalDecisionResponse(BaseModel):
    approval: ApprovalResponse
    outcome: Literal[
        "sent",
        "created",
        "rejected",
        "already_sent",
        "already_created",
        "already_processing",
        "failed",
        "unknown",
    ]
    message: str
    spoken_reply: str | None = None
    spoken_language: Literal["en", "hi"] | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


class ChatResponse(BaseModel):
    reply: str
    spoken_reply: str | None = None
    spoken_ack: str | None = None
    spoken_language: Literal["en", "hi"] | None = None
    action_type: str | None = None
    approval: ApprovalResponse | None = None


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    language: Literal["en", "hi"]


class STTResponse(BaseModel):
    text: str
    language: str
    language_probability: float
    duration_seconds: float
