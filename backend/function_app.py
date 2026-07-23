import azure.functions as func

from api.main import app as fastapi_app
from api.automations.completion_overview import queue as report_queue
from api.automations.task_summary_report import queue as task_report_queue

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
