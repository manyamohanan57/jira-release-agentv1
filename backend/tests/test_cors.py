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
