
from __future__ import annotations

from pydantic import BaseModel, Field



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


class NoteJobRequest(BaseModel):
    """What the webhook hands the queue: enough to fetch and process one transcript."""

    # Graph resource path for the transcript, taken from the notification.
    transcript_resource: str
    subscription_id: str | None = None
    tenant_id: str | None = None
    dry_run: bool = False
    transcript_vtt: str | None = None

    organizer_id_override: str | None = None
    # Test hooks: transcript_vtt has no real Graph meeting behind it, so there is
    # nothing for get_transcript_metadata/get_online_meeting to fetch. Set these
    # to supply the meeting date / title / attendee roster directly for local
    # testing, mirroring what a live Graph fetch would otherwise populate.
    meeting_date_override: str | None = None
    meeting_title_override: str | None = None
    attendee_emails_override: list[str] | None = None


class NoteJobResult(BaseModel):
    job_id: str
    status: str  # queued | running | completed | failed
    transcript_resource: str = ""
    meeting_id: str | None = None
    organizer_id: str | None = None
    organizer_email: str | None = None
    organizer_name: str | None = None
    business_area: str | None = None
    meeting_type: str | None = None  # AHM | SPM | FM | RM, matched from the meeting title
    meeting_date: str | None = None
    meeting_title: str | None = None
    attendee_emails: list[str] = Field(default_factory=list)
    # True once the transcript has been handed off to the Power Automate flow.
    delivered: bool = False
    error: str | None = None


class SubscriptionInfo(BaseModel):
    """Trimmed view of a Graph subscription for the admin/renewal endpoints."""

    id: str
    resource: str
    expirationDateTime: str
    notificationUrl: str | None = None
    lifecycleNotificationUrl: str | None = None
