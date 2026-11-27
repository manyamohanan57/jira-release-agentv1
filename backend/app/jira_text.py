from typing import Any


def jira_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(filter(None, (jira_text(item) for item in value)))
    if isinstance(value, dict):
        if value.get("type") == "text":
            return str(value.get("text", ""))
        if value.get("type") == "hardBreak":
            return "\n"
        content = value.get("content")
        if isinstance(content, list):
            return "\n".join(filter(None, (jira_text(item) for item in content)))
        return ""
    return ""
