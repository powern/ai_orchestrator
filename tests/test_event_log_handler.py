from studio.events.handlers import EventLogHandler
from studio.events.run_events import RunEvent


def test_event_log_handler_is_noop_compatibility_handler():
    handler = EventLogHandler()

    result = handler(
        RunEvent(
            run_id=1,
            project_id=2,
            event_type="planner_started",
            stage="planner",
            message="Planner started.",
            payload="payload",
        )
    )

    assert result is None
