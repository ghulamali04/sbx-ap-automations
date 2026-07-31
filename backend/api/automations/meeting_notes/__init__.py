"""
Meeting Notes automation.

Retires Otter.ai by running the whole meeting-notes pipeline on Microsoft 365
licences the firm already owns (see the Technical Options paper, Option A):

    Teams meeting (transcription on)
      -> transcript created in the tenant
      -> one tenant-wide Graph subscription on
         communications/onlineMeetings/getAllTranscripts fires a webhook
      -> this automation fetches the .vtt transcript, resolves the organiser's
         business area, applies the firm's existing prompt via Azure OpenAI to
         produce structured notes, renders the firm's HTML template, and
      -> emails the formatted note to the adviser via Graph sendMail.

No Microsoft 365 Copilot, Teams Premium, or Power Automate premium licences are
required for this design.
"""
