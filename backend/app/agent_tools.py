from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.jira_client import JiraClient


class SearchInput(BaseModel):
    project_key: str
    dataset_label: str
    jql_suffix: str = Field(
        default="",
        description="Optional Jira JQL expression to narrow the scoped dataset.",
    )
    max_results: int = Field(default=100, ge=1, le=100)


class IssueInput(BaseModel):
    issue_key: str
    dataset_label: str


def build_tools(project_key: str, dataset_label: str) -> list[StructuredTool]:
    jira = JiraClient()

    def search_jira(
        project_key: str,
        dataset_label: str,
        jql_suffix: str = "",
        max_results: int = 100,
    ) -> list[dict]:
        return jira.search(project_key, dataset_label, jql_suffix, max_results)

    def get_jira_issue(issue_key: str, dataset_label: str) -> dict:
        return jira.get_issue(issue_key, dataset_label)

    return [
        StructuredTool.from_function(
            name="search_jira",
            description=(
                "Search Jira tickets only within a project and dataset label. "
                "Use this to find target requirements and relevant linked records."
            ),
            args_schema=SearchInput,
            func=search_jira,
        ),
        StructuredTool.from_function(
            name="get_jira_issue",
            description=(
                "Read one Jira ticket, including its fields and comments, "
                "only after confirming it belongs to the dataset label."
            ),
            args_schema=IssueInput,
            func=get_jira_issue,
        ),
    ]
