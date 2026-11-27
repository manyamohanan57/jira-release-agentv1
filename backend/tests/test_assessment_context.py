from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

import app.assessment as assessment
from app.models import Decision, OverallDecision


class FakeSearchTool:
    name = "search_jira"

    def __init__(self, issues: list[dict[str, Any]]) -> None:
        self.issues = issues

    def invoke(self, _arguments: dict[str, Any]) -> list[dict[str, Any]]:
        return self.issues


class FakeJiraClient:
    def __enter__(self) -> "FakeJiraClient":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class FakeBoundModel:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, _messages: list[Any]) -> AIMessage:
        self.calls += 1
        if self.calls == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_jira_comments",
                        "args": {"issue_key": "KAN-191"},
                        "id": "get-comments",
                        "type": "tool_call",
                    }
                ],
            )
        return AIMessage(content="Inspected the regression test result comment.")


class FakeChatModel:
    def __init__(self) -> None:
        self.bound = FakeBoundModel()

    def bind_tools(self, _tools: list[StructuredTool]) -> FakeBoundModel:
        return self.bound


def test_context_assessment_runs_tool_agent_and_returns_structured_decisions(
    monkeypatch: Any,
) -> None:
    issue = {
        "key": "KAN-191",
        "fields": {
            "summary": "Regression tests: atlas-assistant R2.4",
            "description": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "QA results are in comments."}
                        ],
                    }
                ],
            },
            "labels": ["release-evidence"],
            "fixVersions": [{"name": "R2.4"}],
            "comment": {"total": 1, "comments": []},
        },
    }
    comments = [
        {
            "id": "42",
            "body": "All mandatory regression tests passed for commit b7a91f2 in production.",
        }
    ]
    search_tool = FakeSearchTool([issue])
    comment_tool = StructuredTool.from_function(
        name="get_jira_comments",
        description="Read Jira comments",
        func=lambda issue_key: comments if issue_key == "KAN-191" else [],
    )
    fake_model = FakeChatModel()
    monkeypatch.setattr(assessment, "validate_model_configuration", lambda _settings: None)
    monkeypatch.setattr(assessment, "build_chat_model", lambda _settings: fake_model)
    monkeypatch.setattr(assessment, "JiraClient", FakeJiraClient)
    monkeypatch.setattr(
        assessment,
        "build_tools",
        lambda *_args: [search_tool, comment_tool],
    )

    report = assessment.assess_release_context("KAN", "release-evidence")

    regression = next(
        item for item in report.requirements if item.requirement_id == "REQ-01"
    )
    assert regression.status is Decision.PASS
    assert regression.evidence[0].comment_id == "42"
    assert report.overall_decision is OverallDecision.NEEDS_REVIEW
    assert report.usage.model_calls == 2
    assert any(trace.tool == "get_jira_comments" for trace in report.tool_trace)


def test_agent_candidates_are_bounded_but_all_target_comments_are_fetched(
    monkeypatch: Any,
) -> None:
    issues = [
        {
            "key": f"KAN-{index}",
            "fields": {
                "summary": f"Regression tests: atlas-assistant R2.4 candidate {index}",
                "description": "QA results are in comments.",
                "labels": ["release-evidence"],
                "fixVersions": [{"name": "R2.4"}],
                "comment": {"total": 1, "comments": []},
            },
        }
        for index in range(1, 21)
    ]
    searched_issues: list[dict[str, Any]] = []
    fetched_comments: list[str] = []

    def run_agent(
        _chat_model: Any,
        _tools: Any,
        _project_key: str,
        _dataset_label: str,
        _context: dict[str, str],
        candidate_issues: list[dict[str, Any]],
    ) -> tuple[dict[str, dict[str, Any]], list[Any], int, int, int]:
        searched_issues.extend(candidate_issues)
        return (
            {str(issue["key"]): issue for issue in candidate_issues},
            [],
            1,
            100,
            20,
        )

    comment_tool = StructuredTool.from_function(
        name="get_jira_comments",
        description="Read Jira comments",
        func=lambda issue_key: (
            fetched_comments.append(issue_key)
            or [{"id": issue_key, "body": "Regression tests passed."}]
        ),
    )
    monkeypatch.setattr(assessment, "validate_model_configuration", lambda _settings: None)
    monkeypatch.setattr(assessment, "build_chat_model", lambda _settings: object())
    monkeypatch.setattr(assessment, "JiraClient", FakeJiraClient)
    monkeypatch.setattr(assessment, "run_jira_investigation", run_agent)
    monkeypatch.setattr(
        assessment,
        "build_tools",
        lambda *_args: [FakeSearchTool(issues), comment_tool],
    )

    report = assessment.assess_release_context("KAN", "release-evidence")

    assert 0 < len(searched_issues) <= len(assessment.MANDATORY_REQUIREMENTS)
    assert set(fetched_comments) == {str(issue["key"]) for issue in issues}
    assert report.usage.model_calls == 1
