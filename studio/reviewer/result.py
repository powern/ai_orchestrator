from dataclasses import dataclass

from studio.contracts.validation_report import ValidationReport


@dataclass
class ReviewerResult:
    score: int
    summary: str
    findings: list[str]
    approved: bool
    validation_report: ValidationReport | None = None

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "summary": self.summary,
            "findings": self.findings,
            "approved": self.approved,
            "validation_report": (
                self.validation_report.to_dict() if self.validation_report else None
            ),
        }
