"""
Business-area routing.

The complaint the project exists to solve is that Financial Planning and Business
Services notes are formatted inconsistently. Routing keeps them consistently
different: the organiser's Entra group or department picks the area, the area
picks the prompt and the template (options paper, section 4).

If the organiser matches neither area we fall back to a general template and set
`flagged` — a wrong-format note is worse than an obviously generic one, so we
never guess.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class BusinessArea:
    key: str
    display_name: str
    template: str
    # Extra, area-specific guidance appended to the base note-generation prompt.
    prompt_guidance: str = ""
    # Entra group display names that map to this area.
    group_names: tuple[str, ...] = ()
    # Case-insensitive substrings matched against the organiser's department.
    department_keywords: tuple[str, ...] = ()
    flagged: bool = field(default=False)


# Baked-in defaults matching the two areas named in the brief. Override the whole
# set with MEETING_NOTES_AREAS (JSON) without a code change if the firm's group
# names or wording differ.
_DEFAULT_AREAS: tuple[BusinessArea, ...] = (
    BusinessArea(
        key="financial_planning",
        display_name="Financial Planning",
        template="financial_planning",
        prompt_guidance=(
            "This is a financial planning client meeting. Pay particular "
            "attention to advice given, strategies discussed, products named, "
            "risk tolerance, and any agreed reviews or follow-up appointments."
        ),
        group_names=("FP-Advisers",),
        department_keywords=("financial planning",),
    ),
    BusinessArea(
        key="business_services",
        display_name="Business Services",
        template="business_services",
        prompt_guidance=(
            "This is a business services / accounting client meeting. Pay "
            "particular attention to tax, compliance obligations, deadlines, "
            "entity structures, and bookkeeping or lodgement actions."
        ),
        group_names=("BS-Advisers",),
        department_keywords=("business services", "accounting", "tax"),
    ),
)

# The safe fallback when nothing matches.
GENERAL_AREA = BusinessArea(
    key="general",
    display_name="General",
    template="general",
    prompt_guidance="",
    flagged=True,
)


def _areas() -> tuple[BusinessArea, ...]:
    raw = os.getenv("MEETING_NOTES_AREAS", "").strip()
    if not raw:
        return _DEFAULT_AREAS
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _DEFAULT_AREAS
    areas: list[BusinessArea] = []
    for item in data:
        areas.append(
            BusinessArea(
                key=item["key"],
                display_name=item.get("display_name", item["key"]),
                template=item.get("template", item["key"]),
                prompt_guidance=item.get("prompt_guidance", ""),
                group_names=tuple(item.get("group_names", ())),
                department_keywords=tuple(
                    kw.lower() for kw in item.get("department_keywords", ())
                ),
            )
        )
    return tuple(areas) or _DEFAULT_AREAS


def resolve_business_area(
    user: dict | None,
    group_names: set[str] | None,
) -> BusinessArea:
    """Match the organiser to a business area, or GENERAL_AREA when nothing fits."""
    group_names = group_names or set()
    department = ((user or {}).get("department") or "").strip().lower()

    for area in _areas():
        if group_names & set(area.group_names):
            return area
    for area in _areas():
        if department and any(kw in department for kw in area.department_keywords):
            return area
    return GENERAL_AREA
