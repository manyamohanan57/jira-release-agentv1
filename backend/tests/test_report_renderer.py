import csv
import io
import re
from datetime import datetime, timezone

from app.models import (
    Decision,
    EvidenceItem,
    OverallDecision,
    ReleaseReadinessReport,
    RequirementResult,
    UsageMetrics,
)
from app.report_renderer import render_markdown_report
from app.report_renderer import render_csv_report


def test_markdown_columns_keep_citations_missing_proof_and_confidence_aligned() -> None:
    report = ReleaseReadinessReport(
        report_id="report-1",
        target_release="R2.4",
        overall_decision=OverallDecision.NEEDS_REVIEW,
        requirements=[
            RequirementResult(
                requirement_id="REQ-03",
                requirement_name="Answer Quality",
                status=Decision.INSUFFICIENT_EVIDENCE,
                reasoning="No applicable answer-quality measurement was found.",
                evidence=[
                    EvidenceItem(
                        issue_key="KAN-385",
                        source_identifier="REC-5716",
                        comment_id="11896",
                        source_type="Jira comment",
                        summary="Prompt verification",
                        evidence_details="Related test record; no measured score.",
                    )
                ],
                missing_evidence=["A p7 answer-quality score is missing."],
                confidence=None,
            )
        ],
        usage=UsageMetrics(execution_time_ms=12),
        generated_at=datetime.now(timezone.utc),
    )

    markdown = render_markdown_report(report)
    row = next(line for line in markdown.splitlines() if line.startswith("| REQ-03"))
    cells = re.split(r"(?<!\\)\|", row)[1:-1]

    assert len(cells) == 6
    assert "INSUFFICIENT_EVIDENCE" in cells[1]
    assert "No applicable answer-quality measurement" in cells[2]
    assert "KAN-385" in cells[3]
    assert "REC-5716" in cells[3]
    assert "A p7 answer-quality score is missing" in cells[4]
    assert "Not calculated" in cells[5]


def test_report_renderers_accept_saved_dict_requirements_and_evidence() -> None:
    report = ReleaseReadinessReport(
        report_id="report-dict",
        requirements=[
            {
                "requirement_id": "REQ-05",
                "requirement_name": "Model Usage Cost",
                "mandatory": True,
                "status": "FAIL",
                "reasoning": "=untrusted formula",
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
        usage=UsageMetrics(execution_time_ms=12),
        generated_at=datetime.now(timezone.utc),
    )

    markdown = render_markdown_report(report)
    csv_rows = list(csv.reader(io.StringIO(render_csv_report(report))))

    assert "KAN-383" in markdown
    assert "REC-5716" in markdown
    assert len(csv_rows) == 2
    assert len(csv_rows[0]) == len(csv_rows[1]) == 11
    assert csv_rows[1][1] == "FAIL"
    assert csv_rows[1][2] == "'=untrusted formula"
    assert "Record ID: REC-5716" in csv_rows[1][3]
