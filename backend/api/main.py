
import os

# Load local.settings.json into the environment (no-op under `func start`, which
# already does this). Must run before anything reads os.getenv below.
from api.settings import load_local_settings
load_local_settings()

from azure.core.exceptions import ClientAuthenticationError
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api.automations.zoho.routes import router as zoho_router
from api.automations.completion_overview.routes import router as completion_router
from api.automations.task_summary_report.routes import router as task_summary_router
from api.automations.meeting_notes.routes import router as meeting_notes_router
from api.automations.task_summary_report import azure_openai

app = FastAPI(
    title="Advisory Partners Automations API",
    version="0.1.0",
)

# Env-driven CORS allowlist. Localhost in dev; the SWA/App Service hostname in
# sandbox/prod. Comma-separated. Never hardcode "*" for anything real.
_origins = os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    """Liveness probe — the first thing to hit once deployed to sandbox."""
    return {"status": "ok", "service": "ap-automations"}


@app.get("/azure-model-test")
async def azure_model_test():
    """Verify Azure identity, the Foundry endpoint, and the model deployment."""
    try:
        model_response = await azure_openai.test_model()
    except ClientAuthenticationError as exc:
        raise HTTPException(
            status_code=401,
            detail=(
                "Azure authentication failed. Sign in locally with `az login`, "
                "or verify the Function App managed identity permissions."
            ),
        ) from exc
    except Exception as exc:  # noqa: BLE001 - convert provider failures into an API response
        raise HTTPException(
            status_code=502,
            detail="Azure model request failed. Check the server log for details.",
        ) from exc
    return {
        "status": "ok",
        "model": azure_openai.deployment_name(),
        "response": model_response,
    }


class EchoIn(BaseModel):
    message: str


class EchoOut(BaseModel):
    echoed: str
    length: int


@app.post("/echo", response_model=EchoOut)
async def echo(body: EchoIn):
    """Trivial route that exercises Pydantic request/response validation."""
    return EchoOut(echoed=body.message, length=len(body.message))


# ---------- Automations ----------
app.include_router(zoho_router)
app.include_router(completion_router)
app.include_router(task_summary_router)
app.include_router(meeting_notes_router)
