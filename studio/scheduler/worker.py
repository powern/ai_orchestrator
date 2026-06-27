import time

from studio.config.settings import DEFAULT_MODELS
from studio.core.llm_adapter import LLMAdapter
from studio.core.run_pipeline import RunPipeline
from studio.database.db import init_db, get_connection
from studio.database.migrations import migrate
from studio.events.publisher import publish_run_event
from studio.services.project_status_service import update_project_status
from studio.services.run_service import (
    get_next_queued_run,
    update_run_status,
    save_stage_output,
)


def get_project_for_run(run):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM projects WHERE id = ?",
            (run["project_id"],),
        ).fetchone()


def run_planner_stage(run_id, project):
    update_run_status(run_id, "running", "planner")
    publish_run_event(run_id, project["id"], "planner_started", "planner", "Planner started.")

    adapter = LLMAdapter()

    planner_output = adapter.ask(
        model=DEFAULT_MODELS["planner"],
        system_prompt=(
            "You are Planner Agent. "
            "Create a concise numbered software development backlog. "
            "Do not write code."
        ),
        user_prompt=project["description"],
    )

    save_stage_output(run_id, "planner_output", planner_output)

    publish_run_event(
        run_id,
        project["id"],
        "planner_completed",
        "planner",
        "Planner completed.",
        planner_output,
    )

    return planner_output


def process_one_run():
    run = get_next_queued_run()
    if run is None:
        print("Scheduler heartbeat: no queued runs", flush=True)
        return False

    print(f"Scheduler picked run #{run['id']}", flush=True)

    run_id = run["id"]

    publish_run_event(run_id, run["project_id"], "scheduler", "scheduler", "Scheduler picked queued run.")
    project = get_project_for_run(run)

    try:
        pipeline = RunPipeline(run_planner_stage)
        pipeline.execute(run_id, project)

    except Exception as exc:
        update_run_status(run_id, "failed", "pipeline_failed", str(exc))
        publish_run_event(run_id, project["id"], "run_failed", "pipeline_failed", str(exc))

    finally:
        update_project_status(project["id"])

    return True


def main():
    init_db()
    migrate()

    print("AI Studio Scheduler started", flush=True)

    while True:
        processed = process_one_run()

        if not processed:
            time.sleep(5)


if __name__ == "__main__":
    main()
