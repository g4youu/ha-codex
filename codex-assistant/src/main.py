from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import MAX_AI_FILE_CONTEXT_BYTES, load_settings
from .home_assistant_api import call_service, get_states
from .models import (
    ApplyOperationsRequest,
    ChatRequest,
    ConversationProcessRequest,
    FileOperation,
    InspectFilesRequest,
    PlanRequest,
    ReadFileRequest,
    ServiceCallOperation,
    ValidateFileRequest,
    WriteFileRequest,
)
from .openai_client import OpenAIAPIError, generate_chat_result, generate_plan
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
SERVICE_TOKEN_PATTERN = re.compile(r"^[a-z0-9_]+$")
ENTITY_ID_PATTERN = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")

app = FastAPI(
    title="Codex Assistant",
    version="0.4.1",
    description="Safe Home Assistant assistant API for chat, service actions, and YAML edits.",
)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


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
    size = path.stat().st_size
    if size <= MAX_AI_FILE_CONTEXT_BYTES:
        return read_text(path, max_bytes=MAX_AI_FILE_CONTEXT_BYTES)

    with path.open("rb") as handle:
        raw = handle.read(MAX_AI_FILE_CONTEXT_BYTES)
    truncated = raw.decode("utf-8", errors="replace")
    LOGGER.warning(
        "Truncating context file for AI planning: %s (%s bytes > %s bytes)",
        path.as_posix(),
        size,
        MAX_AI_FILE_CONTEXT_BYTES,
    )
    return (
        f"{truncated}\n\n"
        f"# [Context truncated: {path.as_posix()} is {size} bytes; "
        f"sent first {MAX_AI_FILE_CONTEXT_BYTES} bytes.]"
    )


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


def _enforce_execute_confirmation_or_412(
    *,
    execute: bool,
    dry_run: bool,
    confirm_execute: bool,
    execute_pin: str | None,
    action_count: int,
) -> None:
    if not execute or dry_run or action_count <= 0:
        return
    if SETTINGS.require_execute_confirmation and not confirm_execute:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail=(
                "Execution confirmation is required. "
                "Set confirm_execute=true after reviewing proposed actions."
            ),
        )
    if SETTINGS.execute_pin and (execute_pin or "").strip() != SETTINGS.execute_pin:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="Execution PIN is required or invalid.",
        )


def _effective_include_state_context(request_flag: bool | None) -> bool:
    if request_flag is None:
        return SETTINGS.include_state_context
    return bool(request_flag)


def _validate_service_call_or_400(call: ServiceCallOperation) -> tuple[str, str, dict[str, Any]]:
    domain = call.domain.strip().lower()
    service = call.service.strip().lower()
    if not domain or not SERVICE_TOKEN_PATTERN.fullmatch(domain):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid service domain: {call.domain!r}",
        )
    if not service or not SERVICE_TOKEN_PATTERN.fullmatch(service):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid service name: {call.service!r}",
        )

    allowed_domains = {entry.strip().lower() for entry in SETTINGS.allowed_service_domains if entry.strip()}
    if domain not in allowed_domains:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Service domain '{domain}' is not allowed. "
                f"Allowed domains: {sorted(allowed_domains)}"
            ),
        )

    payload_text = f"{domain}.{service} {json.dumps(call.data, sort_keys=True)}"
    _enforce_content_policy_or_400(payload_text)
    return domain, service, call.data


def _normalize_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in history[-12:]:
        role = (item.get("role") or "").strip().lower()
        content = (item.get("content") or "").strip()
        if role not in {"user", "assistant"}:
            continue
        if not content:
            continue
        normalized.append({"role": role, "content": content[:4000]})
    return normalized


def _chat_file_context(request: ChatRequest) -> dict[str, str]:
    context: dict[str, str] = {}
    for raw_path in request.files:
        path, relative = _resolve_or_400(raw_path)
        context[relative] = _read_for_ai_context(path)
    return context


def _chat_state_context(request: ChatRequest) -> tuple[list[dict[str, Any]], str | None]:
    if not _effective_include_state_context(request.include_state_context):
        return [], None
    entity_ids = [item.strip() for item in request.entity_ids if item.strip()]
    try:
        states = get_states(
            entity_ids=entity_ids or None,
            limit=SETTINGS.max_state_context_entities,
        )
        return states, None
    except Exception as exc:
        LOGGER.warning("Unable to read Home Assistant states for chat context: %s", exc)
        return [], f"State context unavailable: {exc}"


