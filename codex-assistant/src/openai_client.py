from __future__ import annotations

import json
from typing import Any

import httpx


SYSTEM_PROMPT = """You are generating safe Home Assistant YAML file updates.
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
            {"role": "system", "content": [{"type": "input_text", "text": SYSTEM_PROMPT}]},
            {
                "role": "user",
                "content": [{"type": "input_text", "text": json.dumps(user_payload)}],
            },
        ],
        "temperature": 0.2,
        "max_output_tokens": 3000,
    }

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=60.0) as client:
        response = client.post("https://api.openai.com/v1/responses", headers=headers, json=body)
        response.raise_for_status()
        data = response.json()

    output_text = _extract_output_text(data)
    if not output_text:
        raise RuntimeError("Model returned no text output.")

    parsed = json.loads(_strip_json_fences(output_text))
    if not isinstance(parsed, dict):
        raise RuntimeError("Model output must be a JSON object.")
    return parsed
