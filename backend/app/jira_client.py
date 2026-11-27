import base64
import re
from typing import Any
from urllib.parse import quote

import httpx

from app.config import settings


def _escape_jql_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


class JiraClient:
    AUTHENTICATION_ERROR = (
        "Jira returned HTTP 401: Atlassian rejected the configured email/API token. "
        "Create a new Atlassian API token, set JIRA_EMAIL and JIRA_API_TOKEN in "
        "backend/.env, and restart the backend. Do not share the token."
    )

    def __init__(self) -> None:
        jira_url = settings.jira_base_url.strip()
        jira_email = settings.jira_email.strip()
        jira_api_token = settings.jira_api_token.strip()
        if not jira_url or not jira_email or not jira_api_token:
            raise RuntimeError(
                "Jira is not configured. Set JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN."
            )

        credentials = f"{jira_email}:{jira_api_token}"
        encoded = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
        self.base_url = jira_url.rstrip("/")
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": f"Basic {encoded}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def __enter__(self) -> "JiraClient":
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    def verify_access(self, project_key: str) -> None:
        auth_response = self.client.get("/rest/api/3/myself")
        if auth_response.status_code == 401:
            raise RuntimeError(self.AUTHENTICATION_ERROR)
        if auth_response.status_code == 403:
            raise RuntimeError(
                "The configured Jira account cannot access its user profile. "
                "Check the account and API permissions."
            )
        auth_response.raise_for_status()

        encoded_project_key = quote(project_key, safe="")
        project_response = self.client.get(
            f"/rest/api/3/project/{encoded_project_key}"
        )
        if project_response.status_code == 401:
            raise RuntimeError(self.AUTHENTICATION_ERROR)
        if project_response.status_code == 403:
            raise RuntimeError(
                f"The configured Jira account cannot access project '{project_key}'."
            )
        if project_response.status_code == 404:
            raise ValueError(
                f"Jira project '{project_key}' was not found or is not visible to "
                "the configured account."
            )
        project_response.raise_for_status()

    def search(
        self,
        project_key: str,
        dataset_label: str,
        jql_suffix: str = "",
        max_results: int = 100,
    ) -> list[dict[str, Any]]:
        self.verify_access(project_key)
        escaped_project = project_key.replace("\\", "\\\\").replace('"', '\\"')
        escaped_label = dataset_label.replace("\\", "\\\\").replace('"', '\\"')
        jql = f'project = "{escaped_project}" AND labels = "{escaped_label}"'
        if jql_suffix:
            jql = f"{jql} AND ({jql_suffix})"

        issues: list[dict[str, Any]] = []
        next_page_token: str | None = None
        while True:
            payload: dict[str, Any] = {
                "jql": jql,
                "fields": [
                    "summary",
                    "description",
                    "status",
                    "labels",
                    "issuetype",
                    "issuelinks",
                    "fixVersions",
                    "comment",
                ],
                "maxResults": max_results,
            }
            if next_page_token:
                payload["nextPageToken"] = next_page_token

            response = self.client.post(
                "/rest/api/3/search/jql",
                json=payload,
            )
            self._raise_api_error(response)
            page = response.json()
            issues.extend(page.get("issues", []))

            next_page_token = page.get("nextPageToken")
            if not next_page_token or page.get("isLast", False):
                return issues

    def get_issue(
        self,
        issue_key: str,
        dataset_label: str,
        project_key: str | None = None,
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*-\d+", issue_key):
            raise ValueError(f"Invalid Jira issue key: {issue_key}")
        response = self.client.get(
            f"/rest/api/3/issue/{quote(issue_key, safe='')}",
            params={
                "fields": (
                    "summary,description,status,labels,issuetype,issuelinks,"
                    "fixVersions,comment,project"
                )
            },
        )
        self._raise_api_error(response)
        issue = response.json()

        labels = issue.get("fields", {}).get("labels", [])
        if dataset_label and dataset_label not in labels:
            raise ValueError(
                f"{issue_key} does not belong to dataset label {dataset_label}"
            )
        issue_project = issue.get("fields", {}).get("project", {}).get("key")
        if project_key and issue_project != project_key:
            raise ValueError(
                f"{issue_key} is outside assessment project '{project_key}'."
            )
        return issue

    def search_issues(self, jql: str, max_results: int = 100) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        next_page_token: str | None = None
        while len(issues) < max_results:
            payload = {
                "jql": jql,
                "maxResults": min(100, max_results - len(issues)),
                "fields": ["summary", "description", "status", "labels", "issuetype", "assignee", "reporter", "fixVersions", "comment", "issuelinks"],
            }
            if next_page_token:
                payload["nextPageToken"] = next_page_token

            response = self.client.post("/rest/api/3/search/jql", json=payload)
            self._raise_api_error(response)
            page = response.json()
            issues.extend(page.get("issues", []))
            next_page_token = page.get("nextPageToken")
            if not next_page_token or page.get("isLast", False):
                break
        return issues[:max_results]

    def get_comments(
        self,
        issue_key: str,
        dataset_label: str = "",
        project_key: str | None = None,
    ) -> list[dict[str, Any]]:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*-\d+", issue_key):
            raise ValueError(f"Invalid Jira issue key: {issue_key}")
        if dataset_label:
            self.get_issue(issue_key, dataset_label, project_key)

        comments: list[dict[str, Any]] = []
        start_at = 0
        while True:
            response = self.client.get(
                f"/rest/api/3/issue/{quote(issue_key, safe='')}/comment",
                params={"startAt": start_at, "maxResults": 100},
            )
            self._raise_api_error(response)
            page = response.json()
            comments.extend(page.get("comments", []))
            start_at += len(page.get("comments", []))
            if not page.get("comments") or start_at >= page.get("total", start_at):
                break
        return comments

    def get_linked_issues(
        self,
        issue_key: str,
        dataset_label: str = "",
        project_key: str | None = None,
    ) -> list[dict[str, Any]]:
        issue = self.get_issue(issue_key, dataset_label, project_key)
        links = issue.get("fields", {}).get("issuelinks", [])
        linked: list[dict[str, Any]] = []
        for link in links:
            if "outwardIssue" in link:
                linked.append({
                    "issue_key": link["outwardIssue"].get("key"),
                    "link_type": link.get("type", {}).get("name", ""),
                    "direction": "outward",
                })
            if "inwardIssue" in link:
                linked.append({
                    "issue_key": link["inwardIssue"].get("key"),
                    "link_type": link.get("type", {}).get("name", ""),
                    "direction": "inward",
                })
        return linked

    def get_release_evidence(
        self,
        project_key: str,
        dataset_label: str,
        release: str,
        commit: str,
        service: str,
        environment: str,
        requirement_id: str,
    ) -> list[dict[str, Any]]:
        terms = " AND ".join(
            f'text ~ "{_escape_jql_value(value)}"'
            for value in (release, commit, service, environment, requirement_id)
            if value
        )
        return self.search(project_key, dataset_label, terms, 100)

    def _raise_api_error(self, response: httpx.Response) -> None:
        if response.status_code == 401:
            raise RuntimeError(self.AUTHENTICATION_ERROR)
        if response.status_code == 403:
            raise RuntimeError("The configured Jira account cannot access this resource.")
        if response.status_code == 404:
            raise ValueError("The requested Jira issue or resource was not found.")
        if response.status_code == 429:
            raise RuntimeError("Jira API rate limit exceeded. Retry the assessment later.")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"Jira API request failed with status {exc.response.status_code}.") from exc

    def create_issue(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post("/rest/api/3/issue", json=payload)
        self._raise_api_error(response)
        return response.json()

    def create_comment(self, issue_key: str, body: str) -> dict[str, Any]:
        paragraphs = body.splitlines() or [""]
        response = self.client.post(
            f"/rest/api/3/issue/{quote(issue_key, safe='')}/comment",
            json={
                "body": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": paragraph}],
                        }
                        for paragraph in paragraphs
                    ],
                }
            },
        )
        self._raise_api_error(response)
        return response.json()

    def create_issue_link(
        self,
        inward_issue_key: str,
        outward_issue_key: str,
        link_type: str = "Relates",
    ) -> None:
        response = self.client.post(
            "/rest/api/3/issueLink",
            json={
                "type": {"name": link_type},
                "inwardIssue": {"key": inward_issue_key},
                "outwardIssue": {"key": outward_issue_key},
            },
        )
        self._raise_api_error(response)

    def close(self) -> None:
        self.client.close()
