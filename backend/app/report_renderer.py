import csv
import io
from html import escape
from typing import Any

from app.models import ReleaseReadinessReport


def _value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _string(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


def _cell(value: str) -> str:
    escaped = escape(value, quote=False).replace("|", r"\|").replace("\r\n", "\n")
    return escaped.replace("\n", "<br>")


def render_markdown_report(report: ReleaseReadinessReport) -> str:
    lines = [
        f"# Release readiness: {_cell(report.target_release)}",
        "",
        f"**Overall decision:** {_cell(report.overall_decision.value)}  ",
        f"**Project:** {_cell(report.project_key or 'Not specified')}  ",
        f"**Dataset:** {_cell(report.dataset_label or 'Not specified')}  ",
        f"**Commit:** {_cell(report.commit)}  ",
        f"**Service / environment:** {_cell(report.service)} / {_cell(report.environment)}  ",
        f"**Prompt version:** {_cell(report.prompt_version)}",
        "",
        "| Requirement | Status | Assessment | Jira evidence | Missing evidence | Confidence |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for requirement in report.requirements:
        evidence = []
        for item in _value(requirement, "evidence", []):
            issue_key = _string(_value(item, "issue_key", ""))
            source_identifier = _value(item, "source_identifier")
            comment_id = _value(item, "comment_id")
            citation = f"**{_cell(issue_key)}**"
            if source_identifier:
                citation += f"; record {_cell(str(source_identifier))}"
            else:
                citation += "; record ID unavailable"
            if comment_id:
                citation += f"; comment {_cell(str(comment_id))}"
            evidence.append(
                f"{citation}; {_cell(_string(_value(item, 'source_type', 'Jira')))}; "
                f"{_cell(_string(_value(item, 'summary', '')))}: "
                f"{_cell(_string(_value(item, 'evidence_details', '')))}"
            )
        requirement_id = _string(_value(requirement, "requirement_id", ""))
        requirement_name = _string(_value(requirement, "requirement_name", ""))
        mandatory = bool(_value(requirement, "mandatory", True))
        confidence = _value(requirement, "confidence")
        missing_evidence = _value(requirement, "missing_evidence", [])
        lines.append(
            "| "
            + " | ".join(
                (
                    _cell(
                        f"{requirement_id} - {requirement_name} "
                        f"({'Mandatory' if mandatory else 'Optional'})"
                    ),
                    _cell(_string(_value(requirement, "status", ""))),
                    _cell(_string(_value(requirement, "reasoning", ""))),
                    "<br><br>".join(evidence) if evidence else "No qualifying evidence cited",
                    "<br>".join(_cell(_string(item)) for item in missing_evidence)
                    if missing_evidence
                    else "None",
                    (
                        f"{float(confidence):.0%}"
                        if confidence is not None
                        else "Not calculated"
                    ),
                )
            )
            + " |"
        )
    lines.extend(
        (
            "",
            f"Generated: {_cell(report.generated_at.isoformat())}",
            f"Execution time: {report.usage.execution_time_ms} ms",
        )
    )
    return "\n".join(lines) + "\n"


def _csv_cell(value: Any) -> str:
    text = _string(value)
    if text.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def render_csv_report(report: ReleaseReadinessReport) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(
        (
            "Requirement",
            "Status",
            "Assessment",
            "Jira evidence",
            "Missing evidence",
            "Confidence",
            "Target release",
            "Commit",
            "Service",
            "Environment",
            "Prompt version",
        )
    )
    for requirement in report.requirements:
        citations = []
        for item in _value(requirement, "evidence", []):
            identifiers = [
                f"Issue: {_string(_value(item, 'issue_key', ''))}",
                f"Record ID: {_string(_value(item, 'source_identifier')) or 'unavailable'}",
                f"Source type: {_string(_value(item, 'source_type', 'Jira'))}",
            ]
            comment_id = _value(item, "comment_id")
            if comment_id:
                identifiers.append(f"Comment: {_string(comment_id)}")
            citations.append(
                "; ".join(identifiers)
                + f"\nSummary: {_string(_value(item, 'summary', ''))}"
                + f"\nExcerpt: {_string(_value(item, 'evidence_details', ''))}"
            )
        missing = _value(requirement, "missing_evidence", [])
        confidence = _value(requirement, "confidence")
        values = (
            f"{_string(_value(requirement, 'requirement_id', ''))} - "
            f"{_string(_value(requirement, 'requirement_name', ''))}",
            _string(_value(requirement, "status", "")),
            _string(_value(requirement, "reasoning", "")),
            "\n\n".join(citations) if citations else "No qualifying evidence cited",
            "\n".join(_string(item) for item in missing) if missing else "None",
            f"{float(confidence):.0%}" if confidence is not None else "Not calculated",
            report.target_release,
            report.commit,
            report.service,
            report.environment,
            report.prompt_version,
        )
        writer.writerow(tuple(_csv_cell(value) for value in values))
    return output.getvalue()
