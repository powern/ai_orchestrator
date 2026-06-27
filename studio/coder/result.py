from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class PipelineResult:
    actions: List[Dict[str, Any]]

    raw_output: str

    repaired_output: str

    attempts: int = 1

    retried: bool = False

    validation_error: Optional[str] = None
