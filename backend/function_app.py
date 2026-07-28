import os

import azure.functions as func

from api.main import app as fastapi_app
from api.automations.completion_overview import queue as report_queue
from api.automations.task_summary_report import queue as task_report_queue
from api.automations.meeting_notes import queue as meeting_notes_queue
from api.automations.meeting_notes import subscriptions as meeting_notes_subscriptions

# The Azure Functions host will call this function to get the ASGI app to run.
# AuthLevel.ANONYMOUS is the default, but we explicitly set it here to avoid confusion
# AuthLevel.FUNCTION (the default for a function) vs AuthLevel.ANONYMOUS (the default for an ASGI app).
app = func.AsgiFunctionApp(app=fastapi_app, http_auth_level=func.AuthLevel.ANONYMOUS)


@app.function_name(name="process_report_job")
@app.queue_trigger(
    arg_name="msg",
    queue_name=report_queue.QUEUE_NAME,
    # Resolves against the identity-based AzureWebJobsStorage__queueServiceUri /
    # __credential settings. A queue trigger whose connection cannot be resolved
    # puts the host into an error state and stops *every* trigger, not just this one.
    connection="AzureWebJobsStorage",
)
async def process_report_job(msg: func.QueueMessage) -> None:
    """Run one queued completion-overview report on its own invocation."""
    await report_queue.process_message(msg.get_body().decode("utf-8"))


@app.function_name(name="process_task_summary_job")
@app.queue_trigger(
    arg_name="msg",
    queue_name=task_report_queue.QUEUE_NAME,
    connection="AzureWebJobsStorage",
)
async def process_task_summary_job(msg: func.QueueMessage) -> None:
    """Run one queued Task Summary report on its own invocation."""
    await task_report_queue.process_message(msg.get_body().decode("utf-8"))


@app.function_name(name="process_meeting_note_job")
@app.queue_trigger(
    arg_name="msg",
    queue_name=meeting_notes_queue.QUEUE_NAME,
    connection="AzureWebJobsStorage",
)
async def process_meeting_note_job(msg: func.QueueMessage) -> None:
    """Turn one queued Teams transcript into a formatted, emailed meeting note."""
    await meeting_notes_queue.process_message(msg.get_body().decode("utf-8"))


@app.function_name(name="renew_meeting_note_subscription")
@app.timer_trigger(
    arg_name="timer",
    # Every 6 hours. The tenant-wide transcript subscription must exist before a
    # meeting starts or that meeting is lost, so renewal is a reliability job, not
    # housekeeping (options paper, sections 3.3 and 8). renew_due() is idempotent:
    # it renews only subscriptions near expiry and recreates a missing one.
    schedule="0 0 */6 * * *",
    run_on_startup=False,
    use_monitor=True,
)
async def renew_meeting_note_subscription(timer: func.TimerRequest) -> None:
    """Keep the tenant-wide transcript subscription alive on a schedule."""
    if not meeting_notes_subscriptions.client_state() and not os.getenv(
        "MEETING_NOTES_NOTIFICATION_URL"
    ):
        # Not configured yet — do nothing rather than error the host on every tick.
        return
    await meeting_notes_subscriptions.renew_due()
