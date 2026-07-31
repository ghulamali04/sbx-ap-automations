# Meeting Notes automation

Retires Otter.ai by generating client meeting notes from **Teams native
transcription**, on Microsoft 365 licences the firm already owns. This implements
**Option A** from *Meeting Notes Automation — Technical Options*.

```
Teams meeting (transcription on)
  → transcript created in the tenant
  → one tenant-wide Graph subscription (communications/onlineMeetings/getAllTranscripts)
    POSTs a webhook to  /meeting-notes/notifications
  → this app fetches the .vtt, resolves the organiser's business area,
    applies the firm's prompt via Azure OpenAI → structured notes,
    renders the firm's HTML template,
  → Graph sendMail delivers the note to the adviser.
```

No Microsoft 365 Copilot, Teams Premium, or Power Automate premium licences are
required.

## Module map

| File | Responsibility |
|------|----------------|
| `graph.py` | App-only Microsoft Graph client (token, transcript, user/group, sendMail, subscription CRUD) |
| `vtt.py` | Parse Teams WebVTT into speaker-attributed text |
| `routing.py` | Organiser → business area → prompt + template (falls back to a flagged general template) |
| `azure_openai.py` | Transcript → structured JSON notes (instruction-fenced, uncertainty rule) |
| `notes.py` | Structured notes → firm HTML template |
| `service.py` | End-to-end orchestration for one transcript |
| `queue.py` / `jobs.py` / `artifacts.py` | Durable queue + job store + note store (local fallbacks for dev) |
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
| `GET  /meeting-notes/{job_id}/note` | View the rendered HTML note |

The queue trigger `process_meeting_note_job` and the renewal timer
`renew_meeting_note_subscription` are registered in `backend/function_app.py`.

## One-time admin setup (from the options paper, sections 3 & 9)

1. **Enable transcription tenant-wide** (Teams admin / PowerShell):
   `Set-CsTeamsMeetingPolicy -Identity Global -AllowTranscription $true`
2. **Verify the two tenant switches** or every request 403s:
   *Graph API access to transcripts* = **on**, *Speaker attribution* = **on**.
3. **Register one app** and grant admin consent for application permissions:
   `OnlineMeetingTranscript.Read.All`, `User.Read.All`, `GroupMember.Read.All`,
   `Mail.Send`. Put its tenant/client id + secret in `GRAPH_*` (or grant the same
   roles to the Function App managed identity and leave `GRAPH_*` blank in Azure).
4. **Configure** `MEETING_NOTES_NOTIFICATION_URL` (this app's public
   `/meeting-notes/notifications`), a secret `MEETING_NOTES_CLIENT_STATE`, and
   `MEETING_NOTES_MAIL_SENDER` (the mailbox notes are sent from).
5. **Create the subscription**: `POST /meeting-notes/subscriptions`. The 6-hourly
   timer keeps it alive thereafter — the subscription must exist *before* a
   meeting starts or that meeting produces no notification.

> **Auto-start caveat (section 6):** there is no tenant-wide switch that forces
> every meeting to transcribe. During the pilot, advisers press **Transcribe** (or
> set *Record and transcribe automatically* when scheduling). A meeting with no
> transcript produces no note.

## Configuration

| Variable | Default | Notes |
|----------|---------|-------|
| `GRAPH_TENANT_ID` / `GRAPH_CLIENT_ID` / `GRAPH_CLIENT_SECRET` | — | App registration; blank ⇒ managed identity / `az login` |
| `MEETING_NOTES_NOTIFICATION_URL` | — | Required to create/renew the subscription |
| `MEETING_NOTES_LIFECYCLE_URL` | `<notify host>/lifecycle` | Mandatory for expiry > 1h ahead |
| `MEETING_NOTES_CLIENT_STATE` | — | Secret echoed by Graph; verified on every notification |
| `MEETING_NOTES_MAIL_SENDER` | organiser id | Mailbox `sendMail` sends as |
| `MEETING_NOTES_DRY_RUN` | `false` | Render + store the note but skip delivery |
| `MEETING_NOTES_GLOSSARY` | — | Domain terms to correct transcription weak points |
| `MEETING_NOTES_AREAS` | built-in FP/BS | JSON to override business-area routing |
| `AZURE_OPENAI_*` | shared with task_summary_report | Model endpoint/deployment |

## Local testing

`transcript_vtt` on `NoteJobRequest` lets you run the whole pipeline against a
local `.vtt` with no Graph calls (see `tests/test_meeting_notes.py`). Combine with
`MEETING_NOTES_DRY_RUN=true` to render and store a note without a mailbox.
