# Meeting Notes — Microsoft Graph / Teams tenant setup

How to get app-only Microsoft Graph access working so the Meeting Notes automation
can fetch Teams meeting transcripts. These are the exact steps (and the exact errors
you hit if a step is missing), verified against tenant `AdvisoryPartners603` on
2026-07-31.

The automation authenticates as an **application** (client credentials), never as a
person — delegated sign-in is not used.

## 1. App registration + client secret

In **Microsoft Entra ID → App registrations**, note:

| Portal label | Env variable |
| --- | --- |
| Application (client) ID | `GRAPH_CLIENT_ID` |
| Directory (tenant) ID | `GRAPH_TENANT_ID` |
| Certificates & secrets → **Value** | `GRAPH_CLIENT_SECRET` |

> **Gotcha:** `GRAPH_CLIENT_SECRET` must be the secret **Value** (~40 chars, e.g.
> `1K38Q~...`), **not** the **Secret ID** (a GUID). Using the ID gives:
> `AADSTS7000215: Invalid client secret provided.`
> The secret Value is shown only once at creation — if lost, create a new secret.

Set these in `backend/local.settings.json` (gitignored) for local runs, or in the
Function App settings / Key Vault for deployed environments.

## 2. Graph API permissions + admin consent

In the app registration → **API permissions**, add these **Application** permissions
(not Delegated) for Microsoft Graph:

- `User.Read.All` — resolve organisers
- `OnlineMeetingTranscript.Read.All` — read transcripts
- `OnlineMeetingArtifact.Read.All` — read recording/transcript artifacts
- `Mail.Send` — send the formatted note (pipeline delivery)
- `OnlineMeetings.Read.All` — *only if* resolving a specific meeting by `joinWebUrl` /
  `chatInfo/threadId` (not needed for `getAllTranscripts`)

Then click **Grant admin consent for <tenant>**. Every permission's Status must turn
green ("Granted").

> **Gotcha:** Adding a permission without granting admin consent does nothing. The
> symptom is a token with **no `roles` claim** and every data call returning
> `403 Authorization_RequestDenied — Insufficient privileges`.
>
> Verify consent landed by decoding the token's `roles` claim:
> ```bash
> cd backend && .venv/bin/python -c "
> import os, json, base64
> from api.settings import load_local_settings; load_local_settings()
> from azure.identity import ClientSecretCredential
> c = ClientSecretCredential(os.environ['GRAPH_TENANT_ID'], os.environ['GRAPH_CLIENT_ID'], os.environ['GRAPH_CLIENT_SECRET'])
> t = c.get_token('https://graph.microsoft.com/.default').token
> p = t.split('.')[1]; p += '=' * (-len(p) % 4)
> print('roles:', json.loads(base64.urlsafe_b64decode(p)).get('roles', '(none — consent missing)'))
> "
> ```
> When it lists the role names, consent is in place.

## 3. Teams tenant policy (transcript access)

Even with Graph permissions consented, Teams gates transcript access at the tenant
level. Missing this gives `403 GraphAccessToTranscriptsDisabled`.

**a) Allow transcription** (GUI — admin.teams.microsoft.com):
Meetings → Meeting policies → (Global / the org policy) → **Transcription: On**.

**b) Application Access Policy** (PowerShell only — no GUI exists for this):

```powershell
Connect-MicrosoftTeams

New-CsApplicationAccessPolicy -Identity "MeetingNotesTranscripts" `
  -AppIds "<GRAPH_CLIENT_ID>" `
  -Description "Meeting notes automation - transcript access"

# Tenant-wide, or scope to specific organisers with -Identity <UPN>
Grant-CsApplicationAccessPolicy -PolicyName "MeetingNotesTranscripts" -Global
```

Policy changes can take ~30–60 minutes to propagate.

## 4. Verified behaviour

- **Scheduled Teams meetings** with transcription enabled → transcript appears via
  `getAllTranscripts` almost instantly. This is the supported path.
- **"Meet Now" / instant meetings** → do **not** reliably surface through
  `getAllTranscripts` (the Teams recap UI shows the OneDrive file, but Graph does
  not index it). Treat instant meetings as unsupported.
- **Transcription is manual** — an organiser must turn it on in the meeting, or no
  transcript is produced.
- `getAllTranscripts` is an OData function; the URL must pass the organiser as a
  bound parameter: `/users/{id}/onlineMeetings/getAllTranscripts(meetingOrganizerUserId='{id}')`.
  A `404` from it means "no transcripts for this organiser" (an empty result, not a
  failure).

## 5. Test routes

`backend/api/automations/meeting_notes/routes.py` exposes read-only test endpoints
(prefix `/meeting-notes`). Run the API and open `/docs`:

```bash
cd backend && .venv/bin/python -m uvicorn api.main:app --port 8000
```

| Route | Checks |
| --- | --- |
| `GET /meeting-notes/health` | Graph configured (no network) |
| `GET /meeting-notes/graph-test` | App-only token acquisition |
| `GET /meeting-notes/subscriptions` | Reach Graph / transcript notification feed |
| `GET /meeting-notes/users/{user}` | User lookup (`User.Read.All`) |
| `GET /meeting-notes/users/{user}/meetings` | Calendar meetings (`Calendars.Read`) |
| `GET /meeting-notes/users/{user}/transcripts` | Fetch a user's meeting transcripts |
| `GET /meeting-notes/transcript/content?resource=…` | Fetch one transcript as WebVTT |

The repo-root `main.py` is a standalone CLI version of the same connectivity check:
`backend/.venv/bin/python main.py [userIdOrUPN]`.

## 6. Production detection (not polling)

The live pipeline does not poll `getAllTranscripts`. It maintains a change-notification
subscription on `communications/onlineMeetings/getAllTranscripts`
(`meeting_notes/subscriptions.py`); Teams pushes a notification when a transcript is
ready, and the automation fetches it from the resource path in the notification.
