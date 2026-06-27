from studio.database.db import init_db
from studio.database.migrations import migrate
from studio.events.run_events import RunEvent
from studio.services.event_service import add_event, replay_events
from studio.services.project_service import create_project
from studio.services.run_service import create_run


def test_replay_events_rehydrates_persisted_events_in_order():
    init_db()
    migrate()

    project_id = create_project("Replay Project", "Test")
    run_id = create_run(project_id)

    first_id = add_event(run_id, "planner_started", "planner", "Planner started.")
    second_id = add_event(run_id, "coder_started", "coder", "Coder started.")

    seen = []

    def handler(event):
        seen.append(event)
        return event.event_type

    results = replay_events(run_id, handler)

    assert results == ["planner_started", "coder_started"]
    assert [event.event_id for event in seen] == [first_id, second_id]
    assert all(isinstance(event, RunEvent) for event in seen)
    assert all(event.project_id == project_id for event in seen)
