import pytest

from app.decision_engine import validate_evidence
from app.models import Decision


def _record(summary: str, comment: str) -> dict:
    return {
        "key": "KAN-191",
        "fields": {
            "summary": summary,
            "description": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "Release: R2.4"}],
                    }
                ],
            },
            "labels": ["release-evidence"],
            "comment": {
                "comments": [
                    {
                        "id": "42",
                        "body": {
                            "type": "doc",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {"type": "text", "text": comment}
                                    ],
                                }
                            ],
                        },
                    }
                ]
            },
        },
    }


def _context() -> dict[str, str]:
    return {
        "release": "R2.4",
        "commit": "b7a91f2",
        "service": "atlas-assistant",
        "environment": "production",
        "prompt_version": "p7",
    }


def test_regression_pass_uses_comment_evidence_and_formats_adf() -> None:
    status, _, evidence, _, _ = validate_evidence(
        "REQ-01",
        _context(),
        [
            _record(
                "Regression tests: atlas-assistant R2.4",
                "All mandatory regression tests passed for commit b7a91f2 in production.",
            )
        ],
    )

    assert status is Decision.PASS
    assert evidence[0]["comment_id"] == "42"
    assert "type" not in evidence[0]["evidence_details"]
    assert "All mandatory regression tests passed" in evidence[0]["evidence_details"]


def test_long_comment_excerpt_keeps_the_decisive_result() -> None:
    comment = (
        "Context and setup notes. " * 100
        + "All mandatory regression tests passed for commit b7a91f2 in production."
    )
    status, _, evidence, _, _ = validate_evidence(
        "REQ-01",
        _context(),
        [_record("Regression tests: atlas-assistant R2.4", comment)],
    )

    assert status is Decision.PASS
    assert "All mandatory regression tests passed" in evidence[0]["evidence_details"]


def test_unrelated_service_and_ticket_status_do_not_prove_requirement() -> None:
    record = _record(
        "Regression tests: warehouse-agent R2.4",
        "All mandatory regression tests passed for commit b7a91f2 in production.",
    )
    record["fields"]["status"] = {"name": "Done"}

    status, _, evidence, _, _ = validate_evidence(
        "REQ-01",
        _context(),
        [record],
    )

    assert status is Decision.INSUFFICIENT_EVIDENCE
    assert evidence == []


def test_streaming_no_duplicates_or_missing_messages_is_not_a_failure() -> None:
    status, _, _, _, _ = validate_evidence(
        "REQ-12",
        _context(),
        [
            _record(
                "Streaming verification: atlas-assistant R2.4",
                "Production streaming check for commit b7a91f2 confirmed no duplicate or missing final messages.",
            )
        ],
    )

    assert status is Decision.PASS


@pytest.mark.parametrize(
    ("requirement_id", "summary", "comment"),
    [
        (
            "REQ-03",
            "Answer quality: atlas-assistant R2.4",
            "Prompt p7 answer quality was 89% for commit b7a91f2 in production.",
        ),
        (
            "REQ-04",
            "Response latency: atlas-assistant R2.4",
            "p95 latency was 2.5 seconds for commit b7a91f2 in production.",
        ),
        (
            "REQ-05",
            "Model usage cost: atlas-assistant R2.4",
            "Cost per successful request was $0.013 for commit b7a91f2 in production.",
        ),
    ],
)
def test_objective_threshold_breach_is_a_failure(
    requirement_id: str,
    summary: str,
    comment: str,
) -> None:
    status, _, _, _, _ = validate_evidence(
        requirement_id,
        _context(),
        [_record(summary, comment)],
    )

    assert status is Decision.FAIL


def test_log_redaction_requires_sensitive_data_and_qa_verification() -> None:
    status, _, _, _, _ = validate_evidence(
        "REQ-07",
        _context(),
        [
            _record(
                "Log redaction: atlas-assistant R2.4",
                "QA verified sensitive customer data is redacted from production logs for commit b7a91f2.",
            )
        ],
    )

    assert status is Decision.PASS


def test_no_cross_customer_exposure_is_not_interpreted_as_a_failure() -> None:
    status, _, _, _, _ = validate_evidence(
        "REQ-02",
        _context(),
        [
            _record(
                "Customer document isolation: atlas-assistant R2.4",
                "No cross-customer document exposure found in production for commit b7a91f2.",
            )
        ],
    )

    assert status is Decision.PASS


def test_context_from_separate_comments_cannot_be_combined_into_a_pass() -> None:
    record = _record(
        "Regression tests: atlas-assistant R2.4",
        "All mandatory regression tests passed for commit a111111 in production.",
    )
    record["fields"]["comment"]["comments"].append(
        {
            "id": "43",
            "body": "Additional run was for commit b7a91f2 in production.",
        }
    )

    status, _, evidence, _, _ = validate_evidence(
        "REQ-01",
        _context(),
        [record],
    )

    assert status is Decision.INSUFFICIENT_EVIDENCE
    assert [item["comment_id"] for item in evidence] == ["43"]


def test_requirement_definition_is_not_used_as_outcome_evidence() -> None:
    record = _record(
        "Regression tests: atlas-assistant R2.4",
        "All mandatory regression tests must pass for commit b7a91f2 in production.",
    )
    record["fields"]["issuetype"] = {"name": "Requirement"}
    record["fields"]["description"] = (
        "Kind: requirement\nRelease: R2.4\nAcceptance criteria: All mandatory "
        "regression tests must pass."
    )

    status, _, evidence, missing, confidence = validate_evidence(
        "REQ-01",
        _context(),
        [record],
    )

    assert status is Decision.INSUFFICIENT_EVIDENCE
    assert evidence == []
    assert missing
    assert confidence is None


