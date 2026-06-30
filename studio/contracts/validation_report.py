import json
from dataclasses import dataclass, field
from typing import Any

SEVERITY_WEIGHTS = {
    "critical": 3,
    "major": 2,
    "minor": 1,
}


@dataclass(frozen=True)
class ValidationEvidence:
    source: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "message": self.message,
            "data": self.data,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ValidationEvidence":
        value = value or {}
        return cls(
            source=value.get("source") or "unknown",
            message=value.get("message") or "",
            data=dict(value.get("data") or {}),
        )


@dataclass(frozen=True)
class ValidationViolation:
    id: str
    severity: str
    category: str
    message: str
    location: str | None = None
    expected: dict[str, Any] = field(default_factory=dict)
    actual: dict[str, Any] = field(default_factory=dict)
    contract_source: str = "static_reviewer"
    repair_hint: str = ""
    confidence: float = 1.0
    source: str = "static_reviewer"
    affected_files: list[str] = field(default_factory=list)
    related_project_specification: str | None = None
    related_execution_contract: str | None = None
    related_project_state: str | None = None
    evidence: list[ValidationEvidence] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
            "location": self.location,
            "expected": self.expected,
            "actual": self.actual,
            "contract_source": self.contract_source,
            "repair_hint": self.repair_hint,
            "confidence": self.confidence,
            "source": self.source,
            "affected_files": self.affected_files,
            "related_project_specification": self.related_project_specification,
            "related_execution_contract": self.related_execution_contract,
            "related_project_state": self.related_project_state,
            "evidence": [item.to_dict() for item in self.evidence],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ValidationViolation":
        value = value or {}
        return cls(
            id=value.get("id") or "unknown_validation_violation",
            severity=value.get("severity") or "major",
            category=value.get("category") or "static_analysis",
            message=value.get("message") or "",
            location=value.get("location"),
            expected=dict(value.get("expected") or {}),
            actual=dict(value.get("actual") or {}),
            contract_source=value.get("contract_source") or "static_reviewer",
            repair_hint=value.get("repair_hint") or "",
            confidence=float(value.get("confidence", 1.0)),
            source=value.get("source") or "static_reviewer",
            affected_files=list(value.get("affected_files") or []),
            related_project_specification=value.get("related_project_specification"),
            related_execution_contract=value.get("related_execution_contract"),
            related_project_state=value.get("related_project_state"),
            evidence=[
                ValidationEvidence.from_dict(item)
                for item in value.get("evidence") or []
                if isinstance(item, dict)
            ],
        )


@dataclass(frozen=True)
class ValidationReport:
    approved: bool
    summary: dict[str, int]
    violations: list[ValidationViolation] = field(default_factory=list)
    source: str = "static_reviewer"
    score: int = 100
    status: str = "passed"
    single_source_of_truth: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "summary": self.summary,
            "violations": [item.to_dict() for item in self.violations],
            "source": self.source,
            "score": self.score,
            "status": self.status,
            "single_source_of_truth": self.single_source_of_truth,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def findings(self) -> list[str]:
        return [violation.message for violation in self.violations]

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ValidationReport":
        value = value or {}
        violations = [
            ValidationViolation.from_dict(item)
            for item in value.get("violations") or []
            if isinstance(item, dict)
        ]
        summary = value.get("summary") or summarize_violations(violations)
        approved = bool(value.get("approved", not violations))
        status = value.get("status") or ("passed" if approved else "failed")
        return cls(
            approved=approved,
            summary=dict(summary),
            violations=violations,
            source=value.get("source") or "static_reviewer",
            score=int(value.get("score", score_violations(violations))),
            status=status,
            single_source_of_truth=dict(value.get("single_source_of_truth") or {}),
        )


def summarize_violations(violations: list[ValidationViolation]) -> dict[str, int]:
    summary = {"critical": 0, "major": 0, "minor": 0}
    for violation in violations:
        severity = violation.severity if violation.severity in summary else "major"
        summary[severity] += 1
    return summary


def score_violations(violations: list[ValidationViolation]) -> int:
    penalty = sum(SEVERITY_WEIGHTS.get(item.severity, 2) * 20 for item in violations)
    return max(0, 100 - penalty)


def build_validation_report(
    violations: list[ValidationViolation],
    source: str = "static_reviewer",
    single_source_of_truth: dict[str, Any] | None = None,
) -> ValidationReport:
    summary = summarize_violations(violations)
    score = score_violations(violations)
    approved = summary["critical"] == 0 and score >= 80
    return ValidationReport(
        approved=approved,
        summary=summary,
        violations=violations,
        source=source,
        score=score,
        status="passed" if approved else "failed",
        single_source_of_truth=single_source_of_truth or {},
    )


def violation(
    id: str,
    severity: str,
    category: str,
    message: str,
    location: str | None = None,
    expected: dict[str, Any] | None = None,
    actual: dict[str, Any] | None = None,
    repair_hint: str = "",
    source: str = "static_reviewer",
    contract_source: str = "static_reviewer",
    affected_files: list[str] | None = None,
    related_project_specification: str | None = None,
    related_execution_contract: str | None = None,
    related_project_state: str | None = None,
    confidence: float = 1.0,
    evidence: list[ValidationEvidence] | None = None,
) -> ValidationViolation:
    files = affected_files or ([location] if location else [])
    return ValidationViolation(
        id=id,
        severity=severity,
        category=category,
        message=message,
        location=location,
        expected=expected or {},
        actual=actual or {},
        contract_source=contract_source,
        repair_hint=repair_hint,
        confidence=confidence,
        source=source,
        affected_files=files,
        related_project_specification=related_project_specification,
        related_execution_contract=related_execution_contract,
        related_project_state=related_project_state,
        evidence=evidence
        or [
            ValidationEvidence(
                source=source,
                message=message,
                data={"location": location} if location else {},
            )
        ],
    )
