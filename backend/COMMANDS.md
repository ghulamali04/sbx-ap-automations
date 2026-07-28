# Task Summary — Commands Cheat-Sheet

Run/QA commands for the Task Summary automation. Converted from
`commands - aiutomation.docx` with macOS paths.

All commands assume:

- **Working directory:** `backend/`
- **Virtualenv:** `.venv` (use `.venv/bin/python`, or `source .venv/bin/activate` first)
- **Azure auth:** `az login` done (local summaries use `AzureCliCredential`)

> Paths below are macOS. On Windows swap `.venv/bin/python` → `.venv\Scripts\python.exe`
> and `/` → `\` in script paths.

## Run the API locally

```bash
.venv/bin/python -m uvicorn api.main:app --port 8000
```

Or via the Functions host (serves routes under `/api/*`, plus the queue triggers):

```bash
func start
```

## Run the automated tests

```bash
.venv/bin/python -m unittest discover -s tests -p "test_*.py" -v
```

Or with pytest:

```bash
.venv/bin/python -m pytest tests/ -q
```

## Generate a sample PDF (canned data, no network)

```bash
.venv/bin/python api/scripts/generate_sample_task_summary.py
```

Writes `output/pdf/sample-task-summary-report.pdf` and prints the path.

## Generate a PDF from live Zoho + Azure data

Positional arg is the **Head Client ID**. Renders only (no email) unless
`--requestor-email` is given.

```bash
# Client 53
.venv/bin/python api/scripts/generate_actual_task_summary.py 53

# Head Client 3
.venv/bin/python api/scripts/generate_actual_task_summary.py 3
```

Writes `output/pdf/actual-task-summary-report.pdf` by default.

## Generate and email the PDF

Passing `--requestor-email` delivers the PDF through the configured Power
Automate flow (`TASK_SUMMARY_WEBHOOK_URL`, falling back to
`POWER_AUTOMATE_WEBHOOK_URL`).

```bash
.venv/bin/python api/scripts/generate_actual_task_summary.py 53 --requestor-email recipient@example.com
```

### Optional flags (`generate_actual_task_summary.py`)

| Flag | Effect |
|---|---|
| `--requestor-email <addr>` | Send the PDF via the flow. Omit to render only. |
| `--webhook-url <url>` | Override the Power Automate webhook for this run. |
| `--output <path>` | Write the PDF somewhere other than the default. |
| `--active-only` | Search only Zoho projects marked active. |

> **Side effects:** the `generate_actual_*` commands call live Zoho + Azure
> OpenAI, and `--requestor-email` sends a real email. These are not isolated
> tests.
