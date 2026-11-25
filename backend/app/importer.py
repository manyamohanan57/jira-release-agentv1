import json
from pathlib import Path
from typing import Any

from app.jira_client import JiraClient


def import_dataset(dataset_path: str, project_key: str, dataset_label: str) -> tuple[int, int]:
    path = Path(dataset_path)
    if not path.is_file():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    with path.open("r", encoding="utf-8") as handle:
        payload: dict[str, Any] = json.load(handle)

    jira = JiraClient()
    imported = 0
    skipped = 0

    try:
        for issue in payload.get("issues", []):
            source_key = issue.get("key") or issue.get("source_identifier")
            if not source_key:
                skipped += 1
                continue

            fields = issue.get("fields", issue)
            description = fields.get("description", "")
            labels = set(fields.get("labels", []))
            labels.add(dataset_label)
            issue_type = fields.get("issuetype", "Task")
            if isinstance(issue_type, dict):
                issue_type = issue_type.get("name", "Task")

            jira_payload = {
                "fields": {
                    "project": {"key": project_key},
                    "summary": fields.get("summary", source_key),
                    "issuetype": {"name": issue_type},
                    "labels": sorted(labels),
                    "description": {
                        "type": "doc",
                        "version": 1,
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": str(description)}],
                            }
                        ],
                    },
                }
            }
            jira.create_issue(jira_payload)
            imported += 1
    finally:
        jira.close()

    return imported, skipped
