import re
from typing import Any

from app.jira_text import jira_text
from app.models import Decision, MANDATORY_REQUIREMENTS, OverallDecision


def _comment_text(record: dict[str, Any]) -> list[tuple[str | None, str]]:
    comments = record.get("fields", {}).get("comment", {}).get("comments", [])
    return [
        (str(comment["id"]) if comment.get("id") is not None else None,
         jira_text(comment.get("body", "")))
        for comment in comments
    ]


def _record_text(record: dict[str, Any]) -> str:
    fields = record.get("fields", {})
    fix_versions = " ".join(
        str(version.get("name", "") if isinstance(version, dict) else version)
        for version in fields.get("fixVersions", [])
    )
    labels = " ".join(str(label) for label in fields.get("labels", []))
    parts = [
        str(record.get("key", "")),
        jira_text(fields.get("summary", "")),
        jira_text(fields.get("description", "")),
        fix_versions,
        labels,
        *(text for _, text in _comment_text(record)),
    ]
    return "\n".join(part for part in parts if part).lower()


def _record_context(record: dict[str, Any]) -> str:
    fields = record.get("fields", {})
    fix_versions = " ".join(
        str(version.get("name", "") if isinstance(version, dict) else version)
        for version in fields.get("fixVersions", [])
    )
    labels = " ".join(str(label) for label in fields.get("labels", []))
    return "\n".join(
        part
        for part in (
            str(record.get("key", "")),
            jira_text(fields.get("summary", "")),
            fix_versions,
            labels,
        )
        if part
    ).lower()


def _evidence_units(record: dict[str, Any]) -> list[tuple[str | None, str, str]]:
    fields = record.get("fields", {})
    units = []
    description = jira_text(fields.get("description", ""))
    if description.strip():
        units.append((None, description, "Jira description"))
    for comment_id, body in _comment_text(record):
        if body.strip():
            units.append((comment_id, body, "Jira comment"))
    if not units:
        units.append((None, "", "Jira issue"))
    return units


def _commit_matches(record_context: str, source_text: str, target_commit: str) -> bool:
    target = target_commit.lower()
    if not target:
        return True
    source_commits = re.findall(r"\b[a-f0-9]{7,40}\b", source_text.lower())
    context_commits = re.findall(r"\b[a-f0-9]{7,40}\b", record_context.lower())
    mentions = source_commits or context_commits
    return any(
        mention.startswith(target) or target.startswith(mention)
        for mention in mentions
    )


def _environment_matches(
    record_context: str,
    source_text: str,
    environment: str,
) -> bool:
    aliases = {
        "production": {"production", "prod"},
        "staging": {"staging", "stage"},
        "development": {"development", "dev"},
    }
    expected = aliases.get(environment.lower(), {environment.lower()})
    known_environments = {
        "production",
        "prod",
        "staging",
        "stage",
        "development",
        "dev",
        "uat",
        "sandbox",
        *expected,
    }
    pattern = re.compile(
        r"\b(?:" + "|".join(re.escape(name) for name in known_environments) + r")\b",
        re.IGNORECASE,
    )
    mentions = {
        mention.lower()
        for mention in pattern.findall(source_text)
    } or {
        mention.lower()
        for mention in pattern.findall(record_context)
    }
    return bool(mentions.intersection(expected)) and mentions.issubset(expected)


def calculate_overall_status(requirements: list[Any]) -> OverallDecision:
    statuses = [
        getattr(item, "status", None) or getattr(item, "decision", None)
        for item in requirements
    ]
    statuses = [
        Decision(status) if not isinstance(status, Decision) else status
        for status in statuses
    ]
    if Decision.FAIL in statuses:
        return OverallDecision.BLOCKED
    if any(status is Decision.INSUFFICIENT_EVIDENCE for status in statuses):
        return OverallDecision.NEEDS_REVIEW
    return OverallDecision.READY


def _is_explicit_failure(text: str) -> bool:
    failure_terms = re.compile(
        r"\b(?:failed|failing|blocked|unresolved defect|confirmed defect|exposed|"
        r"exposure found|rejected|unsuccessful|duplicate final messages?|"
        r"missing final messages?|not approved|not verified|not working|"
        r"not delivered|not redacted|unredacted|did not pass|"
        r"cross[- ]customer.{0,50}(?:exposure|leakage))\b"
    )
    for sentence in re.split(r"[\n.!?;]+", text):
        for match in failure_terms.finditer(sentence):
            preceding = sentence[max(0, match.start() - 35):match.start()]
            if re.search(
                r"\b(?:no|not|never|without|zero)(?:\s+\w+){0,3}\s*$",
                preceding,
            ):
                continue
            if re.search(r"\bno\s+cross[- ]customer.{0,30}$", preceding):
                continue
            return True
    return False


