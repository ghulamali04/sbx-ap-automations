# Meeting Notes automation

Retires Otter.ai by capturing client meeting transcripts from **Teams native
transcription**, on Microsoft 365 licences the firm already owns, and handing
each one to a Power Automate flow that generates the summary and sends the
email. Implements **Option A** from *Meeting Notes Automation — Technical
Options*, with summary generation and delivery delegated to Power Automate
rather than done in this app.

```
Teams meeting (transcription on)
  → transcript created in the tenant
  → one tenant-wide Graph subscription (communications/onlineMeetings/getAllTranscripts)
    POSTs a webhook to  /meeting-notes/notifications
  → this app fetches the .vtt, parses it to speaker-attributed text,
    resolves the meeting's title + roster, the meeting type (AHM/SPM/FM/RM)
    from the title, and the recording (if any),
  → POSTs {transcript_text, meeting_subject, meeting_title, meeting_type,
    meeting_date, organizer_name, organizer_email, attendee_emails,
    business_area, recording_url} to MEETING_NOTES_WEBHOOK_URL
  → the Power Automate flow generates the summary and sends the email.
```

`business_area` is currently always sent as `null` — there is no confirmed
source/mapping for it yet on the Power Automate side. The organiser-based
routing in `routing.py` still runs and is visible on the job record
(`GET /{job_id}`) for admin/debugging, it's just not forwarded in the payload.

No Microsoft 365 Copilot, Teams Premium, or Power Automate premium licences are
required.

## Module map

| File | Responsibility |
|------|----------------|
| `graph.py` | App-only Microsoft Graph client (token, transcript, user/group, subscription CRUD) |
| `vtt.py` | Parse Teams WebVTT into speaker-attributed text |
| `routing.py` | Organiser → business area (falls back to a flagged general area) |
| `meeting_type.py` | Meeting title → meeting type (AHM/SPM/FM/RM), or `None` when untagged |
| `power_automate.py` | Validate + POST the transcript/context to the Power Automate flow |
| `service.py` | End-to-end orchestration for one transcript |
| `queue.py` / `jobs.py` | Durable queue + job store (local fallbacks for dev) |
| `subscriptions.py` | Create / renew the one tenant-wide transcript subscription |
| `routes.py` | Webhook, lifecycle, subscription admin, and job-status endpoints |

## Endpoints

| Method & path | Purpose |
|---------------|---------|
| `POST /meeting-notes/notifications` | Graph webhook (validation handshake + transcript notifications) |
| `POST /meeting-notes/lifecycle` | Graph lifecycle events (auto-renews on reauthorization/removal) |
| `POST /meeting-notes/subscriptions` | Create the tenant-wide subscription (admin, once) |
| `GET  /meeting-notes/subscriptions` | List this app's transcript subscriptions |
| `POST /meeting-notes/subscriptions/renew` | Renew any near-expiry subscription (also on a 6-hourly timer) |
| `GET  /meeting-notes/{job_id}` | Job status |

The queue trigger `process_meeting_note_job` and the renewal timer
`renew_meeting_note_subscription` are registered in `backend/function_app.py`.

## One-time admin setup (from the options paper, sections 3 & 9)

1. **Enable transcription tenant-wide** (Teams admin / PowerShell):
   `Set-CsTeamsMeetingPolicy -Identity Global -AllowTranscription $true`
2. **Verify the two tenant switches** or every request 403s:
   *Graph API access to transcripts* = **on**, *Speaker attribution* = **on**.
3. **Register one app** and grant admin consent for application permissions:
   `OnlineMeetingTranscript.Read.All`, `OnlineMeetings.Read.All`,
   `User.Read.All`, `GroupMember.Read.All`. Put its tenant/client id + secret in
   `GRAPH_*` (or grant the same roles to the Function App managed identity and
   leave `GRAPH_*` blank in Azure). Additionally grant
   `OnlineMeetingRecording.Read.All` if recordings should be fetched —
   without it, `recording_url` is sent as `""` for every meeting (the fetch is
   best-effort and never blocks the handoff; see `graph.list_meeting_recordings`).
4. **Configure** `MEETING_NOTES_NOTIFICATION_URL` (this app's public
   `/meeting-notes/notifications`), a secret `MEETING_NOTES_CLIENT_STATE`,
   `MEETING_NOTES_WEBHOOK_URL` (the Power Automate flow that generates the
   summary and sends the email), and `MEETING_NOTES_ADMIN_KEY` (required on the
   `X-Admin-Key` header for the subscription-admin and job-status endpoints —
   see Security below).
5. **Create the subscription**: `POST /meeting-notes/subscriptions`. The 6-hourly
   timer keeps it alive thereafter — the subscription must exist *before* a
   meeting starts or that meeting produces no notification.
