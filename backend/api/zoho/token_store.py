"""
Minimal file-backed store for Zoho OAuth tokens.

The in-memory dict this replaces did not survive process restarts — including the
automatic worker restarts uvicorn does under `--reload` — so a token saved in
/callback vanished before /portals could read it. Persisting to a small JSON file
makes the token the source of truth across reloads and restarts.

This is deliberately simple (single-user, local dev / discovery). Production
multi-portal use should move to a real store (DB / Key Vault) keyed per account.
"""
import json
from pathlib import Path

# backend/  ->  three levels up from api/zoho/token_store.py
_TOKEN_FILE = Path(__file__).resolve().parents[2] / ".zoho_tokens.json"


def save_tokens(tokens: dict) -> None:
    _TOKEN_FILE.write_text(json.dumps(tokens, indent=2))


def load_tokens() -> dict:
    if not _TOKEN_FILE.exists():
        return {}
    try:
        return json.loads(_TOKEN_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