def _is_pass(requirement_id: str, text: str, prompt_version: str) -> bool:
    if requirement_id == "REQ-01":
        return bool(
            re.search(
                r"(?:all|mandatory).{0,80}(?:regression|test).{0,80}"
                r"(?:passed|pass|successful)",
                text,
            )
        )
    if requirement_id == "REQ-02":
        return bool(
            re.search(
                r"(?:no cross[- ]customer.{0,40}(?:document )?(?:exposure|leakage)|"
                r"(?:document )?isolation.{0,30}(?:passed|pass|verified))",
                text,
            )
        )
    if requirement_id == "REQ-03":
        quality = re.search(
            r"(?:answer )?(?:quality|accuracy)\s*(?:of|at|:|=|was|is)?\s*"
            r"(\d+(?:\.\d+)?)\s*%",
            text,
        )
        return bool(
            prompt_version.lower() in text
            and quality
            and float(quality.group(1)) >= 90
        )
    if requirement_id == "REQ-04":
        latency = re.search(
            r"p95.{0,40}?(\d+(?:\.\d+)?)\s*(ms|milliseconds|s|seconds|second)\b",
            text,
        )
        if not latency:
            return False
        value = float(latency.group(1))
        seconds = value / 1000 if latency.group(2).startswith("m") else value
        return seconds <= 2
    if requirement_id == "REQ-05":
        cost = re.search(
            r"(?:cost|per successful request).{0,50}?\$?\s*(0?\.\d+)",
            text,
        )
        return bool(
            cost
            and float(cost.group(1)) <= 0.012
            and ("successful request" in text or "per request" in text)
        )
    if requirement_id == "REQ-06":
        return all(
            phrase in text
            for phrase in ("asha rao", "security", "approved", "production")
        )
    if requirement_id == "REQ-07":
        return (
            "qa" in text
            and ("redact" in text or "redaction" in text)
            and "log" in text
            and any(term in text for term in ("sensitive", "pii", "credential", "secret"))
            and any(word in text for word in ("passed", "verified", "confirmed"))
        )
    if requirement_id == "REQ-08":
        return (
            ("human handoff" in text or "handoff" in text)
            and "support queue" in text
            and any(word in text for word in ("successfully", "successful", "delivered"))
            and "delivery" in text
            and "dependency" in text
        )
    if requirement_id == "REQ-09":
        return (
            "rollback" in text
            and "rehearsal" in text
            and "approved" in text
            and "production" in text
            and any(word in text for word in ("succeeded", "successful", "passed"))
        )
    if requirement_id == "REQ-10":
        count_is_complete = bool(
            re.search(r"\b60\s*(?:/|of)\s*60\b|\ball 60\b", text)
        )
        return (
            count_is_complete
            and "parsing" in text
            and any(word in text for word in ("passed", "pass", "successful"))
        )
    if requirement_id == "REQ-11":
        return (
            "qa" in text
            and "keyboard" in text
            and "navigation" in text
            and "focus" in text
            and any(word in text for word in ("passed", "verified", "confirmed"))
        )
    if requirement_id == "REQ-12":
        return (
            "stream" in text
            and "no duplicate" in text
            and (
                "no missing" in text
                or "no duplicate or missing" in text
            )
            and "final message" in text
        )
    return False


def _threshold_failure(requirement_id: str, text: str) -> bool:
    if requirement_id == "REQ-03":
        quality = re.search(
            r"(?:answer )?(?:quality|accuracy)\s*(?:of|at|:|=|was|is)?\s*"
            r"(\d+(?:\.\d+)?)\s*%",
            text,
        )
        return bool(quality and float(quality.group(1)) < 90)
    if requirement_id == "REQ-01":
        results = re.search(
            r"\b(\d+)\s*(?:/|of)\s*(\d+)\s+"
            r"(?:mandatory\s+)?(?:regression\s+)?(?:tests?|cases?)\b",
            text,
        )
        return bool(results and int(results.group(1)) < int(results.group(2)))
    if requirement_id == "REQ-04":
        latency = re.search(
            r"p95.{0,40}?(\d+(?:\.\d+)?)\s*(ms|milliseconds|s|seconds|second)\b",
            text,
        )
        if latency:
            value = float(latency.group(1))
            seconds = value / 1000 if latency.group(2).startswith("m") else value
            return seconds > 2
    if requirement_id == "REQ-05":
        cost = re.search(
            r"(?:cost|per successful request).{0,50}?\$?\s*(0?\.\d+)",
            text,
        )
        return bool(
            cost
            and float(cost.group(1)) > 0.012
            and ("successful request" in text or "per request" in text)
        )
    if requirement_id == "REQ-10":
        count = re.search(r"\b(\d+)\s*(?:/|of)\s*60\b", text)
        return bool(count and int(count.group(1)) < 60)
    return False


