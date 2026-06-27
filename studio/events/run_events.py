from dataclasses import dataclass
from typing import Any


@dataclass
class RunEvent:
    run_id: int
    project_id: int | None
    event_type: str
    stage: str
    message: str
    payload: Any = None
    event_id: int | None = None
