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


def _counted_outcome(
    requirement_id: str,
    text: str,
) -> tuple[int, int, str] | None:
    if requirement_id == "REQ-01":
        outcome = re.search(
            r"\b(\d+)\s*(?:/|of)\s*(\d+)\s+"
            r"(?:mandatory\s+)?(?:automated\s+)?(?:regression\s+)?"
            r"(?:tests?|cases?)\b.{0,30}\b(passed|failed|successful)\b",
            text,
        )
    elif requirement_id == "REQ-10":
        outcome = re.search(
            r"\b(\d+)\s*(?:/|of)\s*60\s+"
            r"(?:documents?|files?)\b.{0,30}\b(passed|failed|successful|parsed)\b",
            text,
        )
    else:
        return None
    if not outcome:
        return None
    if requirement_id == "REQ-10":
        return int(outcome.group(1)), 60, outcome.group(2)
    return int(outcome.group(1)), int(outcome.group(2)), outcome.group(3)


def _is_pass(requirement_id: str, text: str, prompt_version: str) -> bool:
    if requirement_id == "REQ-01":
        results = _counted_outcome(requirement_id, text)
        if results:
            count, total, outcome = results
            return (outcome in ("passed", "successful") and count == total) or (
                outcome == "failed" and count == 0
            )
        return bool(
            re.search(
                r"(?:all|mandatory).{0,80}(?:regression|test).{0,80}"
                r"(?:passed|successful)",
                text,
            )
        )
    if requirement_id == "REQ-02":
        return bool(
            re.search(
                r"(?:no cross[- ]customer.{0,40}(?:document )?(?:exposure|leakage)|"
                r"(?:document )?isolation.{0,30}(?:passed|verified))",
                text,
            )
        )
    if requirement_id == "REQ-03":
        quality = _observed_metric(
            text,
            r"(?:answer )?(?:quality|accuracy)\s*(?:of|at|:|=|was|is)?\s*"
            r"(\d+(?:\.\d+)?)\s*%",
        )
        return bool(
            prompt_version.lower() in text
            and quality
            and float(quality.group(1)) >= 90
        )
    if requirement_id == "REQ-04":
        latency = _observed_metric(
            text,
            r"p95.{0,40}?(\d+(?:\.\d+)?)\s*(ms|milliseconds|s|seconds|second)\b",
        )
        if not latency:
            return False
        value = float(latency.group(1))
        seconds = value / 1000 if latency.group(2).startswith("m") else value
        return seconds <= 2
    if requirement_id == "REQ-05":
        cost = _observed_metric(
            text,
            r"(?:cost|per successful request).{0,60}?"
            r"(?:usd\s*)?\$?\s*(\d+(?:\.\d+)?)",
        )
        return bool(
            cost
            and float(cost.group(1)) <= 0.012
            and ("successful request" in text or "per request" in text)
        )
    if requirement_id == "REQ-06":
        approver = re.search(
            r"(?:approved|approval granted|signed off)"
            r"\s+(?:by\s+)?(?:the\s+)?(?:security owner\s+)?asha rao\b"
            r"|\b(?:security owner\s+)?asha rao\b[^.;\n]{0,40}"
            r"\b(?:approved|approval granted|signed off)\b",
            text,
        )
        approver_role = re.search(
            r"\bsecurity(?:\s+owner)?\b.{0,30}\basha rao\b"
            r"|\basha rao\b.{0,30}\bsecurity(?:\s+owner)?\b",
            text,
        )
        return approver is not None and approver_role is not None
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
        count = _counted_outcome(requirement_id, text)
        count_is_complete = bool(
            count
            and count[0] == 60
            and count[2] in ("passed", "successful", "parsed")
        )
        return (
            count_is_complete
            and "parsing" in text
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
            and any(
                word in text
                for word in ("verified", "confirmed", "observed", "result")
            )
        )
    return False


