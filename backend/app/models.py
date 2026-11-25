from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Decision(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class OverallDecision(str, Enum):
    READY = "READY"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    BLOCKED = "BLOCKED"


class EvidenceReference(BaseModel):
    ticket_key: str
    comment_id: str | None = None
    source_identifier: str | None = None
    summary: str
    applicability: str


class RequirementDecision(BaseModel):
    requirement_id: str
    title: str
    mandatory: bool = True
    decision: Decision
    explanation: str
    evidence: list[EvidenceReference] = Field(default_factory=list)
    outstanding: list[str] = Field(default_factory=list)


class ToolTraceEntry(BaseModel):
    tool: str
    arguments: dict[str, Any]
    started_at: datetime
    completed_at: datetime
    duration_ms: int
    success: bool
    result_summary: str


class UsageMetrics(BaseModel):
    execution_time_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    model_calls: int = 0


class AssessmentRequest(BaseModel):
    project_key: str
    dataset_label: str = "tyn-release-assessment-v2"
    target_release: str


class ImportRequest(BaseModel):
    project_key: str
    dataset_path: str
    dataset_label: str = "tyn-release-assessment-v2"


class ImportResult(BaseModel):
    imported: int
    skipped: int
    project_key: str
    dataset_label: str


class ReleaseReadinessReport(BaseModel):
    report_id: str
    project_key: str
    dataset_label: str
    target_release: str
    overall_decision: OverallDecision
    requirements: list[RequirementDecision]
    tool_trace: list[ToolTraceEntry] = Field(default_factory=list)
    usage: UsageMetrics
    generated_at: datetime
