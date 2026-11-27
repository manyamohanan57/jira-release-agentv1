from datetime import datetime, timezone

from fastapi.testclient import TestClient

import app.main as main
from app.models import ReleaseReadinessReport, UsageMetrics

from app.main import app


def test_assessment_preflight_allows_local_frontend_origins() -> None:
    client = TestClient(app)
    for origin in ("http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3001"):
        response = client.options(
            "/assessment/run",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin


def test_assessment_preflight_rejects_non_local_origins() -> None:
    response = TestClient(app).options(
        "/assessment/run",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 400


def test_assessment_export_returns_saved_report_json(
    monkeypatch,
) -> None:
    report = ReleaseReadinessReport(
        report_id="test-report",
        usage=UsageMetrics(execution_time_ms=123),
        generated_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(main.store, "get", lambda _assessment_id: report)

    response = TestClient(app).get("/assessment/test-report/export")

    assert response.status_code == 200
    assert response.json()["report_id"] == "test-report"
    assert "release-assessment-test-report.json" in response.headers["content-disposition"]


def test_assessment_markdown_export_returns_a_table(monkeypatch) -> None:
    report = ReleaseReadinessReport(
        report_id="test-report",
        requirements=[
            {
                "requirement_id": "REQ-05",
                "requirement_name": "Model Usage Cost",
                "status": "FAIL",
                "reasoning": "Observed value exceeded threshold.",
                "evidence": [
                    {
                        "issue_key": "KAN-383",
                        "source_identifier": "REC-5716",
                        "comment_id": "11896",
                        "source_type": "Jira comment",
                        "summary": "Cost run",
                        "evidence_details": "Measured USD 0.018.",
                    }
                ],
                "missing_evidence": [],
                "confidence": None,
            }
        ],
        usage=UsageMetrics(execution_time_ms=123),
        generated_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(main.store, "get", lambda _assessment_id: report)

    response = TestClient(app).get("/assessment/test-report/markdown")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "| Requirement | Status | Assessment | Jira evidence | Missing evidence | Confidence |" in response.text
    assert "KAN-383" in response.text
    assert "REC-5716" in response.text


def test_assessment_csv_export_returns_a_download(monkeypatch) -> None:
    report = ReleaseReadinessReport(
        report_id="test-report",
        usage=UsageMetrics(execution_time_ms=123),
        generated_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(main.store, "get", lambda _assessment_id: report)

    response = TestClient(app).get("/assessment/test-report/csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "release-assessment-test-report.csv" in response.headers["content-disposition"]
    assert response.text.startswith("Requirement,Status,Assessment")
