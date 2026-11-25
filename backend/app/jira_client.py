import base64
from typing import Any

import httpx

from app.config import settings


class JiraClient:
    def __init__(self) -> None:
        if not settings.jira_base_url or not settings.jira_email or not settings.jira_api_token:
            raise RuntimeError(
                "Jira is not configured. Set JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN."
            )

        credentials = f"{settings.jira_email}:{settings.jira_api_token}"
        encoded = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
        self.base_url = settings.jira_base_url.rstrip("/")
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": f"Basic {encoded}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def search(
        self,
        project_key: str,
        dataset_label: str,
        jql_suffix: str = "",
        max_results: int = 100,
    ) -> list[dict[str, Any]]:
        jql = f'project = "{project_key}" AND labels = "{dataset_label}"'
        if jql_suffix:
            jql = f"{jql} AND ({jql_suffix})"

        response = self.client.post(
            "/rest/api/3/search/jql",
            json={
                "jql": jql,
                "fields": ["summary", "description", "status", "labels", "issuelinks", "fixVersions", "comment", "customfield_*"],
                "maxResults": max_results,
            },
        )
        response.raise_for_status()
        return response.json().get("issues", [])

    def get_issue(self, issue_key: str, dataset_label: str) -> dict[str, Any]:
        response = self.client.get(
            f"/rest/api/3/issue/{issue_key}",
            params={
                "fields": "summary,description,status,labels,issuelinks,fixVersions,comment,customfield_*"
            },
        )
        response.raise_for_status()
        issue = response.json()

        labels = issue.get("fields", {}).get("labels", [])
        if dataset_label not in labels:
            raise ValueError(
                f"{issue_key} does not belong to dataset label {dataset_label}"
            )
        return issue

    def create_issue(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post("/rest/api/3/issue", json=payload)
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        self.client.close()
