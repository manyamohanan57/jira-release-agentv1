from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

from app.agent_workflow import MAX_AGENT_TOOL_CALLS, run_jira_investigation


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
                        "args": {"issue_key": "KAN-1"},
                        "id": "comment-call",
                        "type": "tool_call",
                    }
                ],
            )
        return AIMessage(content="Inspected the QA comment for KAN-1.")


class FakeChatModel:
    def __init__(self) -> None:
        self.bound = FakeBoundModel()

    def bind_tools(self, _tools: list[StructuredTool]) -> FakeBoundModel:
        return self.bound


def test_investigation_agent_invokes_jira_comment_tool(caplog: Any) -> None:
    comments = [
        {
            "id": "101",
            "body": "QA: all mandatory regression tests passed.",
        }
    ]
    comment_tool = StructuredTool.from_function(
        name="get_jira_comments",
        description="Read Jira comments",
        func=lambda issue_key: comments if issue_key == "KAN-1" else [],
    )
    issue = {
        "key": "KAN-1",
        "fields": {
            "summary": "Regression tests: atlas-assistant R2.4",
            "description": "Review the comments for test results.",
            "labels": ["release-evidence"],
        },
    }

    with caplog.at_level("INFO", logger="app.agent_workflow"):
        records, traces, model_calls, _, _ = run_jira_investigation(
            FakeChatModel(),
            [comment_tool],
            "KAN",
            "release-evidence",
            {
                "release": "R2.4",
                "commit": "b7a91f2",
                "service": "atlas-assistant",
                "environment": "production",
                "prompt_version": "p7",
            },
            [issue],
        )

    assert records["KAN-1"]["fields"]["comment"]["comments"] == comments
    assert traces[0].tool == "get_jira_comments"
    assert model_calls == 2
    assert "calling tool get_jira_comments" in caplog.text


def test_investigation_stops_at_tool_call_budget() -> None:
    class ManyCallsBoundModel:
        def __init__(self) -> None:
            self.calls = 0

        def invoke(self, _messages: list[Any]) -> AIMessage:
            self.calls += 1
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_jira_comments",
                        "args": {"issue_key": "KAN-1"},
                        "id": f"comment-call-{index}",
                        "type": "tool_call",
                    }
                    for index in range(MAX_AGENT_TOOL_CALLS + 2)
                ],
            )

    bound_model = ManyCallsBoundModel()

    class ManyCallsChatModel:
        def bind_tools(self, _tools: list[StructuredTool]) -> ManyCallsBoundModel:
            return bound_model

    comment_tool = StructuredTool.from_function(
        name="get_jira_comments",
        description="Read Jira comments",
        func=lambda issue_key: [],
    )
    issue = {
        "key": "KAN-1",
        "fields": {
            "summary": "Regression tests: atlas-assistant R2.4",
            "description": "Review the comments for test results.",
            "labels": ["release-evidence"],
        },
    }

    _, traces, model_calls, _, _ = run_jira_investigation(
        ManyCallsChatModel(),
        [comment_tool],
        "KAN",
        "release-evidence",
        {"service": "atlas-assistant", "release": "R2.4"},
        [issue],
    )

    assert bound_model.calls == 1
    assert model_calls == 1
    assert len(traces) == MAX_AGENT_TOOL_CALLS


def test_agent_search_is_scoped_bounded_and_logged(caplog: Any) -> None:
    class SearchBoundModel:
        def __init__(self) -> None:
            self.calls = 0

        def invoke(self, _messages: list[Any]) -> AIMessage:
            self.calls += 1
            if self.calls == 1:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "search_jira",
                            "args": {
                                "project_key": "OTHER",
                                "dataset_label": "unscoped",
                                "max_results": 100,
                            },
                            "id": "search-call",
                            "type": "tool_call",
                        }
                    ],
                )
            return AIMessage(content="Found a scoped candidate issue.")

    bound_model = SearchBoundModel()

    class SearchChatModel:
        def bind_tools(self, _tools: list[StructuredTool]) -> SearchBoundModel:
            return bound_model

    search_arguments: list[dict[str, Any]] = []
    search_issue = {
        "key": "KAN-2",
        "fields": {
            "summary": "Regression tests: atlas-assistant R2.4",
            "description": "Candidate evidence.",
            "labels": ["release-evidence"],
        },
    }

    def search_jira(
        project_key: str,
        dataset_label: str,
        max_results: int,
    ) -> list[dict[str, Any]]:
        search_arguments.append(
            {
                "project_key": project_key,
                "dataset_label": dataset_label,
                "max_results": max_results,
            }
        )
        return [search_issue]

    search_tool = StructuredTool.from_function(
        name="search_jira",
        description="Search scoped Jira records",
        func=search_jira,
    )
    initial_issue = {
        "key": "KAN-1",
        "fields": {"summary": "Release R2.4", "labels": ["release-evidence"]},
    }

    with caplog.at_level("INFO", logger="app.agent_workflow"):
        records, traces, _, _, _ = run_jira_investigation(
            SearchChatModel(),
            [search_tool],
            "KAN",
            "release-evidence",
            {
                "release": "R2.4",
                "commit": "b7a91f2",
                "service": "atlas-assistant",
                "environment": "production",
                "prompt_version": "p7",
            },
            [initial_issue],
        )

    assert search_arguments == [
        {
            "project_key": "KAN",
            "dataset_label": "release-evidence",
            "max_results": 8,
        }
    ]
    assert records["KAN-2"] == search_issue
    assert traces[0].tool == "search_jira"
    assert "calling tool search_jira" in caplog.text
