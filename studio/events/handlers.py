class EventLogHandler:
    """
    Deprecated compatibility handler.

    Event storage is handled before projection by
    studio.services.event_service.add_event(). This handler intentionally does
    nothing to avoid recursive writes.
    """

    def __call__(self, event):
        return None


class RuntimeHandler:
    def __call__(self, event):
        if event.project_id is None:
            return None

        from studio.services.runtime_service import upsert_project_runtime

        status = "running"

        if event.event_type in ("run_completed", "run_completed_after_fix"):
            status = "completed"

        if event.event_type in ("run_failed", "run_failed_after_fix"):
            status = "failed"

        return upsert_project_runtime(
            project_id=event.project_id,
            run_id=event.run_id,
            status=status,
            current_stage=event.stage,
            current_agent=event.stage,
            message=event.message,
            last_event_id=event.event_id,
        )
