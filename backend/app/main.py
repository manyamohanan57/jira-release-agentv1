from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.assessment import assess_release, assess_release_context
from app.importer import import_dataset
from app.models import (
    AssessmentRequest,
    ImportRequest,
    ImportResult,
    ReleaseReadinessReport,
)
from app.models import MANDATORY_REQUIREMENTS
from app.report_renderer import render_csv_report, render_markdown_report
from app.storage import AssessmentStore

app = FastAPI(
    title="Jira Release Evidence Agent",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = AssessmentStore()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/imports", response_model=ImportResult)
def import_records(request: ImportRequest) -> ImportResult:
    try:
        result = import_dataset(
            request.dataset_path,
            request.project_key,
            request.dataset_label,
        )
        return ImportResult(
            imported=result.imported,
            skipped=result.skipped,
            project_key=request.project_key,
            dataset_label=request.dataset_label,
            reused=result.reused,
            comments_imported=result.comments_imported,
            links_imported=result.links_imported,
            relationships_skipped=result.relationships_skipped,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/assessments", response_model=ReleaseReadinessReport)
def create_assessment(request: AssessmentRequest) -> ReleaseReadinessReport:
    try:
        project_key = request.effective_project_key
        if not project_key:
            raise ValueError("A Jira project key is required.")
        report = assess_release_context(
            project_key,
            request.dataset_label,
            request.effective_release,
            request.commit,
            request.service,
            request.environment,
            request.prompt_version,
        )
        store.save(report)
        return report
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/assessment/run", response_model=ReleaseReadinessReport)
def run_assessment(request: AssessmentRequest) -> ReleaseReadinessReport:
    return create_assessment(request)


@app.post("/assessment/requirement/{requirement_id}", response_model=ReleaseReadinessReport)
def run_requirement(requirement_id: str, request: AssessmentRequest) -> ReleaseReadinessReport:
    if requirement_id not in MANDATORY_REQUIREMENTS:
        raise HTTPException(status_code=404, detail=f"Unknown requirement: {requirement_id}")
    report = run_assessment(request)
    report.requirements = [
        requirement for requirement in report.requirements
        if getattr(requirement, "requirement_id", None) == requirement_id
    ]
    report.assessment_summary = f"Individual assessment for {requirement_id}."
    return report


@app.get("/assessment/{assessment_id}", response_model=ReleaseReadinessReport)
def get_assessment(assessment_id: str) -> ReleaseReadinessReport:
    report = store.get(assessment_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Assessment not found.")
    return report


@app.get("/assessment/{assessment_id}/export")
def export_assessment(assessment_id: str) -> JSONResponse:
    report = store.get(assessment_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Assessment not found.")
    return JSONResponse(
        content=report.model_dump(mode="json"),
        headers={
            "Content-Disposition": (
                f'attachment; filename="release-assessment-{report.report_id}.json"'
            )
        },
    )


@app.get("/assessment/{assessment_id}/markdown")
def export_assessment_markdown(assessment_id: str) -> Response:
    report = store.get(assessment_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Assessment not found.")
    return Response(
        content=render_markdown_report(report),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="release-assessment-{report.report_id}.md"'
            )
        },
    )


@app.get("/assessment/{assessment_id}/csv")
def export_assessment_csv(assessment_id: str) -> Response:
    report = store.get(assessment_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Assessment not found.")
    return Response(
        content=render_csv_report(report),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="release-assessment-{report.report_id}.csv"'
            )
        },
    )
