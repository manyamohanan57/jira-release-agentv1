# Jira Release Evidence Agent

A Next.js and FastAPI application that assesses software-release requirements using evidence retrieved from Jira.

## Structure

- `backend/` - FastAPI API, Jira REST client, LangChain agent tools, importer, and report models
- `frontend/` - Next.js assessment dashboard
- `data/` - place imported or source datasets here
- `reports/` - generated reports

## Setup

1. Copy `backend/.env.example` to `backend/.env`, set your Jira URL/email/API token, select `groq`, `gemini`, or `mistral`, and provide that model provider's API key. Backend configuration is loaded from this file regardless of the launch directory. After changing Jira credentials, restart the backend.
2. Start the backend and frontend as described below.
3. Assess a release using its Jira project key, dataset label, and target release. The backend searches the scoped Jira dataset, then runs a LangChain tool-calling investigation over relevant Jira comments and linked issues.

The model investigates evidence; a deterministic decision engine applies thresholds and calculates the overall release status. Reports include Jira issue/comment references, source record IDs when present, missing evidence, tool traces, and model usage. Confidence is shown as "Not calculated" rather than using an unsupported fixed score. The frontend displays the requirement results in a readable, horizontally scrollable table. Jira descriptions and comments are treated as untrusted input.

If Jira returns HTTP 401, create a new Atlassian API token and update `JIRA_EMAIL` and `JIRA_API_TOKEN` in `backend/.env`.

## Backend

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

On Windows, if PowerShell blocks activation, start Uvicorn directly without activation:

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

API documentation is available at `http://localhost:8000/docs`.

The backend exposes `POST /assessment/run`, `POST /assessment/requirement/{requirement_id}`,
`POST /imports`, `GET /assessment/{assessment_id}`, and `GET /health`. Assessments are
persisted in `backend/assessment_history.db` and reports use only Jira records for evidence.

### Import the dataset

Create a dedicated Jira project first and grant the configured account permission to create
issues, comments, and issue links. Put the supplied dataset at `data/dataset.json`, then,
from the `backend/` directory, import it with:

```powershell
$body = @{
    project_key = "YOUR_PROJECT_KEY"
    dataset_path = "..\data\dataset.json"
    dataset_label = "tyn-release-assessment-v2"
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
    -Uri "http://localhost:8000/imports" `
    -ContentType "application/json" `
    -Body $body
```

The importer preserves source IDs and source issue metadata in Jira issue descriptions,
imports source comments with their fictional actor, role, and timestamp clearly marked in
the comment body, and creates links when both source records are present. Re-running the
import reuses issues marked with the same source ID and avoids duplicating marked comments
and links. The import response reports imported/reused issues, comments, and links.

The workspace does not include the supplied dataset or its release manifest. The importer
supports common JSON shapes (`issues` with optional nested `fields`, `comments`, and
`relationships`/`links`, or top-level `comments` and `relationships`), but its mapping to
the supplied dataset has not been verified. Jira does not allow an importer to impersonate
the fictional source actors; their identities and timestamps are preserved as text, while
Jira's native authorship and timestamps remain those of the importing account.

### Run and export an assessment

`POST /assessment/run` returns a `report_id`, decisions, Jira evidence references, the
investigation trace, execution time, and token counts when the model provider supplies
them. The agent's tool-call activity is also logged in the backend terminal. Download a
saved report as JSON, Markdown, or CSV with:

```powershell
Invoke-WebRequest `
    -Uri "http://localhost:8000/assessment/REPORT_ID/export" `
    -OutFile "..\reports\release-assessment.json"

Invoke-WebRequest `
    -Uri "http://localhost:8000/assessment/REPORT_ID/markdown" `
    -OutFile "..\reports\release-assessment.md"

Invoke-WebRequest `
    -Uri "http://localhost:8000/assessment/REPORT_ID/csv" `
    -OutFile "..\reports\release-assessment.csv"
```

### Design and known limits

- The model gathers Jira evidence through scoped tools. Deterministic checks calculate
  requirement decisions and the overall release status; the model does not invent a
  PASS/FAIL result.
- Agent calls are bounded to control prompt size. Remaining candidate comments are
  retrieved by the assessment pipeline and recorded in the same trace.
- The current 12 requirement names and evidence thresholds are built into the application.
  Manifest-driven requirement/threshold loading remains to be mapped and verified against
  the supplied manifest.
- Generic importer behavior is covered by local tests, but a full 400-issue / 2,059-comment
  Jira import and end-to-end report have not been verified from this workspace because the
  source dataset and manifest are absent.
- AI assistance was used while developing the application and its tests; generated changes
  were reviewed and validated locally. A live Jira/model run is required to validate the
  supplied dataset and provider configuration.

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

## Docker

Create and configure `backend/.env`, then run:

```bash
docker compose up --build
```
