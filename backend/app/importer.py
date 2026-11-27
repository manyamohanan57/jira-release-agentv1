import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.jira_client import JiraClient
from app.jira_text import jira_text


_SOURCE_ID_PATTERN = re.compile(r"(?im)^Source ID:\s*(.+?)\s*$")
_LINKED_SOURCE_PATTERN = re.compile(
    r"(?im)^Linked Source IDs:\s*(.+?)\s*$"
)


@dataclass(frozen=True)
class ImportSummary:
    imported: int
    skipped: int
    reused: int
    comments_imported: int
    links_imported: int
    relationships_skipped: int


def _identifier(value: Any) -> str | None:
    if isinstance(value, dict):
        value = (
            value.get("source_identifier")
            or value.get("source_id")
            or value.get("issue_key")
            or value.get("key")
            or value.get("id")
        )
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _source_id(issue: dict[str, Any], fields: dict[str, Any]) -> str | None:
    for value in (
        issue.get("source_identifier"),
        issue.get("source_id"),
        issue.get("source_key"),
        fields.get("source_identifier"),
        fields.get("source_id"),
        issue.get("key"),
        issue.get("id"),
    ):
        result = _identifier(value)
        if result:
            return result
    return None


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _display_value(value: Any) -> str:
    if isinstance(value, dict):
        return str(
            value.get("displayName")
            or value.get("name")
            or value.get("emailAddress")
            or value.get("key")
            or ""
        )
    return str(value) if value is not None else ""


def _comment_records(issue: dict[str, Any]) -> list[dict[str, Any]]:
    fields = issue.get("fields", issue)
    comments = issue.get("comments")
    if comments is None:
        comments = fields.get("comment", [])
        if isinstance(comments, dict):
            comments = comments.get("comments", [])
    return [item for item in _list(comments) if isinstance(item, dict)]


