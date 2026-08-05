
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MeetingType:
    code: str
    display_name: str
    # Case-insensitive, word-bounded patterns matched against the meeting title.
    keywords: tuple[str, ...] = ()


MEETING_TYPES: tuple[MeetingType, ...] = (
    MeetingType("AHM", "Annual Health Meeting", ("AHM", "annual health meeting")),
    MeetingType("SPM", "Strategic Planning Meeting", ("SPM", "strategic planning meeting")),
    MeetingType("FM", "Financial Meeting", ("FM", "financial meeting")),
    MeetingType("RM", "Review Meeting", ("RM", "review meeting")),
)


def resolve_meeting_type(meeting_title: str | None) -> str | None:
    """Match the meeting title against known type keywords.

    Returns the type code (AHM/SPM/FM/RM), or None when the title carries no
    recognisable tag — the Power Automate flow gets a null rather than a guess.
    """
    title = (meeting_title or "").strip()
    if not title:
        return None
    for meeting_type in MEETING_TYPES:
        for keyword in meeting_type.keywords:
            if re.search(rf"\b{re.escape(keyword)}\b", title, re.IGNORECASE):
                return meeting_type.code
    return None
