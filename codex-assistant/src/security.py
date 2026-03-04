from __future__ import annotations

from pathlib import Path

from .config import CONFIG_ROOT


ALLOWED_ROOT_FILES = {
    "automations.yaml",
    "scripts.yaml",
    "scenes.yaml",
    "ui-lovelace.yaml",
}
ALLOWED_DIRECTORIES = {"dashboards", "packages"}
ALLOWED_YAML_EXTENSIONS = {".yaml", ".yml"}


def resolve_allowed_path(raw_path: str) -> tuple[Path, Path]:
    candidate = Path(raw_path.strip())
    if not raw_path.strip():
        raise ValueError("Path is required.")
    if candidate.is_absolute():
        raise ValueError("Absolute paths are not allowed.")

    resolved = (CONFIG_ROOT / candidate).resolve()
    try:
        relative = resolved.relative_to(CONFIG_ROOT)
    except ValueError as exc:
        raise ValueError("Path escapes /config.") from exc

    rel_posix = relative.as_posix()
    if rel_posix in ALLOWED_ROOT_FILES:
        return resolved, relative

    if not relative.parts:
        raise ValueError("Path is not allowed.")

    top_level = relative.parts[0]
    if top_level not in ALLOWED_DIRECTORIES:
        raise ValueError(
            "Path is not in allowlist. Allowed files: automations.yaml, scripts.yaml, "
            "scenes.yaml, ui-lovelace.yaml, and YAML files under dashboards/ or packages/."
        )

    if resolved.suffix.lower() not in ALLOWED_YAML_EXTENSIONS:
        raise ValueError("Only YAML files are allowed in dashboards/ and packages/.")

    return resolved, relative
