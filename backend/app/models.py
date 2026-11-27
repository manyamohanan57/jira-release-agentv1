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


MANDATORY_REQUIREMENTS: dict[str, str] = {
    "REQ-01": "Automated Regression",
    "REQ-02": "Customer Document Isolation",
    "REQ-03": "Answer Quality",
    "REQ-04": "Response Latency",
    "REQ-05": "Model Usage Cost",
    "REQ-06": "Security Approval",
    "REQ-07": "Sensitive Log Redaction",
    "REQ-08": "Human Handoff",
    "REQ-09": "Rollback Rehearsal",
    "REQ-10": "Document Parsing",
    "REQ-11": "Keyboard Accessibility",
    "REQ-12": "Streaming Integrity",
}


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


class EvidenceItem(BaseModel):
    issue_key: str
    summary: str
    evidence_details: str
    source_type: str = "Jira"
    comment_id: str | None = None


class RequirementResult(BaseModel):
    requirement_id: str
    requirement_name: str
    status: Decision
    reasoning: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    mandatory: bool = True


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
    project_key: str | None = None
    dataset_label: str = "tyn-release-assessment-v2"
    target_release: str = "R2.4"
    release: str | None = None
    commit: str = "b7a91f2"
    service: str = "atlas-assistant"
    environment: str = "production"
    prompt_version: str = "p7"

    @property
    def effective_project_key(self) -> str:
        from app.config import settings
        return self.project_key or settings.jira_project_key

    @property
    def effective_release(self) -> str:
        return self.release or self.target_release


class ImportRequest(BaseModel):
    project_key: str
    dataset_path: str
    dataset_label: str = "tyn-release-assessment-v2"


class ImportResult(BaseModel):
    imported: int
    skipped: int
    project_key: str
    dataset_label: str
    reused: int = 0
    comments_imported: int = 0
    links_imported: int = 0
    relationships_skipped: int = 0


class ReleaseReadinessReport(BaseModel):
    report_id: str
    project_key: str | None = None
    dataset_label: str | None = None
    target_release: str = "R2.4"
    release: str = "R2.4"
    commit: str = "b7a91f2"
    service: str = "atlas-assistant"
    environment: str = "production"
    prompt_version: str = "p7"
    assessment_summary: str = ""
    summary: str = ""
    overall_decision: OverallDecision = OverallDecision.NEEDS_REVIEW
    overall_status: OverallDecision = OverallDecision.NEEDS_REVIEW
    requirements: list[Any] = Field(default_factory=list)
    tool_trace: list[ToolTraceEntry] = Field(default_factory=list)
    usage: UsageMetrics
    generated_at: datetime
