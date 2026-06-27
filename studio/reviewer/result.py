from dataclasses import dataclass


@dataclass
class ReviewerResult:
    score: int
    summary: str
    findings: list[str]
    approved: bool