def _configured_openai_api_key() -> str:
    if SETTINGS.openai_api_key:
        return SETTINGS.openai_api_key
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="openai_api_key is not configured in add-on options.",
    )


def _openai_http_status(exc: OpenAIAPIError) -> int:
    if exc.status_code in {400, 401, 403, 429}:
        return exc.status_code
    return status.HTTP_502_BAD_GATEWAY


def _friendly_openai_error(exc: OpenAIAPIError) -> str:
    code = (exc.error_code or "").strip().lower()
    detail = exc.detail.strip()
    if code == "insufficient_quota" or "exceeded your current quota" in detail.lower():
        return (
            "OpenAI API quota is exhausted for this key/project. "
            "Add billing/credits in OpenAI Platform, then retry."
        )
    if code == "invalid_api_key":
        return "OpenAI API key is invalid. Update openai_api_key in add-on options and restart the add-on."
    if code in {"rate_limit_exceeded", "requests", "tokens"} or exc.status_code == 429:
        return "OpenAI rate limit reached. Wait a moment and retry, or reduce request frequency."
    if exc.status_code == 401:
        return "OpenAI authentication failed. Verify openai_api_key in add-on options."
    return f"OpenAI request failed: {detail}"


def _normalized_text(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return re.sub(r"\s+", " ", normalized).strip()


def _clean_entity_hint(raw: str) -> str:
    hint = raw.strip().lower().strip(" .,!?:;\"'`[]{}()")
    hint = re.sub(r"\b(?:the|a|an|my|please)\b", " ", hint)
    return re.sub(r"\s+", " ", hint).strip()


def _resolve_entity_id_from_hint(hint: str, states: list[dict[str, Any]]) -> str | None:
    cleaned = _clean_entity_hint(hint)
    if not cleaned:
        return None

    if ENTITY_ID_PATTERN.fullmatch(cleaned):
        if not states:
            return cleaned
        known_ids = {str(item.get("entity_id", "")).lower() for item in states}
        if cleaned in known_ids:
            return cleaned

    hint_norm = _normalized_text(cleaned)
    if not hint_norm:
        return None

    best_score = -1
    best_entity: str | None = None
    hint_tokens = hint_norm.split()
    for state in states:
        entity_id = str(state.get("entity_id") or "").lower().strip()
        if not entity_id:
            continue
        friendly = str(state.get("friendly_name") or "")
        entity_norm = _normalized_text(entity_id.replace(".", " ").replace("_", " "))
        friendly_norm = _normalized_text(friendly)

        score = 0
        if cleaned == entity_id:
            score = 120
        elif hint_norm == friendly_norm and friendly_norm:
            score = 110
        elif hint_norm == entity_norm and entity_norm:
            score = 100
        elif friendly_norm and hint_norm in friendly_norm:
            score = 80
        elif hint_norm in entity_norm:
            score = 70
        elif hint_tokens and friendly_norm and all(token in friendly_norm for token in hint_tokens):
            score = 60
        elif hint_tokens and entity_norm and all(token in entity_norm for token in hint_tokens):
            score = 50

        if score > best_score:
            best_score = score
            best_entity = entity_id

    if best_score >= 60:
        return best_entity
    return None


def _local_entity_overview(states: list[dict[str, Any]]) -> str:
    if not states:
        return "I could not read Home Assistant entities right now."
    sample = [str(item.get("entity_id", "")) for item in states[:15] if item.get("entity_id")]
    listed = ", ".join(sample)
    total = len(states)
    if total > len(sample):
        return f"I can see {total} entities. Sample: {listed} ..."
    return f"I can see {total} entities: {listed}"


def _local_state_response(message: str, states: list[dict[str, Any]]) -> str | None:
    lowered = message.lower()
    if re.search(r"\b(check|list|show)\b.*\b(entities|entity|devices|states)\b", lowered):
        return _local_entity_overview(states)

    state_match = re.search(r"\b(?:status|state)\s+(?:of\s+)?(.+)$", lowered)
    if not state_match:
        return None

    entity_hint = state_match.group(1)
    entity_id = _resolve_entity_id_from_hint(entity_hint, states)
    if not entity_id:
        return "I could not match that entity. Try an explicit entity_id like light.kitchen."

    for item in states:
        if str(item.get("entity_id", "")).lower() == entity_id:
            friendly = item.get("friendly_name")
            state_value = item.get("state")
            label = f" ({friendly})" if friendly else ""
            return f"{entity_id}{label} is currently '{state_value}'."
    return f"I found {entity_id}, but its state is unavailable right now."


def _local_service_response(
    *,
    message: str,
    states: list[dict[str, Any]],
    max_service_calls: int,
) -> dict[str, Any] | None:
    if max_service_calls < 1:
        return None

    command_patterns = [
        (re.compile(r"^\s*(?:please\s+)?(?:turn|switch)\s+on\s+(.+)$", re.IGNORECASE), "turn_on"),
        (re.compile(r"^\s*(?:please\s+)?(?:turn|switch)\s+off\s+(.+)$", re.IGNORECASE), "turn_off"),
        (re.compile(r"^\s*(?:please\s+)?toggle\s+(.+)$", re.IGNORECASE), "toggle"),
    ]

    matched_service = None
    matched_hint = None
    for pattern, service in command_patterns:
        match = pattern.search(message)
        if match:
            matched_service = service
            matched_hint = match.group(1)
            break

    if not matched_service or not matched_hint:
        return None

    entity_id = _resolve_entity_id_from_hint(matched_hint, states)
    if not entity_id:
        cleaned_hint = _clean_entity_hint(matched_hint)
        if ENTITY_ID_PATTERN.fullmatch(cleaned_hint):
            entity_id = cleaned_hint
        else:
            return {
                "assistant_message": (
                    "I understood the command but could not match an entity. "
                    "Use an explicit entity_id like light.kitchen."
                ),
                "service_calls": [],
                "file_operations": [],
                "source": "local_fallback",
            }

    domain = entity_id.split(".", 1)[0]
    allowed_domains = {entry.strip().lower() for entry in SETTINGS.allowed_service_domains if entry.strip()}
    if domain not in allowed_domains:
        return {
            "assistant_message": (
                f"I matched {entity_id}, but domain '{domain}' is not allowed by add-on policy."
            ),
            "service_calls": [],
            "file_operations": [],
            "source": "local_fallback",
        }

    return {
        "assistant_message": f"Prepared {domain}.{matched_service} for {entity_id}.",
        "service_calls": [
            {
                "domain": domain,
                "service": matched_service,
                "data": {"entity_id": entity_id},
                "reason": f"User asked to {matched_service.replace('_', ' ')} {entity_id}.",
            }
        ],
        "file_operations": [],
        "source": "local_fallback",
    }


def _build_local_chat_result(
    *,
    message: str,
    existing_states: list[dict[str, Any]],
    max_service_calls: int,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not SETTINGS.local_fallback_enabled:
        return None, existing_states

    states = list(existing_states)
    if not states:
        try:
            states = get_states(limit=SETTINGS.max_state_context_entities)
        except Exception:
            states = []

    local_service = _local_service_response(
        message=message,
        states=states,
        max_service_calls=max_service_calls,
    )
    if local_service:
        return local_service, states

    state_text = _local_state_response(message, states)
    if state_text:
        return {
            "assistant_message": state_text,
            "service_calls": [],
            "file_operations": [],
            "source": "local_fallback",
        }, states

    return None, states


def _prepare_model_operations(
    *,
    model_result: dict[str, Any],
    requested_max_ops: int,
    requested_max_service_calls: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    assistant_message = str(model_result.get("assistant_message", "")).strip()
    if not assistant_message:
        assistant_message = "I prepared a safe plan based on your request."

    raw_file_operations = model_result.get("file_operations", [])
    if not isinstance(raw_file_operations, list):
        raw_file_operations = []
    raw_service_calls = model_result.get("service_calls", [])
    if not isinstance(raw_service_calls, list):
        raw_service_calls = []

    prepared_file_ops: list[dict[str, Any]] = []
    for item in raw_file_operations[:requested_max_ops]:
        if not isinstance(item, dict):
            continue
        try:
            op = FileOperation.model_validate(item)
            path, relative = _resolve_or_400(op.path)
            if _is_yaml(path):
                validate_yaml(op.content)
            _enforce_content_policy_or_400(op.content)
            old_content = _read_existing(path)
            diff = unified_diff(path, old_content, op.content)
            _enforce_diff_size_or_400(diff)
        except Exception:
            continue
        prepared_file_ops.append(
            {
                "path_obj": path,
                "path": relative,
                "content": op.content,
                "expected_sha256": op.expected_sha256,
                "reason": op.reason,
                "diff": diff,
            }
        )

    prepared_service_calls: list[dict[str, Any]] = []
    for item in raw_service_calls[:requested_max_service_calls]:
        if not isinstance(item, dict):
            continue
        try:
            call = ServiceCallOperation.model_validate(item)
            domain, service, data = _validate_service_call_or_400(call)
        except Exception:
            continue
        prepared_service_calls.append(
            {
                "domain": domain,
                "service": service,
                "data": data,
                "reason": call.reason,
            }
        )

    return prepared_file_ops, prepared_service_calls, assistant_message


def _run_chat(request: ChatRequest) -> dict[str, Any]:
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="message is required.")
    _enforce_goal_policy_or_400(message)

    requested_max_ops = min(request.max_operations, SETTINGS.max_apply_operations)
    requested_max_service_calls = min(request.max_service_calls, SETTINGS.max_service_calls)
    history = _normalize_history(
        [{"role": item.role, "content": item.content} for item in request.history]
    )
    file_context = _chat_file_context(request)
    state_context, state_warning = _chat_state_context(request)

    model_result: dict[str, Any] | None = None
    model_source = "openai"

    local_result, enriched_states = _build_local_chat_result(
        message=message,
        existing_states=state_context,
        max_service_calls=requested_max_service_calls,
    )
    if local_result:
        model_result = local_result
        model_source = "local_fallback"
        if enriched_states and not state_context:
            state_context = enriched_states

    if model_result is None:
        configured_openai_key = _configured_openai_api_key()
        try:
            model_result = generate_chat_result(
                api_key=configured_openai_key,
                model=SETTINGS.openai_model,
                message=message,
                history=history,
                file_context=file_context,
                state_context=state_context,
                allowed_service_domains=SETTINGS.allowed_service_domains,
                max_file_operations=requested_max_ops,
                max_service_calls=requested_max_service_calls,
            )
        except OpenAIAPIError as exc:
            LOGGER.warning("OpenAI chat request failed: %s", exc.detail)
            fallback_result, _ = _build_local_chat_result(
                message=message,
                existing_states=state_context,
                max_service_calls=requested_max_service_calls,
            )
            if fallback_result:
                model_result = fallback_result
                model_source = "local_fallback"
                warning = f"OpenAI unavailable ({_friendly_openai_error(exc)}); used local fallback."
                state_warning = f"{state_warning} | {warning}" if state_warning else warning
            else:
                raise HTTPException(
                    status_code=_openai_http_status(exc),
                    detail=_friendly_openai_error(exc),
                ) from exc
        except Exception as exc:
            LOGGER.exception("Failed to generate chat response")
            fallback_result, _ = _build_local_chat_result(
                message=message,
                existing_states=state_context,
                max_service_calls=requested_max_service_calls,
            )
            if fallback_result:
                model_result = fallback_result
                model_source = "local_fallback"
                warning = "OpenAI request failed unexpectedly; used local fallback."
                state_warning = f"{state_warning} | {warning}" if state_warning else warning
            else:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Chat generation failed: {exc}",
                ) from exc

    prepared_file_ops, prepared_service_calls, assistant_message = _prepare_model_operations(
        model_result=model_result,
        requested_max_ops=requested_max_ops,
        requested_max_service_calls=requested_max_service_calls,
    )

    dry_run = _effective_dry_run(request.dry_run)
    execution_results: dict[str, Any] | None = None
    executed = False

    if request.execute:
        action_count = len(prepared_file_ops) + len(prepared_service_calls)
        _enforce_manual_approval_or_412(request.approval_phrase, dry_run)
        _enforce_execute_confirmation_or_412(
            execute=request.execute,
            dry_run=dry_run,
            confirm_execute=request.confirm_execute,
            execute_pin=request.execute_pin,
            action_count=action_count,
        )

        file_results: list[dict[str, Any]] = []
        for entry in prepared_file_ops:
            if dry_run:
                file_results.append(
                    {
                        "path": entry["path"],
                        "reason": entry["reason"],
                        "applied": False,
                        "dry_run": True,
                        "proposed_sha256": sha256_text(entry["content"]),
                        "diff": entry["diff"],
                    }
                )
                continue

            backup_path = None
            if request.backup:
                backup_path = backup_existing(entry["path_obj"], Path(entry["path"]))
            try:
                write_text_atomic(
                    entry["path_obj"],
                    entry["content"],
                    expected_sha256=entry["expected_sha256"],
                )
            except FileHashMismatchError as exc:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
            file_results.append(
                {
                    "path": entry["path"],
                    "reason": entry["reason"],
                    "applied": True,
                    "dry_run": False,
                    "backup_path": backup_path.as_posix() if backup_path else None,
                    "sha256": sha256_file(entry["path_obj"]),
                    "diff": entry["diff"],
                }
            )

        service_results: list[dict[str, Any]] = []
        for entry in prepared_service_calls:
            if dry_run:
                service_results.append(
                    {
                        "domain": entry["domain"],
                        "service": entry["service"],
                        "data": entry["data"],
                        "reason": entry["reason"],
                        "applied": False,
                        "dry_run": True,
                    }
                )
                continue
            try:
                result = call_service(entry["domain"], entry["service"], entry["data"])
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Service call failed for {entry['domain']}.{entry['service']}: {exc}",
                ) from exc
            service_results.append(
                {
                    "domain": entry["domain"],
                    "service": entry["service"],
                    "data": entry["data"],
                    "reason": entry["reason"],
                    "applied": True,
                    "dry_run": False,
                    "result": result,
                }
            )

        execution_results = {
            "file_operations": file_results,
            "service_calls": service_results,
        }
        executed = not dry_run
        append_audit(
            action="chat_execute",
            payload={
                "dry_run": dry_run,
                "file_operations": len(prepared_file_ops),
                "service_calls": len(prepared_service_calls),
            },
        )

    append_audit(
        action="chat",
        payload={
            "message_length": len(message),
            "returned_file_operations": len(prepared_file_ops),
            "returned_service_calls": len(prepared_service_calls),
            "execute_requested": request.execute,
            "dry_run": dry_run,
            "source": model_source,
        },
    )

    return {
        "model": SETTINGS.openai_model,
        "source": model_source,
        "assistant_message": assistant_message,
        "state_warning": state_warning,
        "dry_run": dry_run,
        "execute_requested": request.execute,
        "executed": executed,
        "file_operations": [
            {
                "path": entry["path"],
                "reason": entry["reason"],
                "content": entry["content"],
                "diff": entry["diff"],
            }
            for entry in prepared_file_ops
        ],
        "service_calls": [
            {
                "domain": entry["domain"],
                "service": entry["service"],
                "data": entry["data"],
                "reason": entry["reason"],
            }
            for entry in prepared_service_calls
        ],
        "execution_results": execution_results,
    }


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
        "openai_key_configured": bool(SETTINGS.openai_api_key),
        "model": SETTINGS.openai_model,
        "require_manual_approval": SETTINGS.require_manual_approval,
        "require_execute_confirmation": SETTINGS.require_execute_confirmation,
        "execute_pin_configured": bool(SETTINGS.execute_pin),
        "local_fallback_enabled": SETTINGS.local_fallback_enabled,
        "max_apply_operations": SETTINGS.max_apply_operations,
        "max_diff_chars": SETTINGS.max_diff_chars,
        "allow_dangerous_changes": SETTINGS.allow_dangerous_changes,
        "allowed_service_domains": list(SETTINGS.allowed_service_domains),
        "max_service_calls": SETTINGS.max_service_calls,
        "include_state_context": SETTINGS.include_state_context,
        "max_ai_file_context_bytes": MAX_AI_FILE_CONTEXT_BYTES,
    }


