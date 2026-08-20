"""
Live Group Structure data — STUB. No entity-register API client exists in
this codebase. The section itself also requires a hand-arranged layout
(`levels`/`edges`, see `sections/group_structure.py`'s docstring) rather than
auto-layout, so even once a source is wired the level/edge arrangement needs
either a fixed convention per client or a small layout step of its own.
"""
from __future__ import annotations

from api.automations.client_review_pack.sections.group_structure import GroupStructureData


async def fetch_live_group_structure(client_name: str) -> GroupStructureData:
    """Fetch and shape one client's entity-relationship structure.

    To make this live:
      1. Add a client for wherever entity/ownership records actually live
         (Zoho custom module? the practice's corporate-secretarial platform?
         ASIC data?) — follow `api/automations/zoho/client.py`'s shape.
      2. Add its credentials to `local.settings.json`.
      3. Replace the `raise` below with: fetch entities and ownership links
         for `client_name`, arrange them into `levels` (top row first) and
         `edges` (parent id, child id), return a `GroupStructureData`.
    """
    raise NotImplementedError(
        "No entity-register API is integrated in this codebase yet — "
        "see this function's docstring for what to add."
    )
