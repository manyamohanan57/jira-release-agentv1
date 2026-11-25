from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.assessment import assess_release
from app.importer import import_dataset
from app.models import (
    AssessmentRequest,
    ImportRequest,
    ImportResult,
    ReleaseReadinessReport,
)

app = FastAPI(
    title="Jira Release Evidence Agent",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/imports", response_model=ImportResult)
def import_records(request: ImportRequest) -> ImportResult:
    try:
        imported, skipped = import_dataset(
            request.dataset_path,
            request.project_key,
            request.dataset_label,
        )
        return ImportResult(
            imported=imported,
            skipped=skipped,
            project_key=request.project_key,
            dataset_label=request.dataset_label,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/assessments", response_model=ReleaseReadinessReport)
def create_assessment(request: AssessmentRequest) -> ReleaseReadinessReport:
    try:
        return assess_release(
            request.project_key,
            request.dataset_label,
            request.target_release,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