@app.get("/entities/suggest")
def entities_suggest(limit: int = Query(default=120, ge=1, le=500)) -> dict[str, Any]:
    try:
        states = get_states(limit=limit)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Unable to read entities from Home Assistant: {exc}",
        ) from exc

    entities = [
        {
            "entity_id": item.get("entity_id"),
            "friendly_name": item.get("friendly_name"),
            "state": item.get("state"),
        }
        for item in states
        if item.get("entity_id")
    ]
    return {"entities": entities}


@app.post("/files/inspect")
def inspect_files(request: InspectFilesRequest) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    total_included_bytes = 0

    for raw in request.files:
        raw_path = (raw or "").strip()
        if not raw_path:
            continue
        try:
            path, relative = _resolve_or_400(raw_path)
        except HTTPException as exc:
            entries.append(
                {
                    "path": raw_path,
                    "exists": False,
                    "size_bytes": 0,
                    "included_bytes": 0,
                    "truncated": False,
                    "error": str(exc.detail),
                }
            )
            continue

        exists = path.exists()
        size_bytes = path.stat().st_size if exists else 0
        included_bytes = min(size_bytes, MAX_AI_FILE_CONTEXT_BYTES)
        truncated = size_bytes > MAX_AI_FILE_CONTEXT_BYTES
        total_included_bytes += included_bytes
        entries.append(
            {
                "path": relative,
                "exists": exists,
                "size_bytes": size_bytes,
                "included_bytes": included_bytes,
                "truncated": truncated,
                "error": None if exists else "File does not exist.",
            }
        )

    return {
        "max_ai_file_context_bytes": MAX_AI_FILE_CONTEXT_BYTES,
        "total_included_bytes": total_included_bytes,
        "files": entries,
    }