def _comment_source_id(comment: dict[str, Any], index: int) -> str:
    value = (
        comment.get("source_identifier")
        or comment.get("source_id")
        or comment.get("id")
        or comment.get("key")
    )
    if value is not None:
        return str(value)
    stable_content = json.dumps(comment, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(stable_content.encode("utf-8")).hexdigest()[:16]
    return f"generated-{index + 1}-{digest}"


def _source_comment_body(comment: dict[str, Any], source_comment_id: str) -> str:
    lines = [f"Source comment ID: {source_comment_id}"]
    actor = _display_value(
        comment.get("actor")
        or comment.get("author")
        or comment.get("user")
        or comment.get("username")
    )
    role = _display_value(
        comment.get("actor_role")
        or comment.get("author_role")
        or comment.get("role")
    )
    timestamp = (
        comment.get("source_timestamp")
        or comment.get("timestamp")
        or comment.get("created_at")
        or comment.get("created")
    )
    if actor:
        lines.append(f"Source actor: {actor}")
    if role:
        lines.append(f"Source role: {role}")
    if timestamp:
        lines.append(f"Source timestamp: {timestamp}")

    body = comment.get("body")
    if body is None:
        body = comment.get("text", comment.get("comment", ""))
    body_text = jira_text(body)
    if body_text:
        lines.extend(("", body_text))
    return "\n".join(lines)


def _relationship_entries(issue: dict[str, Any]) -> list[dict[str, str]]:
    fields = issue.get("fields", issue)
    relationships: list[dict[str, str]] = []

    for raw in (
        issue.get("relationships"),
        issue.get("links"),
        issue.get("linked_source_ids"),
        issue.get("linked_source_identifiers"),
        fields.get("issuelinks"),
        fields.get("links"),
    ):
        for item in _list(raw):
            if isinstance(item, str):
                target = item
                link_type = "Relates"
                direction = "outward"
            elif isinstance(item, dict):
                link_type_value = item.get("link_type") or item.get("relation") or item.get("type") or "Relates"
                if isinstance(link_type_value, dict):
                    link_type_value = link_type_value.get("name", "Relates")
                direction = str(item.get("direction", "outward")).lower()
                target_value = (
                    item.get("target_source_id")
                    or item.get("target_identifier")
                    or item.get("to_source_id")
                    or item.get("to_id")
                    or item.get("target_id")
                    or item.get("target")
                    or item.get("issue_id")
                    or item.get("issue_key")
                    or item.get("key")
                )
                if target_value is None and item.get("outwardIssue"):
                    target_value = item["outwardIssue"]
                    direction = "inward"
                elif target_value is None and item.get("inwardIssue"):
                    target_value = item["inwardIssue"]
                    direction = "outward"
                target = _identifier(target_value) or ""
                link_type = str(link_type_value or "Relates")
            else:
                continue
            if target:
                relationships.append(
                    {
                        "target": target,
                        "link_type": link_type,
                        "direction": direction,
                    }
                )

    description = jira_text(fields.get("description", ""))
    linked_match = _LINKED_SOURCE_PATTERN.search(description)
    if linked_match:
        for target in re.findall(r"\bREC-\d+\b", linked_match.group(1), re.IGNORECASE):
            relationships.append(
                {"target": target, "link_type": "Relates", "direction": "outward"}
            )

    unique: dict[tuple[str, str, str], dict[str, str]] = {}
    for relationship in relationships:
        key = (
            relationship["target"],
            relationship["link_type"],
            relationship["direction"],
        )
        unique[key] = relationship
    return list(unique.values())


def _source_metadata(issue: dict[str, Any], fields: dict[str, Any]) -> list[str]:
    metadata = []
    for label, names in (
        ("status", ("status",)),
        ("created", ("created", "created_at")),
        ("updated", ("updated", "updated_at")),
        ("reporter", ("reporter",)),
        ("assignee", ("assignee",)),
        ("fix versions", ("fixVersions", "fix_versions")),
    ):
        value = next(
            (fields[name] for name in names if fields.get(name) is not None),
            None,
        )
        if value is None:
            value = next((issue[name] for name in names if issue.get(name) is not None), None)
        if value is None:
            continue
        if label == "fix versions":
            value = ", ".join(
                _display_value(version.get("name") if isinstance(version, dict) else version)
                for version in _list(value)
            )
        else:
            value = _display_value(value)
        if value:
            metadata.append(f"Source {label}: {value}")
    return metadata


def _adf_document(text: str) -> dict[str, Any]:
    paragraphs = text.splitlines() or [""]
    return {
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


def _existing_source_map(issues: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    source_map = {}
    for issue in issues:
        fields = issue.get("fields", {})
        description = jira_text(fields.get("description", ""))
        match = _SOURCE_ID_PATTERN.search(description)
        source_id = match.group(1).strip() if match else None
        if not source_id:
            summary = jira_text(fields.get("summary", ""))
            source_id = summary if summary.startswith("REC-") else None
        if source_id and issue.get("key"):
            source_map[source_id] = issue
    return source_map


def _existing_links(issues: list[dict[str, Any]]) -> set[tuple[str, str, str]]:
    links: set[tuple[str, str, str]] = set()
    for issue in issues:
        for link in issue.get("fields", {}).get("issuelinks", []):
            link_type = str(link.get("type", {}).get("name", "Relates"))
            inward = link.get("inwardIssue", {}).get("key")
            outward = link.get("outwardIssue", {}).get("key")
            if inward and outward:
                links.add((str(link_type), str(inward), str(outward)))
    return links


def _global_comments(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    comments_by_issue: dict[str, list[dict[str, Any]]] = {}
    raw_comments = payload.get("comments")
    if isinstance(raw_comments, dict):
        comment_records = []
        for issue_ref, comments in raw_comments.items():
            for comment in _list(comments):
                if isinstance(comment, dict):
                    linked_comment = dict(comment)
                    linked_comment.setdefault("issue_source_id", issue_ref)
                    comment_records.append(linked_comment)
    else:
        comment_records = _list(raw_comments)

    for comment in comment_records:
        if not isinstance(comment, dict):
            continue
        issue_ref = (
            comment.get("issue_source_id")
            or comment.get("source_issue_id")
            or comment.get("issue_id")
            or comment.get("issue_key")
            or comment.get("ticket_id")
        )
        source_id = _identifier(issue_ref)
        if source_id:
            comments_by_issue.setdefault(source_id, []).append(comment)
    return comments_by_issue


def _global_relationships(payload: dict[str, Any]) -> list[tuple[str, dict[str, str]]]:
    result = []
    for relation in _list(payload.get("relationships")) + _list(payload.get("links")):
        if not isinstance(relation, dict):
            continue
        source = _identifier(
            relation.get("source_source_id")
            or relation.get("from_source_id")
            or relation.get("source_id")
            or relation.get("from")
            or relation.get("source")
        )
        target = _identifier(
            relation.get("target_source_id")
            or relation.get("to_source_id")
            or relation.get("target_id")
            or relation.get("to")
            or relation.get("target")
        )
        if source and target:
            link_type = relation.get("link_type") or relation.get("type") or "Relates"
            if isinstance(link_type, dict):
                link_type = link_type.get("name", "Relates")
            result.append(
                (
                    source,
                    {
                        "target": target,
                        "link_type": str(link_type),
                        "direction": str(relation.get("direction", "outward")).lower(),
                    },
                )
            )
    return result


def import_dataset(
    dataset_path: str,
    project_key: str,
    dataset_label: str,
) -> ImportSummary:
    path = Path(dataset_path)
    if not path.is_file():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or not isinstance(payload.get("issues"), list):
        raise ValueError("Dataset must be a JSON object with an 'issues' array.")

    source_records: dict[str, dict[str, Any]] = {}
    skipped = 0
    for issue in payload["issues"]:
        if not isinstance(issue, dict):
            skipped += 1
            continue
        fields = issue.get("fields", issue)
        if not isinstance(fields, dict):
            skipped += 1
            continue
        source_id = _source_id(issue, fields)
        if not source_id:
            skipped += 1
            continue
        if source_id in source_records:
            raise ValueError(f"Dataset contains duplicate source identifier '{source_id}'.")
        source_records[source_id] = issue

    if not source_records:
        raise ValueError("Dataset contains no issues with a stable source identifier.")

    comments_by_source = _global_comments(payload)
    for source_id, issue in source_records.items():
        issue_comments = _comment_records(issue)
        issue_comments.extend(comments_by_source.get(source_id, []))
        issue["_import_comments"] = issue_comments

    global_relations = _global_relationships(payload)
    relations_by_source: dict[str, list[dict[str, str]]] = {}
    for source_id, relationship in global_relations:
        relations_by_source.setdefault(source_id, []).append(relationship)

    jira = JiraClient()
    imported = 0
    reused = 0
    comments_imported = 0
    links_imported = 0
    relationships_skipped = 0
    source_to_issue = {}
    relationship_plan: list[tuple[str, str, str, str]] = []

    try:
        existing_issues = jira.search(project_key, dataset_label, max_results=100)
        source_to_issue.update(_existing_source_map(existing_issues))
        existing_link_set = _existing_links(existing_issues)

        for source_id, issue in source_records.items():
            if source_id in source_to_issue:
                reused += 1
                continue

            fields = issue.get("fields", issue)
            source_description = jira_text(fields.get("description", ""))
            labels = {
                str(label)
                for label in _list(fields.get("labels"))
                if label
            }
            labels.add(dataset_label)
            issue_type = fields.get("issuetype", issue.get("issue_type", "Task"))
            if isinstance(issue_type, dict):
                issue_type = issue_type.get("name", "Task")
            if not isinstance(issue_type, str) or not issue_type.strip():
                issue_type = "Task"

            relationships = _relationship_entries(issue)
            relationships.extend(relations_by_source.get(source_id, []))
            target_ids = list(dict.fromkeys(item["target"] for item in relationships))
            description_parts = [f"Source ID: {source_id}"]
            original_key = issue.get("key")
            if original_key:
                description_parts.append(f"Source key: {original_key}")
            if source_description:
                description_parts.extend(("", source_description))
            description_parts.extend(_source_metadata(issue, fields))
            if target_ids:
                description_parts.append(
                    "Linked Source IDs: " + ", ".join(target_ids)
                )
            description = "\n".join(description_parts)
            summary = jira_text(fields.get("summary", "")) or source_id

            created_issue = jira.create_issue(
                {
                    "fields": {
                        "project": {"key": project_key},
                        "summary": summary[:255],
                        "issuetype": {"name": issue_type},
                        "labels": sorted(labels),
                        "description": _adf_document(description),
                    }
                }
            )
            jira_key = created_issue.get("key")
            if not jira_key:
                raise RuntimeError(
                    f"Jira did not return a key after importing source issue '{source_id}'."
                )
            source_to_issue[source_id] = {
                "key": jira_key,
                "fields": {"labels": sorted(labels), "issuelinks": []},
            }
            imported += 1
            relationship_plan.extend(
                (
                    source_id,
                    item["target"],
                    item["link_type"],
                    item["direction"],
                )
                for item in relationships
            )

        # Existing records also need relationship reconciliation on reruns.
        for source_id, issue in source_records.items():
            if source_id not in source_to_issue:
                continue
            relationships = _relationship_entries(issue)
            relationships.extend(relations_by_source.get(source_id, []))
            relationship_plan.extend(
                (
                    source_id,
                    item["target"],
                    item["link_type"],
                    item["direction"],
                )
                for item in relationships
            )

        for source_id, issue in source_records.items():
            jira_issue = source_to_issue.get(source_id)
            if not jira_issue:
                continue
            comments = issue.get("_import_comments", [])
            if not comments:
                continue
            jira_key = str(jira_issue["key"])
            existing_comments = jira.get_comments(
                jira_key,
                dataset_label,
                project_key,
            )
            existing_bodies = {
                jira_text(comment.get("body", ""))
                for comment in existing_comments
            }
            for index, comment in enumerate(comments):
                comment_id = _comment_source_id(comment, index)
                body = _source_comment_body(comment, comment_id)
                if body in existing_bodies or f"Source comment ID: {comment_id}" in "\n".join(existing_bodies):
                    continue
                jira.create_comment(jira_key, body)
                existing_bodies.add(body)
                comments_imported += 1

        issue_keys = {
            source_id: str(record["key"])
            for source_id, record in source_to_issue.items()
        }
        for source_id, target_id, link_type, direction in relationship_plan:
            inward_key = issue_keys.get(target_id)
            outward_key = issue_keys.get(source_id)
            if not inward_key or not outward_key:
                relationships_skipped += 1
                continue
            if direction in {"inward", "in"}:
                inward_key, outward_key = outward_key, inward_key
            link_key = (link_type, inward_key, outward_key)
            if link_key in existing_link_set:
                continue
            jira.create_issue_link(inward_key, outward_key, link_type)
            existing_link_set.add(link_key)
            links_imported += 1
    finally:
        jira.close()

    return ImportSummary(
        imported=imported,
        skipped=skipped,
        reused=reused,
        comments_imported=comments_imported,
        links_imported=links_imported,
        relationships_skipped=relationships_skipped,
    )
