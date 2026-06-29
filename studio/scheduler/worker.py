import logging
import time

from studio.config.settings import DEFAULT_MODELS, SCHEDULER_POLL_INTERVAL_SECONDS
from studio.contracts import append_handoff, build_agent_context, build_handoff
from studio.core.llm_adapter import LLMAdapter
from studio.core.run_pipeline import RunPipeline
from studio.database.db import get_connection, init_db
from studio.database.migrations import migrate
from studio.events.publisher import publish_run_event
from studio.services.project_status_service import update_project_status
from studio.services.run_service import (
    get_next_queued_run,
    save_stage_output,
    update_run_status,
)

logger = logging.getLogger(__name__)


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
    agent_context = build_agent_context(
        run_id,
        "planner",
        previous_stage_outputs={"planner_output": planner_output},
    )
    append_handoff(
        run_id,
        "planner",
        build_handoff(
            producer="planner",
            consumer="architect",
            summary="Planner defined project goals, constraints, and success criteria.",
            agent_context=agent_context,
            implementation_contract={"output": "development_backlog"},
            recommended_focus=["architecture", "acceptance criteria", "test strategy"],
        ),
        workspace_path=project["workspace_path"],
    )

    return planner_output


def process_one_run():
    run = get_next_queued_run()
    if run is None:
        logger.info("Scheduler heartbeat: no queued runs")
        return False

    logger.info("Scheduler picked run #%s", run["id"])

    run_id = run["id"]

    publish_run_event(
        run_id, run["project_id"], "scheduler", "scheduler", "Scheduler picked queued run."
    )
    project = get_project_for_run(run)

    try:
        pipeline = RunPipeline(run_planner_stage)
        pipeline.execute(run_id, project)

    except Exception as exc:
        logger.exception("Run #%s failed during scheduler processing", run_id)
        update_run_status(run_id, "failed", "pipeline_failed", str(exc))
        publish_run_event(run_id, project["id"], "run_failed", "pipeline_failed", str(exc))

    finally:
        update_project_status(project["id"])

    return True


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    init_db()
    migrate()

    logger.info("AI Studio Scheduler started")

    while True:
        processed = process_one_run()

        if not processed:
            time.sleep(SCHEDULER_POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
