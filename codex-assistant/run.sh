#!/usr/bin/with-contenv bashio
set -euo pipefail

export LOG_LEVEL
LOG_LEVEL="$(bashio::config 'log_level')"

export AUTH_TOKEN
AUTH_TOKEN="$(bashio::config 'auth_token')"

export OPENAI_API_KEY
OPENAI_API_KEY="$(bashio::config 'openai_api_key')"

export OPENAI_MODEL
OPENAI_MODEL="$(bashio::config 'model')"

export DRY_RUN
DRY_RUN="$(bashio::config 'dry_run')"

export REQUIRE_MANUAL_APPROVAL
REQUIRE_MANUAL_APPROVAL="$(bashio::config 'require_manual_approval')"

export APPROVAL_PHRASE
APPROVAL_PHRASE="$(bashio::config 'approval_phrase')"

export ALLOW_DANGEROUS_CHANGES
ALLOW_DANGEROUS_CHANGES="$(bashio::config 'allow_dangerous_changes')"

export FORBIDDEN_TOKENS
FORBIDDEN_TOKENS="$(bashio::config 'forbidden_tokens')"

export MAX_APPLY_OPERATIONS
MAX_APPLY_OPERATIONS="$(bashio::config 'max_apply_operations')"

export MAX_DIFF_CHARS
MAX_DIFF_CHARS="$(bashio::config 'max_diff_chars')"

exec uvicorn src.main:app --host 0.0.0.0 --port 8099