def _observed_metric(text: str, pattern: str) -> re.Match[str] | None:
    match = re.search(pattern, text)
    if not match:
        return None
    value_start = match.start(1) if match.lastindex else match.start()
    prefix = text[:value_start]
    sentence_start = max(
        prefix.rfind("\n"),
        prefix.rfind("."),
        prefix.rfind("!"),
        prefix.rfind("?"),
        prefix.rfind(";"),
    )
    suffix = text[match.end():]
    sentence_endings = [
        position
        for delimiter in ("\n", ".", "!", "?", ";")
        if (position := suffix.find(delimiter)) >= 0
    ]
    sentence_end = min(sentence_endings) if sentence_endings else len(suffix)
    before = prefix[max(sentence_start + 1, value_start - 100):]
    after = suffix[:min(sentence_end, 50)]
    has_strong_observation_signal = re.search(
        r"\b(?:measured|measurement|observed|recorded|actual|run result)\b",
        before,
    )
    metric_terms = r"(?:p95|latency|quality|accuracy|cost|successful request)"
    is_normative = re.search(
        r"\b(?:must|should|shall|no more than|at most|less than)\b|<=|>=",
        before,
    ) or re.search(
        r"\b(?:target|threshold|limit|maximum|minimum|acceptance)\b"
        rf".{{0,35}}\b{metric_terms}\b|\b{metric_terms}\b.{{0,35}}"
        r"\b(?:target|threshold|limit|maximum|minimum|acceptance)\b",
        before,
    )
    if is_normative and not has_strong_observation_signal:
        return None
    has_observation_signal = re.search(
        r"\b(?:measured|measurement|observed|recorded|actual|result|average|"
        r"mean|was|is|scored|achieved)\b|[:=]",
        before,
    )
    has_result_signal = re.search(
        r"\b(?:measured|measurement|observed|recorded|actual|result|was|is|"
        r"scored|achieved)\b",
        after,
    )
    return match if has_observation_signal or has_result_signal else None


def _threshold_failure(requirement_id: str, text: str) -> bool:
    if requirement_id == "REQ-03":
        quality = _observed_metric(
            text,
            r"(?:answer )?(?:quality|accuracy)\s*(?:of|at|:|=|was|is)?\s*"
            r"(\d+(?:\.\d+)?)\s*%",
        )
        return bool(quality and float(quality.group(1)) < 90)
    if requirement_id == "REQ-01":
        results = _counted_outcome(requirement_id, text)
        if not results:
            return False
        count, total, outcome = results
        return (outcome == "failed" and count > 0) or (
            outcome in ("passed", "successful") and count < total
        )
    if requirement_id == "REQ-04":
        latency = _observed_metric(
            text,
            r"p95.{0,40}?(\d+(?:\.\d+)?)\s*(ms|milliseconds|s|seconds|second)\b",
        )
        if latency:
            value = float(latency.group(1))
            seconds = value / 1000 if latency.group(2).startswith("m") else value
            return seconds > 2
    if requirement_id == "REQ-05":
        cost = _observed_metric(
            text,
            r"(?:cost|per successful request).{0,60}?"
            r"(?:usd\s*)?\$?\s*(\d+(?:\.\d+)?)",
        )
        return bool(
            cost
            and float(cost.group(1)) > 0.012
            and ("successful request" in text or "per request" in text)
        )
    if requirement_id == "REQ-10":
        count = _counted_outcome(requirement_id, text)
        if not count:
            return False
        return (count[2] == "failed" and count[0] > 0) or (
            count[2] in ("passed", "successful", "parsed") and count[0] < 60
        )
    return False


