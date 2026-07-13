"""
Load configuration from local.settings.json when running outside the Functions host.

Azure Functions Core Tools (`func start`) automatically load the "Values" block of
local.settings.json into environment variables. When running the FastAPI app directly
under uvicorn, nothing does that — so this module reproduces the behaviour, giving both
run modes a single source of config.

Real environment variables always win (setdefault), so the Functions host, the cloud
deployment's app settings, and any explicit `export` are never overwritten.
"""
import json
import os
from pathlib import Path

# backend/  ->  parent of the api/ package this file lives in
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_SETTINGS_FILE = _BACKEND_ROOT / "local.settings.json"


def load_local_settings() -> None:
    """Merge local.settings.json "Values" into os.environ without overwriting existing vars."""
    if not _SETTINGS_FILE.exists():
        return
    try:
        data = json.loads(_SETTINGS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return
    for key, value in data.get("Values", {}).items():
        os.environ.setdefault(key, str(value))