def test_requirement_threshold_is_not_a_measured_failure() -> None:
    record = _record(
        "Response latency requirement: atlas-assistant R2.4",
        "The p95 latency target must be at most 2.0 seconds for commit "
        "b7a91f2 in production.",
    )
    record["fields"]["issuetype"] = {"name": "Requirement"}
    record["fields"]["description"] = "Kind: requirement\nRelease: R2.4"

    status, _, _, _, _ = validate_evidence("REQ-04", _context(), [record])

    assert status is Decision.INSUFFICIENT_EVIDENCE


def test_empty_jira_issue_is_not_cited_as_evidence() -> None:
    record = _record("Regression: atlas-assistant R2.4", "")
    record["fields"]["description"] = ""
    record["fields"]["comment"]["comments"] = []

    status, _, evidence, missing, _ = validate_evidence(
        "REQ-01",
        _context(),
        [record],
    )

    assert status is Decision.INSUFFICIENT_EVIDENCE
    assert evidence == []
    assert missing


def test_cost_failure_reports_measured_value_threshold_and_source_id() -> None:
    record = _record(
        "Model usage cost: atlas-assistant R2.4",
        "Mean model cost was USD 0.018 per successful request for release R2.4, "
        "service atlas-assistant, commit b7a91f2 in production.",
    )
    record["fields"]["description"] = (
        "Release: R2.4\nSource ID: REC-5716"
    )

    status, reasoning, evidence, _, confidence = validate_evidence(
        "REQ-05",
        _context(),
        [record],
    )

    assert status is Decision.FAIL
    assert "USD 0.018" in reasoning
    assert "USD 0.012" in reasoning
    assert evidence[0]["source_identifier"] == "REC-5716"
    assert evidence[0]["source_type"] == "Jira comment"
    assert evidence[0]["comment_id"] == "42"
    assert confidence is None


@pytest.mark.parametrize(
    ("comment", "expected_measurement"),
    [
        (
            "19/20 regression tests passed for commit b7a91f2 in production.",
            "19/20 regression tests passed",
        ),
        (
            "1/20 regression tests failed for commit b7a91f2 in production.",
            "1/20 regression tests failed",
        ),
    ],
)
def test_regression_count_failure_explains_observed_count(
    comment: str,
    expected_measurement: str,
) -> None:
    status, reasoning, _, _, _ = validate_evidence(
        "REQ-01",
        _context(),
        [_record("Regression run: atlas-assistant R2.4", comment)],
    )

    assert status is Decision.FAIL
    assert expected_measurement in reasoning


def test_document_parsing_failure_reports_count_and_required_total() -> None:
    status, reasoning, _, _, _ = validate_evidence(
        "REQ-10",
        _context(),
        [
            _record(
                "Document parsing: atlas-assistant R2.4",
                "59/60 documents passed parsing for commit b7a91f2 in production.",
            )
        ],
    )

    assert status is Decision.FAIL
    assert "59/60 documents passed" in reasoning
    assert "60/60 documents must pass" in reasoning


@pytest.mark.parametrize(
    ("requirement_id", "summary", "comment", "expected_measurement", "threshold"),
    [
        (
            "REQ-03",
            "Answer quality: atlas-assistant R2.4",
            "Prompt p7 answer quality was 93% for commit b7a91f2 in production.",
            "93%",
            "at least 90%",
        ),
        (
            "REQ-04",
            "Response latency: atlas-assistant R2.4",
            "p95 latency was 1.8 seconds for commit b7a91f2 in production.",
            "1.8 seconds",
            "at most 2.0 seconds",
        ),
    ],
)
def test_numeric_pass_explains_measurement_and_acceptance_limit(
    requirement_id: str,
    summary: str,
    comment: str,
    expected_measurement: str,
    threshold: str,
) -> None:
    status, reasoning, _, _, _ = validate_evidence(
        requirement_id,
        _context(),
        [_record(summary, comment)],
    )

    assert status is Decision.PASS
    assert expected_measurement in reasoning
    assert threshold in reasoning


def test_security_approval_requires_named_security_approver_and_scope() -> None:
    approved = _record(
        "Security approval: atlas-assistant R2.4",
        "Asha Rao, Security Owner, approved release R2.4 for atlas-assistant "
        "commit b7a91f2 in production.",
    )
    status, _, _, _, _ = validate_evidence("REQ-06", _context(), [approved])
    assert status is Decision.PASS

    wrong_approver = _record(
        "Security approval: atlas-assistant R2.4",
        "Asha Rao provided security test results; approved by Dev Lead Bob for "
        "release R2.4, atlas-assistant commit b7a91f2 in production.",
    )
    status, _, _, _, _ = validate_evidence("REQ-06", _context(), [wrong_approver])
    assert status is Decision.INSUFFICIENT_EVIDENCE


@pytest.mark.parametrize(
    "comment",
    [
        "All mandatory regression tests passed for commit b7a91f2.",
        "All mandatory regression tests passed in production.",
    ],
)
def test_pass_requires_commit_and_environment_applicability(comment: str) -> None:
    status, _, _, _, _ = validate_evidence(
        "REQ-01",
        _context(),
        [
            _record(
                "Regression tests: atlas-assistant R2.4",
                comment,
            )
        ],
    )

    assert status is Decision.INSUFFICIENT_EVIDENCE