_MISSING_EVIDENCE: dict[str, str] = {
    "REQ-01": "Target-build regression results showing passed and total test counts are missing.",
    "REQ-02": "A target-build isolation result explicitly confirming whether cross-customer document exposure occurred is missing.",
    "REQ-03": "A p7 answer-quality measurement for the target build is missing; the acceptance threshold is at least 90%.",
    "REQ-04": "A production p95 latency measurement for the target build is missing; the acceptance threshold is at most 2.0 seconds.",
    "REQ-05": "Mean model cost per successful request for the target build is missing; the acceptance threshold is at most USD 0.012.",
    "REQ-06": "An explicit production security approval from Asha Rao for the target release and commit is missing.",
    "REQ-07": "QA verification that sensitive data is redacted from target-build production logs is missing.",
    "REQ-08": "Evidence that the target-build human handoff reached the support queue with dependency handling is missing.",
    "REQ-09": "An approved production rollback rehearsal result for the target build is missing.",
    "REQ-10": "Target-build parsing results showing how many of the required 60 documents passed are missing.",
    "REQ-11": "QA verification of keyboard navigation and focus behavior on the target build is missing.",
    "REQ-12": "A production streaming result confirming there are no duplicate or missing final messages is missing.",
}


def _source_identifier(record: dict[str, Any], source_text: str) -> str | None:
    fields = record.get("fields", {})
    text = "\n".join(
        (
            jira_text(fields.get("description", "")),
            jira_text(fields.get("summary", "")),
            source_text,
        )
    )
    source_id = re.search(r"\b(?:source\s+id\s*:\s*)?(REC-\d+)\b", text, re.I)
    return source_id.group(1).upper() if source_id else None


def _measurement(requirement_id: str, text: str) -> tuple[str, str] | None:
    if requirement_id == "REQ-01":
        result = _counted_outcome(requirement_id, text)
        if result:
            return (
                f"{result[0]}/{result[1]} regression tests {result[2]}",
                (
                    "zero regression tests may fail"
                    if result[2] == "failed"
                    else f"all {result[1]} tests must pass"
                ),
            )
    if requirement_id == "REQ-03":
        result = _observed_metric(
            text,
            r"(?:answer )?(?:quality|accuracy)\s*(?:of|at|:|=|was|is)?\s*"
            r"(\d+(?:\.\d+)?)\s*%",
        )
        if result:
            return f"{result.group(1)}%", "at least 90%"
    if requirement_id == "REQ-04":
        result = _observed_metric(
            text,
            r"p95.{0,40}?(\d+(?:\.\d+)?)\s*(ms|milliseconds|s|seconds|second)\b",
        )
        if result:
            unit = "milliseconds" if result.group(2).startswith("m") else "seconds"
            return f"{result.group(1)} {unit}", "at most 2.0 seconds"
    if requirement_id == "REQ-05":
        result = _observed_metric(
            text,
            r"(?:cost|per successful request).{0,60}?"
            r"(?:usd\s*)?\$?\s*(\d+(?:\.\d+)?)",
        )
        if result:
            return f"USD {result.group(1)} per successful request", "at most USD 0.012"
    if requirement_id == "REQ-10":
        result = _counted_outcome(requirement_id, text)
        if result:
            return (
                f"{result[0]}/60 documents {result[2]}",
                "60/60 documents must pass",
            )
    return None


def _failure_excerpt(text: str) -> str:
    for sentence in re.split(r"[\n.!?;]+", text):
        if _is_explicit_failure(sentence) or re.search(
            r"\b(?:failed|failure|exposure|rejected|exceeded|above threshold)\b",
            sentence,
        ):
            excerpt = " ".join(sentence.split())
            if excerpt:
                return excerpt[:240]
    return "Jira evidence explicitly records an unmet acceptance criterion."


