"""
Manage the one tenant-wide Graph subscription that feeds this pipeline.

The subscription on communications/onlineMeetings/getAllTranscripts is what makes
this scale: one registered app receives a notification for every transcribed
meeting in the tenant, with no per-account install (options paper, section 3.3).

Two operational facts drive this module:
  * The subscription must exist *before* a meeting starts, or that meeting
    produces no notification. So renewal is a reliability job, not housekeeping.
  * A lifecycleNotificationUrl is mandatory for any expiry more than an hour
    ahead, and expiry is capped a few days out — hence the renewal timer.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from api.automations.meeting_notes import graph
from api.automations.meeting_notes.models import SubscriptionInfo

_LOG = logging.getLogger(__name__)

# getAllTranscripts caps expiry a few days out; stay safely under it and renew
# well before the boundary. Override if Microsoft changes the ceiling.
_DEFAULT_EXPIRY_MINUTES = 4230  # ~70.5h, under the ~3-day maximum
# Renew when a subscription has less than this many minutes of life left.
_DEFAULT_RENEW_THRESHOLD_MINUTES = 720  # 12h


def resource() -> str:
    return os.getenv(
        "MEETING_NOTES_SUBSCRIPTION_RESOURCE",
        "communications/onlineMeetings/getAllTranscripts",
    )


def _notification_url() -> str:
    url = os.getenv("MEETING_NOTES_NOTIFICATION_URL", "").strip()
    if not url:
        raise RuntimeError(
            "MEETING_NOTES_NOTIFICATION_URL is not set. Point it at this app's "
            "public /meeting-notes/notifications endpoint."
        )
    return url


def _lifecycle_url() -> str:
    # Falls back to the notifications host with /lifecycle if not set explicitly.
    url = os.getenv("MEETING_NOTES_LIFECYCLE_URL", "").strip()
    if url:
        return url
    notify = _notification_url()
    return notify.rsplit("/", 1)[0] + "/lifecycle"


def client_state() -> str:
    return os.getenv("MEETING_NOTES_CLIENT_STATE", "").strip()


def _expiry_iso(minutes: int | None = None) -> str:
    minutes = minutes or int(
        os.getenv("MEETING_NOTES_SUBSCRIPTION_MINUTES", str(_DEFAULT_EXPIRY_MINUTES))
    )
    expiry = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    # Graph wants the trailing Z form.
    return expiry.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")


def subscription_body() -> dict:
    """Build the POST body for the tenant-wide transcript subscription.

    includeResourceData is false: notifications without resource data need no
    encryption certificate, which removes certificate management from the build
    (options paper, section 3.3). The automation fetches the transcript itself.
    """
    body = {
        "changeType": "created",
        "notificationUrl": _notification_url(),
        "lifecycleNotificationUrl": _lifecycle_url(),
        "resource": resource(),
        "includeResourceData": False,
        "expirationDateTime": _expiry_iso(),
    }
    secret = client_state()
    if secret:
        body["clientState"] = secret
    return body


def _to_info(sub: dict) -> SubscriptionInfo:
    return SubscriptionInfo(
        id=sub.get("id", ""),
        resource=sub.get("resource", ""),
        expirationDateTime=sub.get("expirationDateTime", ""),
        notificationUrl=sub.get("notificationUrl"),
        lifecycleNotificationUrl=sub.get("lifecycleNotificationUrl"),
    )


async def create() -> SubscriptionInfo:
    """Create the tenant-wide subscription. Admin-triggered, once per lifecycle."""
    created = await graph.create_subscription(subscription_body())
    _LOG.info("Created transcript subscription %s", created.get("id"))
    return _to_info(created)


async def renew_one(subscription_id: str) -> SubscriptionInfo:
    renewed = await graph.renew_subscription(subscription_id, _expiry_iso())
    _LOG.info("Renewed transcript subscription %s", subscription_id)
    return _to_info(renewed)


def _minutes_left(expiration_iso: str) -> float:
    try:
        expires = datetime.fromisoformat(expiration_iso.replace("Z", "+00:00"))
    except ValueError:
        return -1.0
    return (expires - datetime.now(timezone.utc)).total_seconds() / 60.0


async def renew_due() -> list[SubscriptionInfo]:
    """Renew every transcript subscription close to expiry. Called by the timer.

    Idempotent and safe to run often: subscriptions with plenty of life left are
    left alone. If none exist yet, one is created so a missed create still heals.
    """
    threshold = int(
        os.getenv(
            "MEETING_NOTES_RENEW_THRESHOLD_MINUTES",
            str(_DEFAULT_RENEW_THRESHOLD_MINUTES),
        )
    )
    target_resource = resource().lower()
    subs = await graph.list_subscriptions()
    ours = [s for s in subs if (s.get("resource") or "").lower() == target_resource]

    if not ours:
        _LOG.warning("No transcript subscription found; creating one.")
        return [await create()]

    renewed: list[SubscriptionInfo] = []
    for sub in ours:
        if _minutes_left(sub.get("expirationDateTime", "")) <= threshold:
            renewed.append(await renew_one(sub["id"]))
        else:
            renewed.append(_to_info(sub))
    return renewed


async def list_ours() -> list[SubscriptionInfo]:
    target_resource = resource().lower()
    subs = await graph.list_subscriptions()
    return [
        _to_info(s)
        for s in subs
        if (s.get("resource") or "").lower() == target_resource
    ]
