from __future__ import annotations

import os
from typing import Any

import httpx


SUPERVISOR_CORE_API_URL = os.getenv("SUPERVISOR_CORE_API_URL", "http://supervisor/core/api").rstrip("/")


def _supervisor_token() -> str:
    token = os.getenv("SUPERVISOR_TOKEN", "").strip()
    if token:
        return token
    token = os.getenv("HASSIO_TOKEN", "").strip()
    if token:
        return token
    raise RuntimeError("Supervisor token is unavailable in this environment.")


def _request(
    method: str,
    path: str,
    *,
    json_payload: dict[str, Any] | None = None,
    timeout_seconds: float = 15.0,
) -> Any:
    url = f"{SUPERVISOR_CORE_API_URL}{path}"
    headers = {"Authorization": f"Bearer {_supervisor_token()}"}
    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.request(method, url, headers=headers, json=json_payload)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            snippet = response.text[:240]
            raise RuntimeError(
                f"Home Assistant API error {response.status_code} for {method} {path}: {snippet}"
            ) from exc
    if not response.text.strip():
        return {}
    return response.json()


def _compact_state(state: dict[str, Any]) -> dict[str, Any]:
    attributes = state.get("attributes") or {}
    return {
        "entity_id": state.get("entity_id"),
        "state": state.get("state"),
        "friendly_name": attributes.get("friendly_name"),
        "unit": attributes.get("unit_of_measurement"),
        "device_class": attributes.get("device_class"),
        "last_changed": state.get("last_changed"),
    }


def get_states(*, entity_ids: list[str] | None = None, limit: int = 80) -> list[dict[str, Any]]:
    if entity_ids:
        collected: list[dict[str, Any]] = []
        for raw_entity in entity_ids:
            entity_id = raw_entity.strip()
            if not entity_id:
                continue
            state = _request("GET", f"/states/{entity_id}")
            if isinstance(state, dict):
                collected.append(_compact_state(state))
        return collected

    payload = _request("GET", "/states")
    if not isinstance(payload, list):
        raise RuntimeError("Invalid state response from Home Assistant API.")

    compact_states = [_compact_state(item) for item in payload if isinstance(item, dict)]
    compact_states.sort(key=lambda item: (item.get("entity_id") or ""))
    return compact_states[:limit]


def call_service(domain: str, service: str, data: dict[str, Any]) -> Any:
    return _request("POST", f"/services/{domain}/{service}", json_payload=data, timeout_seconds=25.0)