def _decision_reasoning(
    requirement_id: str,
    decision: Decision,
    evidence_texts: list[str],
    context: dict[str, str],
) -> str:
    combined = "\n".join(evidence_texts)
    measurement = next(
        (
            result
            for text in evidence_texts
            if (result := _measurement(requirement_id, text)) is not None
        ),
        None,
    )
    name = MANDATORY_REQUIREMENTS.get(requirement_id, requirement_id)
    if decision is Decision.INSUFFICIENT_EVIDENCE:
        return (
            f"Applicable Jira evidence does not establish {name} for release "
            f"{context['release']}, commit {context['commit']}, service "
            f"{context['service']} in {context['environment']}."
        )
    if decision is Decision.FAIL:
        if measurement:
            return (
                f"Measured {measurement[0]}, which violates the acceptance "
                f"threshold ({measurement[1]})."
            )
        return f"Jira evidence records a concrete failure: {_failure_excerpt(combined)}"
    if measurement:
        return (
            f"Measured {measurement[0]}, satisfying the acceptance threshold "
            f"({measurement[1]})."
        )
    if requirement_id == "REQ-06":
        return (
            f"Asha Rao's security approval explicitly covers release "
            f"{context['release']} and commit {context['commit']} for production."
        )
    pass_explanations = {
        "REQ-01": "Jira regression evidence states the mandatory regression tests passed.",
        "REQ-02": "Jira verification reports that customer document isolation passed or no cross-customer exposure was found.",
        "REQ-07": "QA verified sensitive data redaction in the target service's logs.",
        "REQ-08": "Jira evidence confirms human handoff delivery to the support queue with dependency handling.",
        "REQ-09": "Jira evidence records a successful, approved production rollback rehearsal.",
        "REQ-11": "QA verified keyboard navigation and focus behavior.",
        "REQ-12": "Production streaming verification found no duplicate or missing final messages.",
    }
    explanation = pass_explanations.get(
        requirement_id,
        f"Applicable Jira evidence explicitly verifies {name}.",
    )
    return (
        f"{explanation} The evidence applies to release {context['release']}, "
        f"commit {context['commit']}, service {context['service']} in "
        f"{context['environment']}."
    )


_EVIDENCE_TERMS: dict[str, tuple[str, ...]] = {
    "REQ-01": ("regression", "test", "passed", "failed"),
    "REQ-02": ("exposure", "isolation", "leakage"),
    "REQ-03": ("quality", "accuracy", "score"),
    "REQ-04": ("p95", "latency"),
    "REQ-05": ("cost", "successful request"),
    "REQ-06": ("asha rao", "approved", "security"),
    "REQ-07": ("redaction", "redacted", "logs"),
    "REQ-08": ("handoff", "support queue", "delivery"),
    "REQ-09": ("rollback", "rehearsal"),
    "REQ-10": ("parsing", "documents"),
    "REQ-11": ("keyboard", "focus"),
    "REQ-12": ("stream", "duplicate", "missing"),
}


def _evidence_excerpt(source_text: str, requirement_id: str) -> str:
    limit = 1500
    if len(source_text) <= limit:
        return source_text
    lowered = source_text.lower()
    positions = [
        position
        for term in _EVIDENCE_TERMS.get(requirement_id, ())
        if (position := lowered.find(term)) >= 0
    ]
    start = max(0, min(positions, default=0) - 250)
    end = min(len(source_text), start + limit)
    excerpt = source_text[start:end].strip()
    if start:
        excerpt = "..." + excerpt
    if end < len(source_text):
        excerpt += "..."
    return excerpt


def _public_evidence(
    record: dict[str, Any],
    source_text: str,
    comment_id: str | None,
    source_type: str,
    requirement_id: str,
) -> dict[str, Any]:
    fields = record.get("fields", {})
    return {
        "issue_key": str(record.get("key", "")),
        "comment_id": comment_id,
        "summary": jira_text(fields.get("summary", "")),
        "evidence_details": _evidence_excerpt(source_text, requirement_id),
        "source_type": source_type,
        "source_identifier": _source_identifier(record, source_text),
    }


def _is_requirement_definition(record: dict[str, Any]) -> bool:
    fields = record.get("fields", {})
    issue_type = fields.get("issuetype") or {}
    return (
        jira_text(issue_type.get("name", "")).strip().lower() == "requirement"
        or re.search(
            r"(?im)^\s*kind\s*:\s*requirement\s*$",
            jira_text(fields.get("description", "")),
        )
        is not None
    )


