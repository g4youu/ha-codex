# Changelog

## v0.4.1 - 2026-03-13
- Added local fallback mode for common Home Assistant control commands (`turn on/off`, `toggle`, entity/status checks) when OpenAI is unavailable or quota-limited.
- Added explicit execution review confirmation and optional execution PIN guard for non-dry-run chat execution.
- Added `POST /files/inspect` and panel context-byte warnings to prevent oversized context surprises.
- Added `GET /entities/suggest` and panel entity suggestions.
- Added `POST /conversation/process` for Assist-style conversation integrations.
- Replaced planner-heavy panel with a compact chat-only UI and collapsible advanced controls.
- Added panel release notes fed by `codex-assistant/src/static/changelog.json`.
- Added CI workflow for syntax checks on push/PR.

## v0.2.8 - 2026-03-13
- Wrapped long payload output lines in panel.

## v0.2.7 - 2026-03-13
- Improved OpenAI API error details.
- Removed unsupported fields for Responses API compatibility.

## v0.2.6 - 2026-03-13
- Truncated oversized context files for AI planning instead of returning 400.
- Changed default chat file context to empty.
