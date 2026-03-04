# Codex Assistant Add-on for Home Assistant

This project is a secure starter for a Home Assistant add-on that can help generate and apply YAML changes for:

- Automations
- Scripts
- Scenes
- Dashboards (YAML mode)
- Packages

The add-on is designed around a safe workflow:

1. Generate a plan (AI proposes file updates).
2. Review diffs.
3. Apply changes through guarded write endpoints.

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
```

## Home Assistant install (custom repository)

1. Push this project to a Git repo.
2. In Home Assistant: `Settings -> Add-ons -> Add-on Store -> (...) -> Repositories`.
3. Add your repository URL.
4. Install `Codex Assistant`.
5. Configure `auth_token` (required for API access).
6. Keep `dry_run` enabled until you trust your workflow.
7. Open the add-on panel (Ingress), paste token, generate plan, review diffs, apply.

## API flow (recommended)

1. `POST /ai/plan`: describe desired outcome and files to target.
2. Review returned operations and diffs via `POST /operations/apply` with dry-run.
3. Apply for real only after review.

Core API endpoints:

- `GET /`: Ingress panel UI
- `GET /health`
- `POST /ai/plan`
- `POST /operations/apply`
- `POST /files/read`
- `POST /files/validate`
- `POST /files/write`

## Notes

- The included ingress panel is intentionally lightweight so policy enforcement remains server-side.
- For Lovelace in storage mode (`.storage`), keep writes manual or add dedicated safe handlers rather than broad file access.
- For first production use, rotate `auth_token`, keep `dry_run=true`, and only disable it after validating output.
