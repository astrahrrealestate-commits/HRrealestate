"""Shape checks on a raw (verified) webhook body, independent of the typed parser: item counts and numbers.

The route compares `count_items` with what the parser produced, so items it could not read are never silently acked.
"""

import json


def count_items(body: bytes) -> int:
    """How many message/status/echo items a webhook body claims to carry (to detect items the parser dropped)."""
    try:
        data = json.loads(body)
    except (ValueError, RecursionError):
        return 0
    total = 0
    for entry in data.get("entry", []) if isinstance(data, dict) else []:
        for change in entry.get("changes", []) if isinstance(entry, dict) else []:
            value = change.get("value") if isinstance(change, dict) else None
            if isinstance(value, dict):
                total += sum(
                    len(v) for k in ("messages", "statuses", "message_echoes") if isinstance(v := value.get(k), list)
                )
    return total


def phone_number_ids(body: bytes) -> list[str]:
    try:
        data = json.loads(body)
        return [
            str(c["value"]["metadata"]["phone_number_id"])
            for e in data.get("entry", [])
            for c in e.get("changes", [])
            if isinstance(c, dict)
            and isinstance(c.get("value"), dict)
            and isinstance(c["value"].get("metadata"), dict)
            and c["value"]["metadata"].get("phone_number_id")
        ]
    except (ValueError, RecursionError, AttributeError, TypeError, KeyError):
        return []
