from studio.services.event_service import add_event


def publish_run_event(
    run_id,
    project_id=None,
    event_type=None,
    stage=None,
    message="",
    payload=None,
):
    if event_type is None:
        raise ValueError("event_type is required")

    return add_event(
        run_id,
        event_type,
        stage,
        message,
        payload,
    )
