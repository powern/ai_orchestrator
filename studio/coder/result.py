from dataclasses import dataclass
from typing import Any


@dataclass
class PipelineResult:
    actions: list[dict[str, Any]]

    raw_output: str

    repaired_output: str

    attempts: int = 1

    retried: bool = False

    validation_error: str | None = None
