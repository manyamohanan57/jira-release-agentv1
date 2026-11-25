# Jira Release Evidence Agent

A Next.js and FastAPI application that assesses software-release requirements using evidence retrieved from Jira.

## Structure

- `backend/` - FastAPI API, Jira REST client, LangChain agent tools, importer, and report models
- `frontend/` - Next.js assessment dashboard
- `data/` - place imported or source datasets here
- `reports/` - generated reports

## Setup

1. Copy `.env.example` to `.env`, select `groq`, `gemini`, or `mistral`, and provide the matching API key.
2. Start the backend and frontend as described below.
3. Import a dataset once, then assess it by project key, dataset label, and target release.

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

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

## Docker

Create `.env`, then run:

```bash
docker compose up --build
```
