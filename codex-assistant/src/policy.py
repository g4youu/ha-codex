from __future__ import annotations


def find_forbidden_token(text: str, forbidden_tokens: tuple[str, ...]) -> str | None:
    lowered = text.lower()
    for token in forbidden_tokens:
        if token.lower() in lowered:
            return token
    return None


def enforce_content_policy(
    *,
    content: str,
    forbidden_tokens: tuple[str, ...],
    allow_dangerous_changes: bool,
) -> None:
    if allow_dangerous_changes:
        return
    match = find_forbidden_token(content, forbidden_tokens)
    if not match:
        return
    raise ValueError(
        f"Content contains forbidden token '{match}'. "
        "Disable policy only if you explicitly accept the risk."
    )


def enforce_goal_policy(
    *,
    goal: str,
    forbidden_tokens: tuple[str, ...],
    allow_dangerous_changes: bool,
) -> None:
    if allow_dangerous_changes:
        return
    match = find_forbidden_token(goal, forbidden_tokens)
    if not match:
        return
    raise ValueError(
        f"Goal contains forbidden token '{match}'. "
        "Adjust goal or disable dangerous-change protection."
    )
