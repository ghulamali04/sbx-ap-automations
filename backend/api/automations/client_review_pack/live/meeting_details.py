"""
Live Meeting Notes data — STUB, and structurally different from every other
module in this package. `meeting_notes` (MS Graph) is push-driven: a Teams
transcript notification arrives, gets fetched, and is handed to Power
Automate, which generates the summary and sends the email — this app never
gets agenda/objectives/action-items back. There is no "fetch by client name"
call to make here the way there is for Zoho tasks.

Graph *can* supply date/time/location/attendees for a specific meeting
(`meeting_notes.graph.get_online_meeting`), but only given a `meeting_id` from
an already-received transcript notification — not from a client name, so it
doesn't fit this module's `fetch_live_x(client_name)` shape either.
"""
from __future__ import annotations

from api.automations.client_review_pack.sections.meeting_details import MeetingDetailsData


async def fetch_live_meeting_details(client_name: str) -> MeetingDetailsData:
    """Not implementable as a simple fetch — see module docstring.

    To make this live, one of:
      (a) Have Power Automate POST its AI-generated agenda/objectives/action
          items back to a new endpoint in this app (mirroring how
          `meeting_notes.power_automate.deliver_transcript` POSTs *out*),
          store it, and have this function read the stored record for the
          most recent meeting matching `client_name`; or
      (b) Call `meeting_notes.graph.get_online_meeting(organizer_id,
          meeting_id)` for one specific already-known meeting — but that needs
          a `meeting_id`, not a client name, so the caller (not this function)
          would need to resolve which meeting.
    """
    raise NotImplementedError(
        "Meeting details has no fetch-by-client-name source — see this function's "
        "docstring for the two real options."
    )
