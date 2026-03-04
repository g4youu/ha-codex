# Codex Assistant Add-on for Home Assistant

This project is a secure starter for a Home Assistant add-on that works as a general Home Assistant assistant.

It can chat to:

- Propose and run allowed Home Assistant service calls
- Generate and apply YAML changes for automations, scripts, scenes, dashboards (YAML mode), and packages

The add-on supports two safe workflows:

1. Chat workflow:
   - Ask for tasks in plain language.
   - Review proposed service calls/file edits.
   - Execute only with guardrails (dry-run + approval phrase).

2. File planning workflow:
   - Generate a YAML plan (AI proposes file updates).
   - Review diffs.
   - Apply changes through guarded write endpoints.

It includes an ingress panel at `/` so you can run this flow directly in Home Assistant.

## Why this is safer

- Path allowlist (only specific Home Assistant YAML targets under `/config`)
- No absolute paths, no path traversal
- YAML validation before write
- Optional global dry-run mode (on by default)
- SHA-256 precondition checks to prevent blind overwrite
- Automatic backups under `/config/.codex-backups/...`
- JSONL audit log in `/data/audit.log`
- Token-based API auth for non-health endpoints
- Forbidden token policy (blocks dangerous domains/services by default)
- Manual approval phrase gate for non-dry-run writes
- Max operations and max diff size limits
- Service-domain allowlist for runtime Home Assistant actions

## Repository layout

- `repository.yaml`: Home Assistant add-on repository metadata
- `codex-assistant/`: add-on bundle
- `codex-assistant/src/`: FastAPI service

## Local development

From this workspace:

```bash
cd "codex-assistant"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8099
```

Set env vars for local testing:

```bash
export AUTH_TOKEN="change-me"
export DRY_RUN="true"
export OPENAI_API_KEY=""
export OPENAI_MODEL="gpt-5-mini"
export REQUIRE_MANUAL_APPROVAL="true"
export APPROVAL_PHRASE="APPLY"
export ALLOW_DANGEROUS_CHANGES="false"
export FORBIDDEN_TOKENS="shell_command:,command_line:,python_script:,rest_command:,service: homeassistant.restart,service: hassio.host_reboot,service: hassio.host_shutdown"
export MAX_APPLY_OPERATIONS="5"
export MAX_DIFF_CHARS="40000"
export ALLOWED_SERVICE_DOMAINS="light,switch,scene,script,automation,input_boolean,input_number,media_player,cover,climate,fan,lock,notify"
export MAX_SERVICE_CALLS="4"
export INCLUDE_STATE_CONTEXT="true"
export MAX_STATE_CONTEXT_ENTITIES="80"
```

## Home Assistant install (custom repository)

1. Push this project to a Git repo.
2. In Home Assistant: `Settings -> Add-ons -> Add-on Store -> (...) -> Repositories`.
3. Add your repository URL.
4. Install `Codex Assistant`.
5. Configure `auth_token` (required for API access).
6. Keep `dry_run` enabled until you trust your workflow.
7. Open the add-on panel (Ingress), paste token, and start with chat in dry-run mode.

## API flow (recommended)

1. `POST /chat`: ask in plain language and review proposed service calls/file edits.
2. Keep `dry_run=true` while validating outputs and diffs.
3. Execute for real only after review and with `approval_phrase`.

Core API endpoints:

- `GET /`: Ingress panel UI
- `GET /health`
- `POST /chat`
- `POST /ai/plan`
- `POST /operations/apply`
- `POST /files/read`
- `POST /files/validate`
- `POST /files/write`

## Notes

- The included ingress panel is intentionally lightweight so policy enforcement remains server-side.
- For Lovelace in storage mode (`.storage`), keep writes manual or add dedicated safe handlers rather than broad file access.
- For first production use, rotate `auth_token`, keep `dry_run=true`, and only disable it after validating output.
- Keep dangerous domains (`homeassistant`, `hassio`) out of `allowed_service_domains` unless you intentionally accept that risk.
