from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

from app.agent_tools import build_tools
from app.config import settings
from app.model_factory import build_chat_model, validate_model_configuration
from app.models import (
    Decision,
    OverallDecision,
    RequirementDecision,
    ReleaseReadinessReport,
    UsageMetrics,
)


def assess_release(project_key: str, dataset_label: str, target_release: str) -> ReleaseReadinessReport:
    started = perf_counter()
    validate_model_configuration(settings)
    build_chat_model(settings)

    build_tools(project_key, dataset_label)

    placeholder = RequirementDecision(
        requirement_id="NOT_AVAILABLE",
        title="Assessment agent awaiting configuration",
        mandatory=True,
        decision=Decision.INSUFFICIENT_EVIDENCE,
        explanation=(
            "The application scaffold is running, but the LangChain investigation "
            "workflow has not yet executed."
        ),
        outstanding=[
            "Configure the model and Jira credentials.",
            "Run the tool-driven requirement discovery and evidence assessment.",
        ],
    )

    elapsed_ms = int((perf_counter() - started) * 1000)
    return ReleaseReadinessReport(
        report_id=str(uuid4()),
        project_key=project_key,
        dataset_label=dataset_label,
        target_release=target_release,
        overall_decision=OverallDecision.NEEDS_REVIEW,
        requirements=[placeholder],
        usage=UsageMetrics(execution_time_ms=elapsed_ms, model_calls=0),
        generated_at=datetime.now(timezone.utc),
    )
