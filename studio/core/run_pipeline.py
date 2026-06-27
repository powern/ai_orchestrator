import json

from studio.config.settings import DEFAULT_MODELS, FIX_MAX_SANITIZE_ATTEMPTS
from studio.core.json_utils import normalize_coder_json
from studio.core.llm_adapter import LLMAdapter
from studio.core.stages import (
    run_architect_stage,
    run_coder_placeholder,
    run_executor_stage,
    run_fix_stage,
    run_tester_stage,
)
from studio.core.tester_result import StageTestResult
from studio.database.db import get_connection
from studio.events.publisher import publish_run_event
from studio.reviewer.static_agent import StaticReviewerAgent
from studio.sanitizer.agent import ActionSanitizerAgent
from studio.services.run_service import (
    save_stage_output,
    update_run_status,
)


def add_event(run_id, event_type, stage=None, message="", payload=None):
    return publish_run_event(
        run_id=run_id,
        event_type=event_type,
        stage=stage,
        message=message,
        payload=payload,
    )


def get_project_id(project):
    try:
        return project["id"]
    except Exception:
        return None


def get_project_id_for_run(run_id):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT project_id FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()

    if row is None:
        return None

    return row["project_id"]


def sanitize_fix_output(run_id, fix_output):
    sanitizer = ActionSanitizerAgent(
        adapter=LLMAdapter(),
        model=DEFAULT_MODELS["coder"],
    )

    result = sanitizer.process(
        fix_output,
        max_attempts=FIX_MAX_SANITIZE_ATTEMPTS,
    )

    normalized_output = json.dumps(
        result.actions,
        ensure_ascii=False,
        indent=2,
    )

    save_stage_output(run_id, "coder_output", normalized_output)

    add_event(
        run_id,
        "fix_sanitized",
        "static_reviewer",
        "Fix output sanitized to Executor JSON.",
        normalized_output,
    )

    return result.actions, normalized_output


class RunPipeline:

    def __init__(self, planner_fn):
        self.planner_fn = planner_fn

    def execute(self, run_id, project):
        project_id = get_project_id(project) or get_project_id_for_run(run_id)
        planner_output = self.planner_fn(run_id, project)

        architect_output = run_architect_stage(
            run_id,
            planner_output,
        )

        coder_output = run_coder_placeholder(
            run_id,
            planner_output,
            architect_output,
        )

        static_review = StaticReviewerAgent().review(
            normalize_coder_json(coder_output),
        )

        add_event(
            run_id,
            "static_review_completed",
            "static_reviewer",
            "Static review completed.",
            str(static_review),
        )

        if not static_review.approved:
            add_event(
                run_id,
                "static_review_failed",
                "static_reviewer",
                "Static review rejected executor actions.",
                str(static_review.findings),
            )

            static_failure = StageTestResult(
                success=False,
                returncode=1,
                stdout="Static review rejected executor actions.",
                stderr="\n".join(static_review.findings),
            )

            fix_result = run_fix_stage(
                run_id,
                project["workspace_path"],
                coder_output,
                static_failure,
            )

            actions, coder_output = sanitize_fix_output(
                run_id,
                fix_result["output"],
            )

            static_review = StaticReviewerAgent().review(actions)

            if not static_review.approved:
                update_run_status(
                    run_id,
                    "failed",
                    "static_review_failed",
                    "Run failed because static review rejected executor actions after fix.",
                )

                add_event(
                    run_id,
                    "run_failed",
                    "static_review_failed",
                    "Run failed because static review rejected executor actions after fix.",
                    str(static_review.findings),
                )

                return

        run_executor_stage(
            run_id,
            project["workspace_path"],
            coder_output,
        )

        tester_result = run_tester_stage(
            run_id,
            project["workspace_path"],
        )

        if tester_result.success:
            update_run_status(
                run_id,
                "completed",
                "tester_completed",
                "Planner, Architect, Coder, Executor, and Tester stages completed successfully.",
            )

            publish_run_event(
                run_id,
                project_id,
                "run_completed",
                "tester_completed",
                "Run completed after tester stage.",
            )

            return

        fix_result = run_fix_stage(
            run_id,
            project["workspace_path"],
            coder_output,
            tester_result,
        )

        actions, coder_output = sanitize_fix_output(
            run_id,
            fix_result["output"],
        )

        static_review = StaticReviewerAgent().review(actions)

        add_event(
            run_id,
            "static_review_completed_after_fix",
            "static_reviewer",
            "Static review completed after tester fix.",
            str(static_review),
        )

        if not static_review.approved:
            update_run_status(
                run_id,
                "failed",
                "static_review_failed",
                "Run failed because static review rejected tester fix actions.",
            )

            add_event(
                run_id,
                "run_failed",
                "static_review_failed",
                "Run failed because static review rejected tester fix actions.",
                str(static_review.findings),
            )

            return

        run_executor_stage(
            run_id,
            project["workspace_path"],
            coder_output,
        )

        tester_result = run_tester_stage(
            run_id,
            project["workspace_path"],
        )

        if tester_result.success:
            update_run_status(
                run_id,
                "completed",
                "tester_completed",
                "Run completed after automatic fix.",
            )

            publish_run_event(
                run_id,
                project_id,
                "run_completed_after_fix",
                "tester_completed",
                "Run completed after automatic fix.",
            )

            return

        update_run_status(
            run_id,
            "failed",
            "tester_failed",
            "Run failed after automatic fix.",
        )

        publish_run_event(
            run_id,
            project_id,
            "run_failed_after_fix",
            "tester_failed",
            "Run failed after automatic fix.",
        )
