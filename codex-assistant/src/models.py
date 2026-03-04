from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ReadFileRequest(BaseModel):
    path: str = Field(..., description="Path relative to /config.")


class ValidateFileRequest(BaseModel):
    path: str = Field(..., description="Path relative to /config.")
    content: str = Field(..., description="Proposed file content.")


class WriteFileRequest(BaseModel):
    path: str = Field(..., description="Path relative to /config.")
    content: str = Field(..., description="New file content.")
    expected_sha256: str | None = Field(
        default=None,
        description="Optional precondition hash of current file content.",
    )
    backup: bool = Field(
        default=True,
        description="Create a timestamped backup before writing.",
    )
    dry_run: bool | None = Field(
        default=None,
        description="Request dry-run for this call. True always forces dry-run.",
    )
    approval_phrase: str | None = Field(
        default=None,
        description="Manual confirmation phrase for non-dry-run writes.",
    )


class FileOperation(BaseModel):
    path: str = Field(..., description="Path relative to /config.")
    content: str = Field(..., description="Full replacement content.")
    expected_sha256: str | None = Field(default=None)
    reason: str | None = Field(default=None)


class ApplyOperationsRequest(BaseModel):
    operations: list[FileOperation] = Field(default_factory=list)
    backup: bool = Field(default=True)
    dry_run: bool | None = Field(default=None)
    approval_phrase: str | None = Field(
        default=None,
        description="Manual confirmation phrase for non-dry-run applies.",
    )


class PlanRequest(BaseModel):
    goal: str = Field(..., description="Desired Home Assistant outcome.")
    files: list[str] = Field(
        default_factory=list,
        description="Relevant target files to include as context.",
    )
    max_operations: int = Field(default=5, ge=1, le=10)
    openai_api_key: str | None = Field(
        default=None,
        description="Optional per-request OpenAI API key override.",
    )


class ServiceCallOperation(BaseModel):
    domain: str = Field(..., description="Home Assistant service domain.")
    service: str = Field(..., description="Home Assistant service name.")
    data: dict[str, Any] = Field(default_factory=dict, description="Service data payload.")
    reason: str | None = Field(default=None)


class ChatHistoryItem(BaseModel):
    role: str = Field(..., description="user or assistant")
    content: str = Field(..., description="Plain text content.")


class ChatRequest(BaseModel):
    message: str = Field(..., description="User chat message.")
    history: list[ChatHistoryItem] = Field(default_factory=list)
    files: list[str] = Field(
        default_factory=list,
        description="Optional target files for file-edit context.",
    )
    include_state_context: bool | None = Field(
        default=None,
        description="Include Home Assistant states in model context.",
    )
    entity_ids: list[str] = Field(
        default_factory=list,
        description="Optional entity IDs to fetch state context for.",
    )
    max_operations: int = Field(default=3, ge=1, le=10)
    max_service_calls: int = Field(default=3, ge=1, le=10)
    openai_api_key: str | None = Field(
        default=None,
        description="Optional per-request OpenAI API key override.",
    )
    execute: bool = Field(
        default=False,
        description="Execute proposed actions immediately (subject to policy and dry-run).",
    )
    backup: bool = Field(default=True)
    dry_run: bool | None = Field(default=None)
    approval_phrase: str | None = Field(default=None)


class VerifyOpenAIKeyRequest(BaseModel):
    openai_api_key: str | None = Field(
        default=None,
        description="Optional OpenAI API key override to verify.",
    )
