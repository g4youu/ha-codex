# Codex Assistant Add-on for Home Assistant

Codex Assistant is a chat-first Home Assistant add-on focused on safe control, troubleshooting, and guided configuration changes.

## What it does

- Chat interface in Home Assistant side panel (Ingress)
- Direct Home Assistant service-control proposals (`light`, `switch`, `climate`, etc.)
- Optional immediate execution with guardrails
- Troubleshooting with live Home Assistant state context
- Safe YAML/file planning support for automations/scripts/scenes/dashboards/packages
- Local fallback for common commands when OpenAI is unavailable (for example quota/rate-limit issues)

## Safety model

- Path allowlist for writable files under `/config`
- YAML validation before writes
- Diff-size guardrails
- Dry-run mode by default
- Manual approval phrase for non-dry-run writes
- Optional execute confirmation + optional execution PIN
- Service-domain allowlist
- Automatic backups under `/config/.codex-backups`
- Audit log under `/data/audit.log`

## Add-on options

Required:
- `openai_api_key`

Important options:
- `dry_run`
- `require_manual_approval`
- `approval_phrase`
- `require_execute_confirmation`
- `execute_pin`
- `local_fallback_enabled`
- `allowed_service_domains`

## Home Assistant install

1. In Home Assistant: `Settings -> Add-ons -> Add-on Store -> (...) -> Repositories`
2. Add repository URL: `https://github.com/g4youu/ha-codex.git`
3. Install `Codex Assistant`
4. Configure `openai_api_key` in add-on options
5. Start add-on and open the side panel

## Core endpoints

- `GET /` panel UI
- `GET /health`
- `POST /chat`
- `POST /conversation/process` (Assist-style wrapper)
- `GET /entities/suggest`
- `POST /files/inspect`
- `POST /ai/plan`
- `POST /operations/apply`
- `POST /files/read`
- `POST /files/validate`
- `POST /files/write`

## Development

```bash
cd codex-assistant
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8099
```
