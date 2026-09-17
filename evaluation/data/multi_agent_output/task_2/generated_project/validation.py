import datetime
from typing import Optional


ALLOWED_PRIORITIES = {"Low", "Medium", "High"}


def validate_title(title: str) -> None:
    if title is None or not isinstance(title, str) or title.strip() == "":
        raise ValueError("Title must be non-empty.")


def validate_priority(value: str) -> None:
    if value not in ALLOWED_PRIORITIES:
        allowed = ", ".join(sorted(ALLOWED_PRIORITIES))
        raise ValueError(f"Priority must be one of: {allowed}")


def parse_due_date(due_date_str: str) -> datetime.date:
    try:
        return datetime.date.fromisoformat(due_date_str)
    except Exception:
        raise ValueError("Due date must be a valid ISO 8601 date (YYYY-MM-DD).")


def normalize_tags(tags: Optional[list[str]]) -> list[str]:
    if not tags:
        return []
    seen_lower = set()
    result: list[str] = []
    for t in tags:
        if t is None:
            continue
        s = str(t).strip()
        if s == "":
            continue
        low = s.lower()
        if low in seen_lower:
            continue
        seen_lower.add(low)
        result.append(s)
    return result
