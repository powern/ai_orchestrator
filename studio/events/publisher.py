from studio.services.event_service import add_event


def publish_run_event(
    run_id,
    project_id,
    event_type,
    stage,
    message,
    payload=None,
):
    return add_event(
        run_id,
        event_type,
        stage,
        message,
        payload,
    )
