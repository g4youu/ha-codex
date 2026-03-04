from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import MAX_AI_FILE_CONTEXT_BYTES, load_settings
from .models import (
    ApplyOperationsRequest,
    PlanRequest,
    ReadFileRequest,
    ValidateFileRequest,
    WriteFileRequest,
)
from .openai_client import generate_plan
from .policy import enforce_content_policy, enforce_goal_policy
from .security import resolve_allowed_path
from .storage import (
    FileHashMismatchError,
    append_audit,
    backup_existing,
    read_text,
    sha256_file,
    sha256_text,
    unified_diff,
    validate_yaml,
    write_text_atomic,
)


SETTINGS = load_settings()
logging.basicConfig(level=SETTINGS.log_level.upper(), format="%(levelname)s %(message)s")
LOGGER = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="Codex Assistant",
    version="0.1.0",
    description="Safe, allowlisted YAML editing API for Home Assistant.",
)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def require_auth(authorization: str | None = Header(default=None)) -> None:
    token = SETTINGS.auth_token
    if not token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="auth_token is not configured in add-on options.",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )
    presented = authorization[7:].strip()
    if presented != token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token.",
        )


def _resolve_or_400(raw_path: str) -> tuple[Path, str]:
    try:
        resolved, relative = resolve_allowed_path(raw_path)
        return resolved, relative.as_posix()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _is_yaml(path: Path) -> bool:
    return path.suffix.lower() in {".yaml", ".yml"}


def _effective_dry_run(request_dry_run: bool | None) -> bool:
    return SETTINGS.dry_run or bool(request_dry_run)


def _read_for_ai_context(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return read_text(path, max_bytes=MAX_AI_FILE_CONTEXT_BYTES)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Context file too large for AI planning: {path.as_posix()} ({exc})",
        ) from exc


def _read_existing(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return read_text(path)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _enforce_content_policy_or_400(content: str) -> None:
    try:
        enforce_content_policy(
            content=content,
            forbidden_tokens=SETTINGS.forbidden_tokens,
            allow_dangerous_changes=SETTINGS.allow_dangerous_changes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _enforce_goal_policy_or_400(goal: str) -> None:
    try:
        enforce_goal_policy(
            goal=goal,
            forbidden_tokens=SETTINGS.forbidden_tokens,
            allow_dangerous_changes=SETTINGS.allow_dangerous_changes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _enforce_diff_size_or_400(diff: str) -> None:
    if len(diff) <= SETTINGS.max_diff_chars:
        return
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            f"Diff is too large ({len(diff)} chars). "
            f"Current limit is {SETTINGS.max_diff_chars}; split the change."
        ),
    )


def _enforce_manual_approval_or_412(approval_phrase: str | None, dry_run: bool) -> None:
    if dry_run or not SETTINGS.require_manual_approval:
        return
    if approval_phrase and approval_phrase.strip() == SETTINGS.approval_phrase:
        return
    raise HTTPException(
        status_code=status.HTTP_412_PRECONDITION_FAILED,
        detail=(
            "Manual approval phrase is required for write operations. "
            f"Provide approval_phrase='{SETTINGS.approval_phrase}'."
        ),
    )


@app.get("/", include_in_schema=False)
def panel() -> FileResponse:
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Panel not found.")
    return FileResponse(index_path)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "dry_run": SETTINGS.dry_run,
        "token_configured": bool(SETTINGS.auth_token),
        "model": SETTINGS.openai_model,
        "require_manual_approval": SETTINGS.require_manual_approval,
        "max_apply_operations": SETTINGS.max_apply_operations,
        "max_diff_chars": SETTINGS.max_diff_chars,
        "allow_dangerous_changes": SETTINGS.allow_dangerous_changes,
    }