def _public_evidence(
    record: dict[str, Any],
    source_text: str,
    comment_id: str | None,
    source_type: str,
) -> dict[str, Any]:
    fields = record.get("fields", {})
    return {
        "issue_key": str(record.get("key", "")),
        "comment_id": comment_id,
        "summary": jira_text(fields.get("summary", "")),
        "evidence_details": source_text[:1500],
        "source_type": source_type,
    }


def validate_evidence(
    requirement_id: str,
    context: dict[str, str],
    evidence_records: list[dict[str, Any]],
) -> tuple[Decision, str, list[dict[str, Any]], list[str], float]:
    name = MANDATORY_REQUIREMENTS.get(requirement_id, requirement_id)
    if not evidence_records:
        return (
            Decision.INSUFFICIENT_EVIDENCE,
            f"No Jira evidence was retrieved for {name}.",
            [],
            ["Retrieve requirement-specific Jira evidence."],
            0.0,
        )

    release = context["release"].lower()
    service = context["service"].lower()
    environment = context["environment"].lower()
    context_matches: list[
        tuple[dict[str, Any], str, str | None, str, str]
    ] = []
    rejected_commit = False
    rejected_environment = False
    rejected_prompt_version = False
    for record in evidence_records:
        fields = record.get("fields", {})
        fix_versions = " ".join(
            str(version.get("name", "") if isinstance(version, dict) else version)
            for version in fields.get("fixVersions", [])
        ).lower()
        record_context = _record_context(record)
        for comment_id, source_text, source_type in _evidence_units(record):
            text = "\n".join(part for part in (record_context, source_text.lower()) if part)
            if (
                not re.search(rf"\b{re.escape(release)}\b", text)
                and release not in fix_versions
            ):
                continue
            if not re.search(rf"\b{re.escape(service)}\b", text):
                continue
            if not _commit_matches(record_context, source_text, context["commit"]):
                rejected_commit = True
                continue
            if environment and not _environment_matches(
                record_context,
                source_text,
                environment,
            ):
                rejected_environment = True
                continue
            if (
                requirement_id == "REQ-03"
                and not re.search(
                    rf"\b{re.escape(context['prompt_version'].lower())}\b",
                    text,
                )
            ):
                rejected_prompt_version = True
                continue
            context_matches.append(
                (record, text, comment_id, source_type, source_text)
            )

    if not context_matches:
        reasons = []
        if rejected_commit:
            reasons.append(f"evidence for commit {context['commit']} is missing")
        if rejected_environment:
            reasons.append(
                f"evidence for environment {context['environment']} is missing"
            )
        if rejected_prompt_version:
            reasons.append(
                f"evidence for prompt version {context['prompt_version']} is missing"
            )
        if not reasons:
            reasons.append(
                f"no matching {service} evidence for release {context['release']} was found"
            )
        return (
            Decision.INSUFFICIENT_EVIDENCE,
            f"Jira records do not establish {name}: {'; '.join(reasons)}.",
            [],
            [f"Provide evidence for {context['release']} and {context['service']}."],
            0.2,
        )

    evidence_texts = [text for _, text, _, _, _ in context_matches]
    evidence_text = "\n".join(evidence_texts)
    relevant_evidence = [
        _public_evidence(record, source_text, comment_id, source_type)
        for record, _, comment_id, source_type, source_text in context_matches
    ]

    superseded_failure = (
        ("later qa retest" in evidence_text or "later retest" in evidence_text)
        and any(word in evidence_text for word in ("passed", "supersedes"))
    )
    if any(_is_explicit_failure(text) for text in evidence_texts) and not superseded_failure:
        return (
            Decision.FAIL,
            f"Target-context Jira evidence documents a failure for {name}.",
            relevant_evidence,
            [],
            0.95,
        )
    if any(_threshold_failure(requirement_id, text) for text in evidence_texts):
        return (
            Decision.FAIL,
            f"Measured Jira evidence does not meet the required threshold for {name}.",
            relevant_evidence,
            [],
            0.95,
        )
    if any(
        _is_pass(requirement_id, text, context["prompt_version"])
        for text in evidence_texts
    ):
        return (
            Decision.PASS,
            f"Target-context Jira comments explicitly verify {name}.",
            relevant_evidence,
            [],
            0.95,
        )

    return (
        Decision.INSUFFICIENT_EVIDENCE,
        f"Related Jira records were found for {name}, but they do not prove its acceptance criteria.",
        relevant_evidence,
        [f"Provide test results or approval that explicitly satisfy {name}."],
        0.45,
    )