def validate_evidence(
    requirement_id: str,
    context: dict[str, str],
    evidence_records: list[dict[str, Any]],
) -> tuple[Decision, str, list[dict[str, Any]], list[str], float | None]:
    name = MANDATORY_REQUIREMENTS.get(requirement_id, requirement_id)
    evidence_records = [
        record
        for record in evidence_records
        if not _is_requirement_definition(record)
    ]
    if not evidence_records:
        return (
            Decision.INSUFFICIENT_EVIDENCE,
            f"No outcome evidence was retrieved for {name}.",
            [],
            [_MISSING_EVIDENCE.get(requirement_id, f"Evidence for {name} is missing.")],
            None,
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
            if requirement_id == "REQ-06":
                approval_text = source_text.lower()
                if not re.search(rf"\b{re.escape(release)}\b", approval_text):
                    continue
                if not re.search(rf"\b{re.escape(service)}\b", approval_text):
                    continue
                if not _commit_matches("", source_text, context["commit"]):
                    rejected_commit = True
                    continue
                if not _environment_matches("", source_text, environment):
                    rejected_environment = True
                    continue
            if (
                requirement_id == "REQ-03"
                and not re.search(
                    rf"\b{re.escape(context['prompt_version'].lower())}\b",
                    source_text.lower(),
                )
            ):
                rejected_prompt_version = True
                continue
            context_matches.append(
                (record, source_text.lower(), comment_id, source_type, source_text)
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
            [
                f"Evidence must identify release {context['release']}, commit "
                f"{context['commit']}, service {context['service']}, and "
                f"environment {context['environment']}.",
                _MISSING_EVIDENCE.get(requirement_id, f"Outcome evidence for {name} is missing."),
            ],
            None,
        )

    evidence_texts = [text for _, text, _, _, _ in context_matches]
    evidence_text = "\n".join(evidence_texts)

    def public_evidence_for(
        matches: list[tuple[dict[str, Any], str, str | None, str, str]],
    ) -> list[dict[str, Any]]:
        return [
            _public_evidence(
                record,
                source_text,
                comment_id,
                source_type,
                requirement_id,
            )
            for record, _, comment_id, source_type, source_text in matches
        ]

    superseded_failure = (
        ("later qa retest" in evidence_text or "later retest" in evidence_text)
        and any(word in evidence_text for word in ("passed", "supersedes"))
    )
    failure_matches = [
        match for match in context_matches if _is_explicit_failure(match[1])
    ]
    if failure_matches and not superseded_failure:
        return (
            Decision.FAIL,
            _decision_reasoning(
                requirement_id,
                Decision.FAIL,
                [match[1] for match in failure_matches],
                context,
            ),
            public_evidence_for(failure_matches),
            [],
            None,
        )
    threshold_matches = [
        match
        for match in context_matches
        if _threshold_failure(requirement_id, match[1])
    ]
    if threshold_matches:
        return (
            Decision.FAIL,
            _decision_reasoning(
                requirement_id,
                Decision.FAIL,
                [match[1] for match in threshold_matches],
                context,
            ),
            public_evidence_for(threshold_matches),
            [],
            None,
        )
    pass_matches = [
        match
        for match in context_matches
        if _is_pass(requirement_id, match[1], context["prompt_version"])
    ]
    if pass_matches:
        return (
            Decision.PASS,
            _decision_reasoning(
                requirement_id,
                Decision.PASS,
                [match[1] for match in pass_matches],
                context,
            ),
            public_evidence_for(pass_matches),
            [],
            None,
        )

    return (
        Decision.INSUFFICIENT_EVIDENCE,
        _decision_reasoning(
            requirement_id, Decision.INSUFFICIENT_EVIDENCE, evidence_texts, context
        ),
        public_evidence_for(context_matches),
        [_MISSING_EVIDENCE.get(requirement_id, f"Outcome evidence for {name} is missing.")],
        None,
    )
