from studio.events.bus import EventBus
from studio.events.run_events import RunEvent


def test_event_bus_calls_subscribed_handlers():
    bus = EventBus()
    received = []

    def handler(event):
        received.append(event)
        return "ok"

    bus.subscribe(handler)

    event = RunEvent(
        run_id=1,
        project_id=2,
        event_type="tester_completed",
        stage="tester",
        message="Tester completed.",
    )

    results = bus.publish(event)

    assert results == ["ok"]
    assert received == [event]


def test_event_bus_allows_multiple_handlers():
    bus = EventBus()
    calls = []

    bus.subscribe(lambda event: calls.append(("a", event.event_type)))
    bus.subscribe(lambda event: calls.append(("b", event.stage)))

    bus.publish(
        RunEvent(
            run_id=1,
            project_id=2,
            event_type="planner_started",
            stage="planner",
            message="Planner started.",
        )
    )

    assert calls == [
        ("a", "planner_started"),
        ("b", "planner"),
    ]
