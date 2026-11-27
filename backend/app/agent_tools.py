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
    dataset_label: str = ""


class JqlInput(BaseModel):
    jql: str
    max_results: int = Field(default=100, ge=1, le=100)


class CommentsInput(BaseModel):
    issue_key: str


class LinksInput(BaseModel):
    issue_key: str


class ReleaseEvidenceInput(BaseModel):
    project_key: str
    dataset_label: str
    release: str
    commit: str
    service: str
    environment: str
    requirement_id: str


class ValidateEvidenceInput(BaseModel):
    evidence_issue_keys: list[str]
    release: str
    commit: str
    service: str
    environment: str
    prompt_version: str = "p7"
    requirement_id: str


def build_tools(
    project_key: str,
    dataset_label: str,
    jira_client: JiraClient | None = None,
) -> list[StructuredTool]:
    jira = jira_client or JiraClient()
    assessment_project_key = project_key
    assessment_dataset_label = dataset_label

    def search_jira(
        project_key: str,
        dataset_label: str,
        jql_suffix: str = "",
        max_results: int = 100,
    ) -> list[dict]:
        if (
            project_key != assessment_project_key
            or dataset_label != assessment_dataset_label
        ):
            raise ValueError("Jira search scope does not match the assessment.")
        return jira.search(
            assessment_project_key,
            assessment_dataset_label,
            jql_suffix,
            max_results,
        )

    def get_jira_issue(issue_key: str, dataset_label: str = "") -> dict:
        if dataset_label and dataset_label != assessment_dataset_label:
            raise ValueError("Jira issue scope does not match the assessment.")
        return jira.get_issue(
            issue_key,
            assessment_dataset_label,
            assessment_project_key,
        )

    def search_jira_issues(jql: str, max_results: int = 100) -> list[dict]:
        return jira.search(
            assessment_project_key,
            assessment_dataset_label,
            jql,
            max_results,
        )

    def get_jira_comments(issue_key: str) -> list[dict]:
        return jira.get_comments(
            issue_key,
            assessment_dataset_label,
            assessment_project_key,
        )

    def get_linked_issues(issue_key: str) -> list[dict]:
        return jira.get_linked_issues(
            issue_key,
            assessment_dataset_label,
            assessment_project_key,
        )

    def get_release_evidence(
        project_key: str,
        dataset_label: str,
        release: str,
        commit: str,
        service: str,
        environment: str,
        requirement_id: str,
    ) -> list[dict]:
        if (
            project_key != assessment_project_key
            or dataset_label != assessment_dataset_label
        ):
            raise ValueError("Jira evidence scope does not match the assessment.")
        return jira.get_release_evidence(
            assessment_project_key,
            assessment_dataset_label,
            release,
            commit,
            service,
            environment,
            requirement_id,
        )

    def validate_evidence(
        evidence_issue_keys: list[str],
        release: str,
        commit: str,
        service: str,
        environment: str,
        prompt_version: str,
        requirement_id: str,
    ) -> dict:
        records = [
            jira.get_issue(key, assessment_dataset_label, assessment_project_key)
            for key in evidence_issue_keys
        ]
        from app.decision_engine import validate_evidence as evaluate
        status, reasoning, evidence, missing, confidence = evaluate(
            requirement_id,
            {
                "release": release,
                "commit": commit,
                "service": service,
                "environment": environment,
                "prompt_version": prompt_version,
            },
            records,
        )
        return {
            "status": status.value,
            "reasoning": reasoning,
            "evidence": evidence,
            "missing_evidence": missing,
            "confidence": confidence,
        }

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
        StructuredTool.from_function(
            name="search_jira_issues",
            description="Search Jira issues using JQL.",
            args_schema=JqlInput,
            func=search_jira_issues,
        ),
        StructuredTool.from_function(
            name="get_jira_comments",
            description="Retrieve all paginated comments for a Jira issue.",
            args_schema=CommentsInput,
            func=get_jira_comments,
        ),
        StructuredTool.from_function(
            name="get_linked_issues",
            description="Retrieve linked Jira issue keys and relationship directions.",
            args_schema=LinksInput,
            func=get_linked_issues,
        ),
        StructuredTool.from_function(
            name="get_release_evidence",
            description="Search Jira evidence associated with release context.",
            args_schema=ReleaseEvidenceInput,
            func=get_release_evidence,
        ),
        StructuredTool.from_function(
            name="validate_evidence",
            description="Validate retrieved Jira evidence against the target release context.",
            args_schema=ValidateEvidenceInput,
            func=validate_evidence,
        ),
    ]
