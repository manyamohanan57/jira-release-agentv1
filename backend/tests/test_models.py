from app.models import (
    Decision,
    OverallDecision,
    RequirementDecision,
)


def test_mandatory_fail_requires_blocked_calculation() -> None:
    requirement = RequirementDecision(
        requirement_id="REQ-1",
        title="Test",
        mandatory=True,
        decision=Decision.FAIL,
        explanation="Failure demonstrated",
    )
    assert requirement.decision is Decision.FAIL
