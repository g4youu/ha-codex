#!/usr/bin/with-contenv bashio
set -euo pipefail

export LOG_LEVEL
LOG_LEVEL="$(bashio::config 'log_level')"

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

export ALLOWED_SERVICE_DOMAINS
ALLOWED_SERVICE_DOMAINS="$(bashio::config 'allowed_service_domains')"

export MAX_SERVICE_CALLS
MAX_SERVICE_CALLS="$(bashio::config 'max_service_calls')"

export INCLUDE_STATE_CONTEXT
INCLUDE_STATE_CONTEXT="$(bashio::config 'include_state_context')"

export MAX_STATE_CONTEXT_ENTITIES
MAX_STATE_CONTEXT_ENTITIES="$(bashio::config 'max_state_context_entities')"

exec uvicorn src.main:app --host 0.0.0.0 --port 8099
