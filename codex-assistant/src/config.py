from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


CONFIG_ROOT = Path("/config").resolve()
DATA_ROOT = Path("/data").resolve()
BACKUP_ROOT = CONFIG_ROOT / ".codex-backups"
AUDIT_LOG_PATH = DATA_ROOT / "audit.log"

MAX_FILE_SIZE_BYTES = 512 * 1024
MAX_AI_FILE_CONTEXT_BYTES = 64 * 1024
MAX_APPLY_OPERATIONS = 10
MAX_DIFF_CHARS_HARD_LIMIT = 200_000
MAX_SERVICE_CALLS_HARD_LIMIT = 10
DEFAULT_FORBIDDEN_TOKENS = (
    "shell_command:",
    "command_line:",
    "python_script:",
    "rest_command:",
    "service: homeassistant.restart",
    "service: hassio.host_reboot",
    "service: hassio.host_shutdown",
    "service: hassio.addon_start",
    "service: hassio.addon_stop",
    "service: hassio.addon_restart",
)
DEFAULT_ALLOWED_SERVICE_DOMAINS = (
    "light",
    "switch",
    "scene",
    "script",
    "automation",
    "input_boolean",
    "input_number",
    "media_player",
    "cover",
    "climate",
    "fan",
    "lock",
    "notify",
)


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    openai_model: str
    dry_run: bool
    log_level: str
    require_manual_approval: bool
    approval_phrase: str
    allow_dangerous_changes: bool
    forbidden_tokens: tuple[str, ...]
    max_apply_operations: int
    max_diff_chars: int
    allowed_service_domains: tuple[str, ...]
    max_service_calls: int
    include_state_context: bool
    max_state_context_entities: int


def _as_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(raw: str | None, *, default: int, minimum: int, maximum: int) -> int:
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _as_csv(raw: str | None, *, default: tuple[str, ...]) -> tuple[str, ...]:
    if raw is None:
        return default
    if raw.strip().lower() in {"", "null", "none"}:
        return default
    values = tuple(part.strip() for part in raw.split(",") if part.strip())
    return values or default


def load_settings() -> Settings:
    max_apply_operations = _as_int(
        os.getenv("MAX_APPLY_OPERATIONS"),
        default=5,
        minimum=1,
        maximum=MAX_APPLY_OPERATIONS,
    )
    max_diff_chars = _as_int(
        os.getenv("MAX_DIFF_CHARS"),
        default=40_000,
        minimum=500,
        maximum=MAX_DIFF_CHARS_HARD_LIMIT,
    )
    max_service_calls = _as_int(
        os.getenv("MAX_SERVICE_CALLS"),
        default=4,
        minimum=1,
        maximum=MAX_SERVICE_CALLS_HARD_LIMIT,
    )
    max_state_context_entities = _as_int(
        os.getenv("MAX_STATE_CONTEXT_ENTITIES"),
        default=80,
        minimum=10,
        maximum=500,
    )
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini").strip() or "gpt-5-mini",
        dry_run=_as_bool(os.getenv("DRY_RUN"), default=True),
        log_level=os.getenv("LOG_LEVEL", "info").strip().lower() or "info",
        require_manual_approval=_as_bool(os.getenv("REQUIRE_MANUAL_APPROVAL"), default=True),
        approval_phrase=os.getenv("APPROVAL_PHRASE", "APPLY").strip() or "APPLY",
        allow_dangerous_changes=_as_bool(os.getenv("ALLOW_DANGEROUS_CHANGES"), default=False),
        forbidden_tokens=_as_csv(os.getenv("FORBIDDEN_TOKENS"), default=DEFAULT_FORBIDDEN_TOKENS),
        max_apply_operations=max_apply_operations,
        max_diff_chars=max_diff_chars,
        allowed_service_domains=_as_csv(
            os.getenv("ALLOWED_SERVICE_DOMAINS"),
            default=DEFAULT_ALLOWED_SERVICE_DOMAINS,
        ),
        max_service_calls=max_service_calls,
        include_state_context=_as_bool(os.getenv("INCLUDE_STATE_CONTEXT"), default=True),
        max_state_context_entities=max_state_context_entities,
    )
