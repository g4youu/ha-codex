from __future__ import annotations

import json
from typing import Any

import httpx


SYSTEM_PROMPT_PLAN = """You are generating safe Home Assistant YAML file updates.
Return strict JSON with this exact top-level shape:
{"operations":[{"path":"relative/path.yaml","content":"full file content","reason":"short reason"}]}

Rules:
- Never propose paths outside /config.
- Only use these targets:
  - automations.yaml
  - scripts.yaml
  - scenes.yaml
  - ui-lovelace.yaml
  - dashboards/*.yaml
  - packages/*.yaml
- content must be complete replacement content for each file.
- Keep output concise and valid JSON. No markdown or code fences.
"""

SYSTEM_PROMPT_CHAT = """You are a general Home Assistant assistant.
You help the user achieve outcomes safely and return strict JSON only.

Return this exact top-level shape:
{
  "assistant_message": "short human-readable response",
  "file_operations": [{"path":"relative/path.yaml","content":"full file content","reason":"why"}],
  "service_calls": [{"domain":"light","service":"turn_on","data":{"entity_id":"light.kitchen"},"reason":"why"}]
}

Rules:
- Always include assistant_message.
- Never output markdown or code fences.
- file_operations must follow the same allowed path rules:
  - automations.yaml
  - scripts.yaml
  - scenes.yaml
  - ui-lovelace.yaml
  - dashboards/*.yaml
  - packages/*.yaml
- service_calls domain MUST be one of the provided allowed domains.
- Prefer proposing actions in service_calls/file_operations instead of pretending actions already happened.
- Keep responses concise and practical.
"""


def _extract_output_text(response_json: dict[str, Any]) -> str:
    direct_text = response_json.get("output_text")
    if isinstance(direct_text, str) and direct_text.strip():
        return direct_text

    chunks: list[str] = []
    for item in response_json.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks).strip()


def _strip_json_fences(text: str) -> str:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        if candidate.startswith("json"):
            candidate = candidate[4:]
    return candidate.strip()


def _request_responses_api(*, api_key: str, body: dict[str, Any]) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=60.0) as client:
        response = client.post("https://api.openai.com/v1/responses", headers=headers, json=body)
        response.raise_for_status()
        return response.json()


def _parse_json_output(data: dict[str, Any]) -> dict[str, Any]:
    output_text = _extract_output_text(data)
    if not output_text:
        raise RuntimeError("Model returned no text output.")
    parsed = json.loads(_strip_json_fences(output_text))
    if not isinstance(parsed, dict):
        raise RuntimeError("Model output must be a JSON object.")
    return parsed


def generate_plan(
    *,
    api_key: str,
    model: str,
    goal: str,
    file_context: dict[str, str],
    max_operations: int,
) -> dict[str, Any]:
    context_payload = [
        {"path": path, "content": content}
        for path, content in sorted(file_context.items())
    ]
    user_payload = {
        "goal": goal,
        "max_operations": max_operations,
        "files": context_payload,
    }

    body = {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": SYSTEM_PROMPT_PLAN}]},
            {
                "role": "user",
                "content": [{"type": "input_text", "text": json.dumps(user_payload)}],
            },
        ],
        "temperature": 0.2,
        "max_output_tokens": 3000,
    }

    data = _request_responses_api(api_key=api_key, body=body)
    return _parse_json_output(data)


def generate_chat_result(
    *,
    api_key: str,
    model: str,
    message: str,
    history: list[dict[str, str]],
    file_context: dict[str, str],
    state_context: list[dict[str, Any]],
    allowed_service_domains: tuple[str, ...],
    max_file_operations: int,
    max_service_calls: int,
) -> dict[str, Any]:
    context_payload = [
        {"path": path, "content": content}
        for path, content in sorted(file_context.items())
    ]
    user_payload = {
        "message": message,
        "history": history,
        "constraints": {
            "allowed_service_domains": list(allowed_service_domains),
            "max_file_operations": max_file_operations,
            "max_service_calls": max_service_calls,
        },
        "state_context": state_context,
        "file_context": context_payload,
    }
    body = {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": SYSTEM_PROMPT_CHAT}]},
            {
                "role": "user",
                "content": [{"type": "input_text", "text": json.dumps(user_payload)}],
            },
        ],
        "temperature": 0.2,
        "max_output_tokens": 3500,
    }
    data = _request_responses_api(api_key=api_key, body=body)
    return _parse_json_output(data)
