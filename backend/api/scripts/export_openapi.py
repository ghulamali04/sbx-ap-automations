"""Write the FastAPI schema used by clients and CI to contracts/openapi.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BACKEND_ROOT))

from api.main import app

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_OUTPUT_FILE = _REPOSITORY_ROOT / "contracts" / "openapi.json"


def main() -> None:
    schema = app.openapi()
    _OUTPUT_FILE.write_text(
        json.dumps(schema, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {_OUTPUT_FILE}")


if __name__ == "__main__":
    main()
