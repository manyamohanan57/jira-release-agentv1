$ErrorActionPreference = "Stop"

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    & py -3.12 -m venv (Join-Path $PSScriptRoot ".venv")
}

& $python -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
& $python -m uvicorn app.main:app --reload --port 8000
