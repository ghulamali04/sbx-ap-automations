"""
Build and locate the one tenant-wide Graph subscription that feeds this pipeline.

The subscription on communications/onlineMeetings/getAllTranscripts is what makes
this scale: one registered app receives a notification for every transcribed
meeting in the tenant, with no per-account install.

Two operational facts:
  * The subscription must exist *before* a meeting ends, or that transcript
    produces no notification — renewal is a reliability job, not housekeeping.
  * A lifecycleNotificationUrl is mandatory for any expiry more than an hour
    ahead, and getAllTranscripts caps expiry a few days out — hence renewal.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

# getAllTranscripts caps expiry a few days out; stay safely under it.
_DEFAULT_EXPIRY_MINUTES = 4230  # ~70.5h, under the ~3-day maximum


def resource() -> str:
    return os.getenv(
        "MEETING_NOTES_SUBSCRIPTION_RESOURCE",
        "communications/onlineMeetings/getAllTranscripts",
    )


def notification_url() -> str:
    url = os.getenv("MEETING_NOTES_NOTIFICATION_URL", "").strip()
    if not url:
        raise RuntimeError(
            "MEETING_NOTES_NOTIFICATION_URL is not set. Point it at this app's "
            "public /meeting-notes/notifications endpoint (a tunnel URL locally, "
            "or the Function App hostname when deployed)."
        )
    return url


def lifecycle_url() -> str:
    # Falls back to the notifications host with /lifecycle if not set explicitly.
    url = os.getenv("MEETING_NOTES_LIFECYCLE_URL", "").strip()
    if url:
        return url
    return notification_url().rsplit("/", 1)[0] + "/lifecycle"


def client_state() -> str:
    return os.getenv("MEETING_NOTES_CLIENT_STATE", "").strip()


def _expiry_iso(minutes: int | None = None) -> str:
    minutes = minutes or int(
        os.getenv("MEETING_NOTES_SUBSCRIPTION_MINUTES", str(_DEFAULT_EXPIRY_MINUTES))
    )
    expiry = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    # Graph wants the trailing Z form with 7 fractional digits.
    return expiry.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")


def subscription_body() -> dict:
    """Build the POST body for the tenant-wide transcript subscription.

    includeResourceData is false: notifications without resource data need no
    encryption certificate. The automation fetches the transcript itself using the
    resource path in each notification.
    """
    body = {
        "changeType": "created",
        "notificationUrl": notification_url(),
        "lifecycleNotificationUrl": lifecycle_url(),
        "resource": resource(),
        "includeResourceData": False,
        "expirationDateTime": _expiry_iso(),
    }
    secret = client_state()
    if secret:
        body["clientState"] = secret
    return body
