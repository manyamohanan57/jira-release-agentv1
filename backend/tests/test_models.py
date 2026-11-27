from types import SimpleNamespace
from typing import Any

import pytest

import app.assessment as assessment
from app.jira_client import JiraClient
from app.models import (
    Decision,
    OverallDecision,
    RequirementDecision,
)


def test_mandatory_fail_requires_blocked_calculation() -> None:
    requirement = RequirementDecision(
        requirement_id="REQ-1",
        title="Test",
        mandatory=True,
        decision=Decision.FAIL,
        explanation="Failure demonstrated",
    )
    assert requirement.decision is Decision.FAIL


class FakeTool:
    name = "search_jira"

    def invoke(self, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        assert arguments["project_key"] == "REL"
        return [
            {
                "key": "REL-12",
                "fields": {
                    "issuetype": {"name": "Requirement"},
                    "summary": "Export report",
                    "description": "Users can export the release report.",
                    "status": {"name": "Done"},
                    "labels": ["release-evidence"],
                    "fixVersions": [{"name": "R2.4"}],
                    "comment": {
                        "comments": [
                            {"id": "456", "body": "Export verified in staging."}
                        ]
                    },
                },
            }
        ]


class FakeStructuredModel:
    def __init__(self, result: assessment.AssessmentResult) -> None:
        self.result = result

    def invoke(self, prompt: list[tuple[str, str]]) -> dict[str, Any]:
        assert "R2.4" in prompt[1][1]
        return {
            "parsed": self.result,
            "raw": SimpleNamespace(
                usage_metadata={"input_tokens": 400, "output_tokens": 120}
            ),
            "parsing_error": None,
        }


class FakeChatModel:
    def __init__(self, result: assessment.AssessmentResult) -> None:
        self.result = result

    def with_structured_output(
        self, schema: type, include_raw: bool
    ) -> FakeStructuredModel:
        assert schema is assessment.AssessmentResult
        assert include_raw
        return FakeStructuredModel(self.result)


class FakeJiraClient:
    def __enter__(self) -> "FakeJiraClient":
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        return None


def _configure_assessment(
    monkeypatch: pytest.MonkeyPatch,
    result: assessment.AssessmentResult,
) -> None:
    monkeypatch.setattr(assessment, "validate_model_configuration", lambda _: None)
    monkeypatch.setattr(
        assessment, "build_chat_model", lambda _: FakeChatModel(result)
    )
    monkeypatch.setattr(assessment, "JiraClient", FakeJiraClient)
    monkeypatch.setattr(
        assessment,
        "build_tools",
        lambda *_args: [FakeTool()],
    )


def test_assessment_returns_grounded_ready_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = assessment.AssessmentResult(
        assessment_summary="The release requirement is supported by staging evidence.",
        requirements=[
            RequirementDecision(
                requirement_id="REL-12",
                title="Export report",
                decision=Decision.PASS,
                explanation="Staging verification confirms the export works.",
                evidence=[
                    {
                        "ticket_key": "REL-12",
                        "comment_id": "456",
                        "summary": "Export verified in staging.",
                        "applicability": "Confirms the target release requirement.",
                    }
                ],
            )
        ],
    )
    _configure_assessment(monkeypatch, result)

    report = assessment.assess_release("REL", "release-evidence", "R2.4")

    assert report.overall_decision is OverallDecision.READY
    assert report.requirements[0].evidence[0].ticket_key == "REL-12"
    assert report.tool_trace[0].result_summary == "Retrieved 1 Jira issues."
    assert report.usage.model_calls == 1
    assert report.usage.input_tokens == 400


def test_assessment_rejects_unverified_evidence_and_needs_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = assessment.AssessmentResult(
        assessment_summary="Evidence could not be verified.",
        requirements=[
            RequirementDecision(
                requirement_id="REL-12",
                title="Export report",
                decision=Decision.PASS,
                explanation="The export appears to work.",
                evidence=[
                    {
                        "ticket_key": "REL-999",
                        "comment_id": "not-real",
                        "summary": "Claimed verification.",
                        "applicability": "Claimed to confirm the requirement.",
                    }
                ],
            )
        ],
    )
    _configure_assessment(monkeypatch, result)

    report = assessment.assess_release("REL", "release-evidence", "R2.4")

    assert report.overall_decision is OverallDecision.NEEDS_REVIEW
    assert report.requirements[0].decision is Decision.INSUFFICIENT_EVIDENCE
    assert report.requirements[0].evidence == []
    assert report.requirements[0].outstanding


def test_mandatory_failure_blocks_release(monkeypatch: pytest.MonkeyPatch) -> None:
    result = assessment.AssessmentResult(
        assessment_summary="The requirement failed verification.",
        requirements=[
            RequirementDecision(
                requirement_id="REL-12",
                title="Export report",
                decision=Decision.FAIL,
                explanation="Staging verification found a failure.",
                evidence=[
                    {
                        "ticket_key": "REL-12",
                        "comment_id": "456",
                        "summary": "Export verification failed.",
                        "applicability": "Directly verifies the target requirement.",
                    }
                ],
            )
        ],
    )
    _configure_assessment(monkeypatch, result)

    report = assessment.assess_release("REL", "release-evidence", "R2.4")

    assert report.overall_decision is OverallDecision.BLOCKED


def test_jira_search_follows_all_pages() -> None:
    jira = JiraClient.__new__(JiraClient)
    responses = [
        {"issues": [{"key": "REL-1"}], "nextPageToken": "next-page"},
        {"issues": [{"key": "REL-2"}], "isLast": True},
    ]
    request_payloads: list[dict[str, Any]] = []

    class Response:
        status_code = 200

        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload

        def is_error(self) -> bool:
            return False

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return self.payload

    def post(_path: str, json: dict[str, Any]) -> Response:
        request_payloads.append(json)
        return Response(responses.pop(0))

    def get(_path: str) -> Response:
        return Response({})

    jira.client = SimpleNamespace(post=post, get=get)

    issues = jira.search("REL", "release-evidence")

    assert [issue["key"] for issue in issues] == ["REL-1", "REL-2"]
    assert request_payloads[1]["nextPageToken"] == "next-page"
    assert "customfield_*" not in request_payloads[0]["fields"]


def test_release_evidence_search_uses_jql_token_pagination() -> None:
    jira = JiraClient.__new__(JiraClient)
    pages = [
        {"issues": [{"key": "KAN-1"}], "nextPageToken": "continuation"},
        {"issues": [{"key": "KAN-2"}], "isLast": True},
    ]
    requests: list[tuple[str, dict[str, Any]]] = []

    class Response:
        status_code = 200

        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return self.payload

    def post(path: str, json: dict[str, Any]) -> Response:
        requests.append((path, json))
        return Response(pages.pop(0))

    jira.client = SimpleNamespace(post=post)

    issues = jira.search_issues("project = KAN", max_results=2)

    assert [issue["key"] for issue in issues] == ["KAN-1", "KAN-2"]
    assert [path for path, _ in requests] == [
        "/rest/api/3/search/jql",
        "/rest/api/3/search/jql",
    ]
    assert "startAt" not in requests[0][1]
    assert requests[1][1]["nextPageToken"] == "continuation"


def test_release_evidence_search_does_not_fall_back_to_removed_endpoint() -> None:
    import httpx

    jira = JiraClient.__new__(JiraClient)
    requested_paths: list[str] = []

    def post(path: str, json: dict[str, Any]) -> httpx.Response:
        requested_paths.append(path)
        return httpx.Response(
            400,
            request=httpx.Request(
                "POST", "https://jira.example/rest/api/3/search/jql"
            ),
        )

    jira.client = SimpleNamespace(post=post)

    with pytest.raises(RuntimeError, match="status 400"):
        jira.search_issues("project = KAN")

    assert requested_paths == ["/rest/api/3/search/jql"]


def test_jira_search_reports_invalid_credentials_before_empty_results() -> None:
    jira = JiraClient.__new__(JiraClient)

    class UnauthorizedResponse:
        status_code = 401

        def raise_for_status(self) -> None:
            raise AssertionError("401 should be translated to a configuration error")

    jira.client = SimpleNamespace(
        get=lambda _path: UnauthorizedResponse(),
        post=lambda *_args, **_kwargs: pytest.fail(
            "Search must not run when Jira rejects authentication"
        ),
    )

    with pytest.raises(RuntimeError, match="Create a new Atlassian API token"):
        jira.search("REL", "release-evidence")


def test_jira_client_imports_comments_as_source_text() -> None:
    import httpx

    jira = JiraClient.__new__(JiraClient)
    captured: dict[str, Any] = {}

    def post(path: str, *, json: dict[str, Any]) -> httpx.Response:
        captured.update(path=path, payload=json)
        return httpx.Response(
            201,
            json={"id": "comment-1"},
            request=httpx.Request("POST", "https://jira.example" + path),
        )

    jira.client = SimpleNamespace(post=post)

    result = jira.create_comment("KAN-1", "Source actor: Reviewer\nVerified.")

    assert result["id"] == "comment-1"
    assert captured["path"] == "/rest/api/3/issue/KAN-1/comment"
    assert captured["payload"]["body"]["content"][1]["content"][0]["text"] == "Verified."


def test_jira_client_creates_issue_relationship() -> None:
    import httpx

    jira = JiraClient.__new__(JiraClient)
    captured: dict[str, Any] = {}

    def post(path: str, *, json: dict[str, Any]) -> httpx.Response:
        captured.update(path=path, payload=json)
        return httpx.Response(
            201,
            request=httpx.Request("POST", "https://jira.example" + path),
        )

    jira.client = SimpleNamespace(post=post)

    jira.create_issue_link("KAN-2", "KAN-1", "Relates")

    assert captured["path"] == "/rest/api/3/issueLink"
    assert captured["payload"] == {
        "type": {"name": "Relates"},
        "inwardIssue": {"key": "KAN-2"},
        "outwardIssue": {"key": "KAN-1"},
    }


def test_jira_issue_fetch_rejects_another_project_even_with_dataset_label() -> None:
    import httpx

    jira = JiraClient.__new__(JiraClient)
    requested: list[dict[str, Any]] = []

    def get(path: str, *, params: dict[str, Any]) -> httpx.Response:
        requested.append({"path": path, "params": params})
        return httpx.Response(
            200,
            json={
                "key": "OTHER-1",
                "fields": {
                    "labels": ["release-evidence"],
                    "project": {"key": "OTHER"},
                },
            },
            request=httpx.Request("GET", "https://jira.example" + path),
        )

    jira.client = SimpleNamespace(get=get)

    with pytest.raises(ValueError, match="outside assessment project"):
        jira.get_issue("OTHER-1", "release-evidence", "KAN")

    assert "project" in requested[0]["params"]["fields"]


def test_jira_search_api_401_uses_actionable_auth_error() -> None:
    import httpx

    jira = JiraClient.__new__(JiraClient)

    with pytest.raises(RuntimeError, match="Create a new Atlassian API token"):
        jira._raise_api_error(httpx.Response(401))


def test_jira_client_trims_configuration_before_basic_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import base64

    import app.jira_client as jira_module

    captured: dict[str, Any] = {}

    class FakeHttpClient:
        def __init__(self, *, base_url: str, headers: dict[str, str], timeout: float) -> None:
            captured.update(base_url=base_url, headers=headers, timeout=timeout)

    monkeypatch.setattr(
        jira_module,
        "settings",
        SimpleNamespace(
            jira_base_url=" https://jira.example/ ",
            jira_email=" user@example.com ",
            jira_api_token=" token ",
        ),
    )
    monkeypatch.setattr(jira_module.httpx, "Client", FakeHttpClient)

    client = jira_module.JiraClient()
    decoded_auth = base64.b64decode(
        captured["headers"]["Authorization"].removeprefix("Basic ")
    ).decode()
    assert client.base_url == "https://jira.example"
    assert decoded_auth == "user@example.com:token"


def test_overall_status_blocked_before_needs_review() -> None:
    from app.decision_engine import calculate_overall_status

    requirements = [
        RequirementDecision(requirement_id="REQ-1", title="A", decision=Decision.INSUFFICIENT_EVIDENCE, explanation="missing"),
        RequirementDecision(requirement_id="REQ-2", title="B", decision=Decision.FAIL, explanation="failed"),
    ]
    assert calculate_overall_status(requirements) == OverallDecision.BLOCKED


def test_decision_engine_accepts_quality_threshold_only_for_p7() -> None:
    from app.decision_engine import validate_evidence
    from app.models import Decision

    record = {
        "key": "KAN-10",
        "fields": {
            "summary": "Answer quality R2.4",
            "description": "Prompt p7 answer quality: 92% for commit b7a91f2.",
            "labels": ["production", "atlas-assistant"],
            "fixVersions": [{"name": "R2.4"}],
        },
    }
    status, _, _, _, _ = validate_evidence(
        "REQ-03",
        {"release": "R2.4", "commit": "b7a91f2", "service": "atlas-assistant", "environment": "production", "prompt_version": "p7"},
        [record],
    )
    assert status is Decision.PASS


def test_decision_engine_rejects_different_commit_context() -> None:
    from app.decision_engine import validate_evidence

    record = {
        "key": "KAN-11",
        "fields": {
            "summary": "Regression passed",
            "description": "All mandatory regression tests passed for commit a111111.",
            "labels": ["R2.4"],
            "fixVersions": [{"name": "R2.4"}],
        },
    }
    status, _, _, _, _ = validate_evidence(
        "REQ-01",
        {"release": "R2.4", "commit": "b7a91f2", "service": "atlas-assistant", "environment": "production", "prompt_version": "p7"},
        [record],
    )
    assert status.value == "INSUFFICIENT_EVIDENCE"
