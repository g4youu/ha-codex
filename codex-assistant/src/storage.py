from __future__ import annotations

import difflib
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .config import AUDIT_LOG_PATH, BACKUP_ROOT, MAX_FILE_SIZE_BYTES


class FileHashMismatchError(RuntimeError):
    """Raised when caller provided SHA-256 no longer matches file content."""


def sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_text(path: Path, max_bytes: int = MAX_FILE_SIZE_BYTES) -> str:
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(f"File is too large: {size} bytes (max {max_bytes}).")
    return path.read_text(encoding="utf-8")


def validate_yaml(content: str) -> None:
    try:
        yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc


def unified_diff(path: Path, old: str, new: str) -> str:
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff_lines = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{path.as_posix()}",
        tofile=f"b/{path.as_posix()}",
    )
    return "".join(diff_lines)


def backup_existing(path: Path, relative_path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = BACKUP_ROOT / stamp / relative_path
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup_path)
    return backup_path


def write_text_atomic(
    path: Path,
    content: str,
    *,
    expected_sha256: str | None = None,
) -> None:
    content_size = len(content.encode("utf-8"))
    if content_size > MAX_FILE_SIZE_BYTES:
        raise ValueError(f"Content is too large: {content_size} bytes (max {MAX_FILE_SIZE_BYTES}).")

    if path.exists() and expected_sha256:
        current_hash = sha256_file(path)
        if current_hash != expected_sha256:
            raise FileHashMismatchError(
                "SHA-256 mismatch. Re-read the file and retry with the latest hash."
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".{path.name}.codex.tmp"
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def append_audit(action: str, payload: dict[str, Any]) -> None:
    AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "payload": payload,
    }
    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True))
        handle.write("\n")
