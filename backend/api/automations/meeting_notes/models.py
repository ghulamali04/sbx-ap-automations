
from __future__ import annotations

from pydantic import BaseModel, Field


# ---------- Graph change notifications ----------
#
# Shape of the payload Microsoft Graph POSTs to notificationUrl for the
# communications/onlineMeetings/getAllTranscripts subscription. With
# includeResourceData=false there is no encrypted content — only the resource
# path, which the automation then fetches. See section 3.3 of the options paper.

class ChangeNotification(BaseModel):
    """One transcript-created notification inside the delivered batch."""

    subscriptionId: str | None = None
    changeType: str | None = None
    # e.g. communications/onlineMeetings('<meetingId>')/transcripts('<transcriptId>')
    resource: str | None = None
    # Graph echoes back the clientState we set on the subscription so we can
    # prove the caller is Graph and not a spoofer that guessed the URL.
    clientState: str | None = None
    tenantId: str | None = None
    resourceData: dict | None = None


class ChangeNotificationCollection(BaseModel):
    """The batch envelope Graph delivers to the webhook and lifecycle endpoints."""

    value: list[ChangeNotification] = Field(default_factory=list)


# ---------- Structured meeting notes (Azure OpenAI output) ----------
#
# The output shape is pinned so the HTML template renders from named fields
# rather than depending on the model's prose (options paper, section 4:
# "Reusing your existing GPT prompts").

class ActionItem(BaseModel):
    description: str = ""
    # Null, not a guess: an invented owner/date is a compliance problem in a
    # financial-advice context, so the model is told to leave these blank when
    # the transcript does not make them explicit (options paper, section 4).
    owner: str | None = None
    due_date: str | None = None


class FollowUpEvent(BaseModel):
    title: str = ""
    date: str | None = None
    notes: str | None = None


class MeetingNote(BaseModel):
    summary: str = ""
    decisions: list[str] = Field(default_factory=list)
    actions: list[ActionItem] = Field(default_factory=list)
    follow_up_events: list[FollowUpEvent] = Field(default_factory=list)
    risks_or_flags: list[str] = Field(default_factory=list)


# ---------- Job payload / result ----------

class NoteJobRequest(BaseModel):
    """What the webhook hands the queue: enough to fetch and process one transcript."""

    # Graph resource path for the transcript, taken from the notification.
    transcript_resource: str
    subscription_id: str | None = None
    tenant_id: str | None = None
    # Skip Graph sendMail — render the note and store it only. Useful for the
    # Phase 0/1 pilot and for local testing without mailbox permissions.
    dry_run: bool = False
    # Optional override so a test can feed a local .vtt instead of calling Graph.
    transcript_vtt: str | None = None
    # Test hook: when transcript_vtt is set there is no Graph metadata fetch to
    # supply an organiser, so routing/calendar steps have nothing to key off. Set
    # this to force an organiser id for local testing; ignored when Graph supplies
    # its own organiser from the transcript metadata.
    organizer_id_override: str | None = None


class NoteJobResult(BaseModel):
    job_id: str
    status: str  # queued | running | completed | failed
    transcript_resource: str = ""
    meeting_id: str | None = None
    organizer_id: str | None = None
    organizer_email: str | None = None
    organizer_name: str | None = None
    business_area: str | None = None
    template: str | None = None
    delivered: bool = False
    # One entry per follow_up_event: {"title", "status": created|skipped|error, ...}.
    calendar_events: list[dict] = Field(default_factory=list)
    error: str | None = None
    # Absolute link to the rendered HTML note, filled in by the status route so
    # it always reflects the host the caller reached. None until the note exists.
    note_url: str | None = None


class SubscriptionInfo(BaseModel):
    """Trimmed view of a Graph subscription for the admin/renewal endpoints."""

    id: str
    resource: str
    expirationDateTime: str
    notificationUrl: str | None = None
    lifecycleNotificationUrl: str | None = None
