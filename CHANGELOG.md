# Changelog

## v0.4.2 - 2026-03-13
- Fixed chat behavior so action-like requests no longer report success when zero actionable operations were generated.
- Added explicit assistant guidance when actions are only prepared (not executed) or simulated in dry-run mode.
- Added proposed/executed action counts to chat response payload for clear status tracking.
- Updated request dry-run handling so panel toggle can override global dry-run per request.
- Changed default model from `gpt-5-mini` to `gpt-5`.

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
