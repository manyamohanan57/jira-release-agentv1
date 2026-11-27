import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import app.importer as importer
from app.jira_text import jira_text


class FakeJiraClient:
    def __init__(self) -> None:
        self.issues: list[dict[str, Any]] = []
        self.created_issue_count = 0
        self.created_comment_count = 0
        self.created_link_count = 0

    def search(
        self, _project_key: str, _dataset_label: str, max_results: int = 100
    ) -> list[dict[str, Any]]:
        return deepcopy(self.issues)

    def create_issue(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.created_issue_count += 1
        issue = {
            "key": f"KAN-{self.created_issue_count}",
            "fields": deepcopy(payload["fields"]),
        }
        self.issues.append(issue)
        return {"key": issue["key"]}

    def get_comments(
        self,
        issue_key: str,
        _dataset_label: str,
        _project_key: str,
    ) -> list[dict[str, Any]]:
        issue = next(item for item in self.issues if item["key"] == issue_key)
        return issue.setdefault("comments", [])

    def create_comment(self, issue_key: str, body: str) -> dict[str, Any]:
        self.created_comment_count += 1
        issue = next(item for item in self.issues if item["key"] == issue_key)
        comment = {
            "id": str(self.created_comment_count),
            "body": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": body}],
                    }
                ],
            },
        }
        issue.setdefault("comments", []).append(comment)
        return comment

    def create_issue_link(
        self,
        inward_issue_key: str,
        outward_issue_key: str,
        link_type: str,
    ) -> None:
        self.created_link_count += 1
        link = {
            "type": {"name": link_type},
            "inwardIssue": {"key": inward_issue_key},
            "outwardIssue": {"key": outward_issue_key},
        }
        for issue in self.issues:
            if issue["key"] in {inward_issue_key, outward_issue_key}:
                issue.setdefault("fields", {}).setdefault("issuelinks", []).append(
                    deepcopy(link)
                )

    def close(self) -> None:
        return None


def test_import_preserves_sources_and_is_idempotent(
    monkeypatch: Any, tmp_path: Path
) -> None:
    fake_jira = FakeJiraClient()
    monkeypatch.setattr(importer, "JiraClient", lambda: fake_jira)
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "source_identifier": "REC-1",
                        "fields": {
                            "summary": "Regression requirement",
                            "description": "Applies to R2.4.",
                            "issuetype": {"name": "Task"},
                            "labels": ["release"],
                            "status": {"name": "Done"},
                            "created": "2026-01-02T03:04:05.000Z",
                        },
                        "comments": [
                            {
                                "id": "COMMENT-1",
                                "author": {"displayName": "Fictional Reviewer"},
                                "role": "QA",
                                "created": "2026-01-03T04:05:06.000Z",
                                "body": "All mandatory regression tests passed.",
                            }
                        ],
                        "relationships": [
                            {
                                "target_source_id": "REC-2",
                                "link_type": "Relates",
                            }
                        ],
                    },
                    {
                        "source_identifier": "REC-2",
                        "fields": {"summary": "Regression evidence"},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    first = importer.import_dataset(
        str(dataset_path), "KAN", "release-evidence"
    )

    assert first.imported == 2
    assert first.comments_imported == 1
    assert first.links_imported == 1
    created_issue = fake_jira.issues[0]
    description = jira_text(created_issue["fields"]["description"])
    assert "Source ID: REC-1" in description
    assert "Source status: Done" in description
    comment_body = jira_text(fake_jira.issues[0]["comments"][0]["body"])
    assert "Source actor: Fictional Reviewer" in comment_body
    assert "Source role: QA" in comment_body
    assert "Source timestamp: 2026-01-03T04:05:06.000Z" in comment_body

    second = importer.import_dataset(
        str(dataset_path), "KAN", "release-evidence"
    )

    assert second.imported == 0
    assert second.reused == 2
    assert second.comments_imported == 0
    assert second.links_imported == 0
    assert fake_jira.created_issue_count == 2
    assert fake_jira.created_comment_count == 1
    assert fake_jira.created_link_count == 1
