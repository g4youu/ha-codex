from __future__ import annotations

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
