
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from dateutil import parser as date_parser

from api.automations.meeting_notes import graph
from api.automations.meeting_notes.models import FollowUpEvent

_LOG = logging.getLogger(__name__)

_DEFAULT_DURATION_MINUTES = 30
_DEFAULT_HOUR_UTC = 9  # a resolved date with no time-of-day defaults to 9am


def enabled() -> bool:
    return os.getenv("MEETING_NOTES_CREATE_CALENDAR_EVENTS", "true").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _resolve_start(date_text: str, *, reference: datetime) -> datetime | None:
   
    try:
        parsed = date_parser.parse(date_text, fuzzy=True, default=reference)
    except (ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if ":" not in date_text:
        parsed = parsed.replace(hour=_DEFAULT_HOUR_UTC, minute=0, second=0, microsecond=0)
    return parsed


async def schedule_follow_ups(
    events: list[FollowUpEvent],
    *,
    organizer_id: str,
    meeting_subject: str,
) -> list[dict]:
    if not enabled() or not organizer_id or not events:
        return []

    now = datetime.now(timezone.utc)
    results: list[dict] = []
    for event in events:
        if not event.date:
            results.append({"title": event.title, "status": "skipped", "reason": "no date stated"})
            continue
        start = _resolve_start(event.date, reference=now)
        if start is None or start < now - timedelta(days=1):
            results.append(
                {
                    "title": event.title,
                    "status": "skipped",
                    "reason": f"unresolvable or past date: {event.date!r}",
                }
            )
            continue
        end = start + timedelta(minutes=_DEFAULT_DURATION_MINUTES)
        try:
            created = await graph.create_calendar_event(
                organizer_id,
                subject=f"Follow-up: {event.title}" if event.title else f"Follow-up — {meeting_subject}",
                start_iso=start.isoformat(),
                end_iso=end.isoformat(),
                body_html=event.notes or "",
            )
            results.append(
                {
                    "title": event.title,
                    "status": "created",
                    "start": start.isoformat(),
                    "event_id": created.get("id"),
                }
            )
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("Calendar event creation failed for %r: %s", event.title, exc)
            results.append({"title": event.title, "status": "error", "reason": str(exc)})
    return results
