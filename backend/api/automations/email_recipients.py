from __future__ import annotations

import json
import re

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email_recipients(value) -> list[str]:
    """Normalize one email or an email array while preserving input order.

    Power Automate sometimes sends an array expression as a JSON-encoded string
    instead of a native JSON array. Accept both representations.
    """
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                decoded = json.loads(stripped)
            except json.JSONDecodeError:
                decoded = value
            if isinstance(decoded, list):
                value = decoded
    raw_values = value if isinstance(value, (list, tuple, set)) else [value]
    recipients: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        if raw_value is None:
            continue
        for part in re.split(r"[;,]", str(raw_value)):
            email = part.strip()
            if not email:
                continue
            if not _EMAIL_PATTERN.fullmatch(email):
                raise ValueError(f"Invalid email address: {email!r}")
            key = email.casefold()
            if key not in seen:
                seen.add(key)
                recipients.append(email)
    return recipients