6. **Grant an application access policy** — this is a *separate* Teams-admin
   step from the app-registration permissions above, and both
   `get_transcript_metadata`/`get_transcript_content` (fetching each notified
   transcript) and `get_online_meeting` (title/attendees) need it. Without it
   every real fetch 403s with `"neither is allowed access through RSC
   permission evaluation"`, even though the bulk `getAllTranscripts` listing
   (used for local testing) works fine without it. Run from Skype for Business
   PowerShell / Teams PowerShell:
   ```powershell
   New-CsApplicationAccessPolicy -Identity MeetingNotesPolicy -AppIds "<GRAPH_CLIENT_ID>" -Description "Meeting notes automation"
   # Per-user, during the pilot:
   Grant-CsApplicationAccessPolicy -PolicyName MeetingNotesPolicy -Identity "<adviser-object-id>"
   # Or tenant-wide, once past the pilot:
   Grant-CsApplicationAccessPolicy -PolicyName MeetingNotesPolicy -Global
   ```
   Allow up to 30 minutes for this to take effect. See [Configure an application
   access policy](https://learn.microsoft.com/en-us/graph/cloud-communication-online-meeting-application-access-policy).

> **Auto-start caveat (section 6):** there is no tenant-wide switch that forces
> every meeting to transcribe. During the pilot, advisers press **Transcribe** (or
> set *Record and transcribe automatically* when scheduling). A meeting with no
> transcript produces no handoff.

## Configuration

| Variable | Default | Notes |
|----------|---------|-------|
| `GRAPH_TENANT_ID` / `GRAPH_CLIENT_ID` / `GRAPH_CLIENT_SECRET` | — | App registration; blank ⇒ managed identity / `az login` |
| `MEETING_NOTES_NOTIFICATION_URL` | — | Required to create/renew the subscription |
| `MEETING_NOTES_LIFECYCLE_URL` | `<notify host>/lifecycle` | Mandatory for expiry > 1h ahead |
| `MEETING_NOTES_CLIENT_STATE` | — | Secret echoed by Graph; verified on every notification |
| `MEETING_NOTES_WEBHOOK_URL` | — | Power Automate flow that generates the summary and sends the email |
| `MEETING_NOTES_ALLOWED_HOSTS` | falls back to `POWER_AUTOMATE_ALLOWED_HOSTS` | Host allowlist for the webhook URL |
| `MEETING_NOTES_DRY_RUN` | `false` | Fetch + parse the transcript but skip the Power Automate handoff |
| `MEETING_NOTES_AREAS` | built-in FP/BS | JSON to override business-area routing |
| `MEETING_NOTES_ADMIN_KEY` | — | Required as `X-Admin-Key` on `/subscriptions*` and `GET /{job_id}`; unset = open (dev only) |

## Security

The Function App runs with `AuthLevel.ANONYMOUS` (see `function_app.py`) — nothing
in front of this ASGI app authenticates a caller by default, so each endpoint
here is deliberately self-protecting:

- **`/notifications` and `/lifecycle`** — only Graph calls these. Every
  notification's `clientState` is checked against `MEETING_NOTES_CLIENT_STATE`
  with a constant-time comparison (`secrets.compare_digest`); anything else is
  dropped, not processed.
- **`/subscriptions*` and `GET /{job_id}`** — these can create/list the
  tenant-wide Graph subscription or read a job's organiser email, so they
  require an `X-Admin-Key: <MEETING_NOTES_ADMIN_KEY>` header
  (`routes.require_admin_key`), also compared in constant time. Leave the
  variable unset only for local dev; set it before deploying anywhere reachable.
- **Outbound webhook** — `power_automate.validate_webhook_url` rejects
  anything that isn't `https` or isn't on the `MEETING_NOTES_ALLOWED_HOSTS` (or
  shared `POWER_AUTOMATE_ALLOWED_HOSTS`) allowlist before every POST, so a bad
  or tampered `MEETING_NOTES_WEBHOOK_URL` fails closed rather than silently
  sending transcripts somewhere unexpected.
- **Secrets never in source** — `MEETING_NOTES_WEBHOOK_URL` (carries a SAS
  signature), `MEETING_NOTES_CLIENT_STATE`, and `MEETING_NOTES_ADMIN_KEY` all
  live only in `local.settings.json` / the deployed app's settings, never
  hardcoded.

## Local testing

`transcript_vtt` on `NoteJobRequest` lets you run the pipeline against a local
`.vtt` with no Graph calls (see `tests/fixtures/run_meeting_notes_tests.py`).
Combine with `dry_run=True` to exercise parsing/routing without POSTing to
Power Automate.