@app.post("/files/read", dependencies=[Depends(require_auth)])
def read_file(request: ReadFileRequest) -> dict[str, Any]:
    path, relative = _resolve_or_400(request.path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File does not exist.")
    content = _read_existing(path)
    return {
        "path": relative,
        "sha256": sha256_file(path),
        "content": content,
    }


@app.post("/files/validate", dependencies=[Depends(require_auth)])
def validate_file(request: ValidateFileRequest) -> dict[str, Any]:
    path, relative = _resolve_or_400(request.path)
    if _is_yaml(path):
        validate_yaml(request.content)
    _enforce_content_policy_or_400(request.content)
    return {
        "path": relative,
        "valid": True,
    }


@app.post("/files/write", dependencies=[Depends(require_auth)])
def write_file(request: WriteFileRequest) -> dict[str, Any]:
    path, relative = _resolve_or_400(request.path)
    if _is_yaml(path):
        validate_yaml(request.content)
    _enforce_content_policy_or_400(request.content)

    old_content = _read_existing(path)
    diff = unified_diff(path, old_content, request.content)
    _enforce_diff_size_or_400(diff)
    dry_run = _effective_dry_run(request.dry_run)
    _enforce_manual_approval_or_412(request.approval_phrase, dry_run)

    if dry_run:
        append_audit(
            action="write_file",
            payload={"path": relative, "dry_run": True, "reason": "global/request dry-run"},
        )
        return {
            "applied": False,
            "dry_run": True,
            "path": relative,
            "diff": diff,
            "proposed_sha256": sha256_text(request.content),
        }

    backup_path = None
    if request.backup:
        backup_path = backup_existing(path, Path(relative))

    try:
        write_text_atomic(path, request.content, expected_sha256=request.expected_sha256)
    except FileHashMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    append_audit(
        action="write_file",
        payload={
            "path": relative,
            "dry_run": False,
            "backup_path": backup_path.as_posix() if backup_path else None,
        },
    )

    return {
        "applied": True,
        "dry_run": False,
        "path": relative,
        "backup_path": backup_path.as_posix() if backup_path else None,
        "sha256": sha256_file(path),
        "diff": diff,
    }


@app.post("/operations/apply", dependencies=[Depends(require_auth)])
def apply_operations(request: ApplyOperationsRequest) -> dict[str, Any]:
    operations = request.operations
    if not operations:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No operations supplied.")
    if len(operations) > SETTINGS.max_apply_operations:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Too many operations (max {SETTINGS.max_apply_operations}).",
        )

    prepared: list[dict[str, Any]] = []
    for operation in operations:
        path, relative = _resolve_or_400(operation.path)
        if _is_yaml(path):
            validate_yaml(operation.content)
        _enforce_content_policy_or_400(operation.content)
        old_content = _read_existing(path)
        diff = unified_diff(path, old_content, operation.content)
        _enforce_diff_size_or_400(diff)
        prepared.append(
            {
                "path": path,
                "relative": relative,
                "content": operation.content,
                "expected_sha256": operation.expected_sha256,
                "reason": operation.reason,
                "diff": diff,
            }
        )

    dry_run = _effective_dry_run(request.dry_run)
    _enforce_manual_approval_or_412(request.approval_phrase, dry_run)
    if dry_run:
        append_audit(
            action="apply_operations",
            payload={"count": len(prepared), "dry_run": True},
        )
        return {
            "applied": False,
            "dry_run": True,
            "results": [
                {
                    "path": entry["relative"],
                    "reason": entry["reason"],
                    "diff": entry["diff"],
                    "proposed_sha256": sha256_text(entry["content"]),
                }
                for entry in prepared
            ],
        }

    results: list[dict[str, Any]] = []
    for entry in prepared:
        backup_path = None
        if request.backup:
            backup_path = backup_existing(entry["path"], Path(entry["relative"]))
        try:
            write_text_atomic(
                entry["path"],
                entry["content"],
                expected_sha256=entry["expected_sha256"],
            )
        except FileHashMismatchError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        results.append(
            {
                "path": entry["relative"],
                "reason": entry["reason"],
                "sha256": sha256_file(entry["path"]),
                "backup_path": backup_path.as_posix() if backup_path else None,
                "diff": entry["diff"],
            }
        )

    append_audit(
        action="apply_operations",
        payload={"count": len(prepared), "dry_run": False},
    )
    return {"applied": True, "dry_run": False, "results": results}


@app.post("/ai/plan", dependencies=[Depends(require_auth)])
def ai_plan(request: PlanRequest) -> dict[str, Any]:
    if not SETTINGS.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="openai_api_key is not configured in add-on options.",
        )
    _enforce_goal_policy_or_400(request.goal)
    requested_max_ops = min(request.max_operations, SETTINGS.max_apply_operations)

    file_context: dict[str, str] = {}
    for raw_path in request.files:
        path, relative = _resolve_or_400(raw_path)
        file_context[relative] = _read_for_ai_context(path)

    try:
        model_result = generate_plan(
            api_key=SETTINGS.openai_api_key,
            model=SETTINGS.openai_model,
            goal=request.goal,
            file_context=file_context,
            max_operations=requested_max_ops,
        )
    except Exception as exc:
        LOGGER.exception("Failed to generate AI plan")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI plan generation failed: {exc}",
        ) from exc

    operations = model_result.get("operations", [])
    if not isinstance(operations, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Model output is invalid: operations must be a list.",
        )
    if len(operations) > requested_max_ops:
        operations = operations[:requested_max_ops]

    validated: list[dict[str, Any]] = []
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        raw_path = str(operation.get("path", ""))
        content = operation.get("content")
        reason = operation.get("reason")
        if not raw_path or not isinstance(content, str):
            continue

        try:
            path, relative = _resolve_or_400(raw_path)
        except HTTPException:
            continue
        if _is_yaml(path):
            try:
                validate_yaml(content)
            except ValueError:
                continue
        try:
            enforce_content_policy(
                content=content,
                forbidden_tokens=SETTINGS.forbidden_tokens,
                allow_dangerous_changes=SETTINGS.allow_dangerous_changes,
            )
        except ValueError:
            continue

        old_content = _read_existing(path)
        diff = unified_diff(path, old_content, content)
        if len(diff) > SETTINGS.max_diff_chars:
            continue
        validated.append(
            {
                "path": relative,
                "reason": reason,
                "content": content,
                "diff": diff,
            }
        )

    append_audit(
        action="ai_plan",
        payload={"requested_files": list(file_context.keys()), "returned": len(validated)},
    )
    return {
        "model": SETTINGS.openai_model,
        "max_operations": requested_max_ops,
        "operations": validated,
    }