@app.post("/files/read")
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


@app.post("/files/validate")
def validate_file(request: ValidateFileRequest) -> dict[str, Any]:
    path, relative = _resolve_or_400(request.path)
    if _is_yaml(path):
        validate_yaml(request.content)
    _enforce_content_policy_or_400(request.content)
    return {
        "path": relative,
        "valid": True,
    }


@app.post("/files/write")
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


@app.post("/operations/apply")
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


@app.post("/ai/plan")
def ai_plan(request: PlanRequest) -> dict[str, Any]:
    configured_openai_key = _configured_openai_api_key()
    _enforce_goal_policy_or_400(request.goal)
    requested_max_ops = min(request.max_operations, SETTINGS.max_apply_operations)

    file_context: dict[str, str] = {}
    for raw_path in request.files:
        path, relative = _resolve_or_400(raw_path)
        file_context[relative] = _read_for_ai_context(path)

    try:
        model_result = generate_plan(
            api_key=configured_openai_key,
            model=SETTINGS.openai_model,
            goal=request.goal,
            file_context=file_context,
            max_operations=requested_max_ops,
        )
    except OpenAIAPIError as exc:
        raise HTTPException(
            status_code=_openai_http_status(exc),
            detail=_friendly_openai_error(exc),
        ) from exc
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


@app.post("/chat")
def chat(request: ChatRequest) -> dict[str, Any]:
    return _run_chat(request)


@app.post("/conversation/process")
def conversation_process(request: ConversationProcessRequest) -> dict[str, Any]:
    chat_request = ChatRequest(
        message=request.text,
        history=[],
        files=request.files,
        include_state_context=request.include_state_context,
        entity_ids=request.entity_ids,
        max_operations=request.max_operations,
        max_service_calls=request.max_service_calls,
        execute=request.execute,
        confirm_execute=request.confirm_execute,
        execute_pin=request.execute_pin,
        backup=True,
        dry_run=request.dry_run,
        approval_phrase=request.approval_phrase,
    )
    result = _run_chat(chat_request)
    conversation_id = request.conversation_id or str(uuid4())
    return {
        "conversation_id": conversation_id,
        "response": {
            "response_type": "action_done",
            "speech": {
                "plain": {
                    "speech": result.get("assistant_message", "Done."),
                }
            },
        },
        "actions": {
            "service_calls": result.get("service_calls", []),
            "file_operations": result.get("file_operations", []),
        },
        "raw": result,
    }
