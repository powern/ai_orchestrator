from enum import StrEnum


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_RUN_STATUSES = {
    RunStatus.COMPLETED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
}


ALLOWED_RUN_STATUS_TRANSITIONS = {
    RunStatus.QUEUED: {
        RunStatus.RUNNING,
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    },
    RunStatus.RUNNING: {
        RunStatus.RUNNING,
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    },
    RunStatus.COMPLETED: set(),
    RunStatus.FAILED: set(),
    RunStatus.CANCELLED: set(),
}


def coerce_run_status(status: str | RunStatus) -> RunStatus:
    try:
        return status if isinstance(status, RunStatus) else RunStatus(status)
    except ValueError as exc:
        raise ValueError(f"Unsupported run status: {status}") from exc


def validate_run_status_transition(current: str | RunStatus, next_status: str | RunStatus) -> None:
    current_status = coerce_run_status(current)
    target_status = coerce_run_status(next_status)

    if current_status == target_status:
        return

    if target_status not in ALLOWED_RUN_STATUS_TRANSITIONS[current_status]:
        raise ValueError(
            f"Invalid run status transition: {current_status.value} -> {target_status.value}"
        )
