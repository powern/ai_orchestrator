import inspect
import json

from studio.config.settings import (
    DEFAULT_MODELS,
    FIX_MAX_OUTPUT_RETRIES,
    FIX_MAX_SANITIZE_ATTEMPTS,
)
from studio.core.executor_schema import validate_executor_actions
from studio.core.json_utils import normalize_coder_json
from studio.core.llm_adapter import LLMAdapter
from studio.core.runtime_readiness import RuntimeReadinessValidator
from studio.core.stages import (
    run_architect_stage,
    run_coder_placeholder,
    run_coder_revision_stage,
    run_engineering_critic_stage,
    run_executor_stage,
    run_fix_stage,
    run_tester_stage,
)
from studio.core.tester_result import StageTestResult
from studio.database.db import get_connection
from studio.events.publisher import publish_run_event
from studio.reviewer.static_agent import StaticReviewerAgent
from studio.sanitizer.agent import ActionSanitizerAgent
from studio.services.engineering_service import record_engineering_shadow_assessment
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

    try:
        result = sanitizer.process(
            fix_output,
            max_attempts=FIX_MAX_SANITIZE_ATTEMPTS,
        )
    except Exception as exc:
        save_stage_output(run_id, "fix_sanitizer_error", str(exc))
        raise

    normalized_output = json.dumps(
        result.actions,
        ensure_ascii=False,
        indent=2,
    )
    validate_executor_actions(result.actions)

    save_stage_output(run_id, "fix_output", normalized_output)

    add_event(
        run_id,
        "fix_sanitized",
        "static_reviewer",
        "Fix output sanitized to Executor JSON.",
        normalized_output,
    )

    return result.actions, normalized_output


def sanitize_fix_output_or_fail(
    run_id,
    fix_output,
    workspace_path,
    coder_output,
    tester_result,
    trigger_stage="tester_failed",
    static_review_output=None,
    rejected_actions=None,
):
    current_output = fix_output

    for retry_number in range(0, FIX_MAX_OUTPUT_RETRIES + 1):
        try:
            sanitized_fix = sanitize_fix_output(run_id, current_output)
        except Exception as exc:
            save_stage_output(run_id, "fix_sanitizer_error", str(exc))

            if retry_number >= FIX_MAX_OUTPUT_RETRIES:
                update_run_status(
                    run_id,
                    "failed",
                    "fix_failed",
                    f"Fix output could not be sanitized: {exc}",
                )

                add_event(
                    run_id,
                    "fix_failed",
                    "fix_failed",
                    "Fix output could not be sanitized after retries.",
                    str(exc),
                )

                add_event(
                    run_id,
                    "run_failed",
                    "fix_failed",
                    "Run failed because fix output was invalid.",
                    str(exc),
                )

                return None

            add_event(
                run_id,
                "fix_retry",
                "fix",
                f"Fix retry #{retry_number + 1} after sanitizer error.",
                str(exc),
            )

            fix_result = _run_fix_stage_with_context(
                run_id,
                workspace_path,
                coder_output,
                tester_result,
                {
                    "previous_error": exc,
                    "previous_raw_output": current_output,
                    "emit_started": False,
                    "trigger_stage": trigger_stage,
                    "static_review_output": static_review_output,
                    "rejected_actions": rejected_actions,
                },
            )
            current_output = fix_result["output"]
            continue

        add_event(
            run_id,
            "fix_completed",
            "fix",
            "Fix output sanitized and ready for static review.",
            sanitized_fix[1],
        )
        return sanitized_fix

    return None


def _run_fix_stage_with_context(run_id, workspace_path, coder_output, tester_result, context):
    signature = inspect.signature(run_fix_stage)

    accepts_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )

    if accepts_kwargs:
        supported_context = context
    else:
        supported_context = {
            key: value for key, value in context.items() if key in signature.parameters
        }

    return run_fix_stage(
        run_id,
        workspace_path,
        coder_output,
        tester_result,
        **supported_context,
    )


def run_runtime_readiness_stage(run_id, workspace_path):
    add_event(
        run_id,
        "runtime_readiness_started",
        "runtime_readiness",
        "Runtime readiness validation started.",
    )
    report = RuntimeReadinessValidator().validate(workspace_path)
    report_json = report.to_json()
    save_stage_output(run_id, "runtime_readiness", report_json)

    if report.manual_run_ready:
        add_event(
            run_id,
            "runtime_readiness_completed",
            "runtime_readiness",
            "Runtime readiness validation passed.",
            report_json,
        )
        return True, report

    update_run_status(
        run_id,
        "failed",
        "runtime_readiness_failed",
        "Run failed because runtime readiness validation failed.",
    )
    add_event(
        run_id,
        "runtime_readiness_failed",
        "runtime_readiness",
        "Runtime readiness validation failed.",
        report_json,
    )
    add_event(
        run_id,
        "run_failed",
        "runtime_readiness_failed",
        "Run failed because generated project is not manually runnable.",
        report_json,
    )
    return False, report


class RunPipeline:
    def __init__(self, planner_fn):
        self.planner_fn = planner_fn

    def execute(self, run_id, project):
        def maybe_record_engineering_shadow():
            try:
                record_engineering_shadow_assessment(run_id, project)
            except Exception:
                return None

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

        if coder_output is None:
            maybe_record_engineering_shadow()
            return

        critic_result = run_engineering_critic_stage(
            run_id,
            planner_output,
            architect_output,
            coder_output,
        )

        if critic_result.status == "revision_required":
            coder_output = run_coder_revision_stage(
                run_id,
                planner_output,
                architect_output,
                coder_output,
                critic_result,
            )
            critic_result = run_engineering_critic_stage(
                run_id,
                planner_output,
                architect_output,
                coder_output,
            )

            if critic_result.status == "revision_required":
                update_run_status(
                    run_id,
                    "failed",
                    "engineering_critic",
                    "Run failed because Engineering Critic still requires revision.",
                )
                add_event(
                    run_id,
                    "run_failed",
                    "engineering_critic",
                    "Run failed because Engineering Critic still requires revision.",
                    critic_result.to_json(),
                )
                maybe_record_engineering_shadow()
                return

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
            static_review_output = json.dumps(
                {
                    "summary": static_review.summary,
                    "score": static_review.score,
                    "approved": static_review.approved,
                    "findings": static_review.findings,
                },
                ensure_ascii=False,
                indent=2,
            )
            save_stage_output(run_id, "executor_output", static_review_output)
            save_stage_output(
                run_id,
                "bug_report",
                "Static review rejected executor actions.\n"
                + "\n".join(static_review.findings),
            )
            add_event(
                run_id,
                "static_review_failed",
                "static_reviewer",
                "Static review rejected executor actions.",
                static_review_output,
            )

            static_failure = StageTestResult(
                success=False,
                returncode=1,
                stdout="Static review rejected executor actions.",
                stderr="\n".join(static_review.findings),
            )

            fix_result = _run_fix_stage_with_context(
                run_id,
                project["workspace_path"],
                coder_output,
                static_failure,
                {
                    "trigger_stage": "static_review_failed",
                    "static_review_output": static_review_output,
                    "rejected_actions": coder_output,
                },
            )

            sanitized_fix = sanitize_fix_output_or_fail(
                run_id,
                fix_result["output"],
                project["workspace_path"],
                coder_output,
                static_failure,
                trigger_stage="static_review_failed",
                static_review_output=static_review_output,
                rejected_actions=coder_output,
            )
            if sanitized_fix is None:
                maybe_record_engineering_shadow()
                return
            actions, coder_output = sanitized_fix

            static_review = StaticReviewerAgent().review(actions)

            add_event(
                run_id,
                "static_review_completed_after_fix",
                "static_reviewer",
                "Static review completed after static review fix.",
                str(static_review),
            )

            if not static_review.approved:
                after_fix_output = json.dumps(
                    {
                        "summary": static_review.summary,
                        "score": static_review.score,
                        "approved": static_review.approved,
                        "findings": static_review.findings,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                save_stage_output(run_id, "executor_output", after_fix_output)
                save_stage_output(
                    run_id,
                    "bug_report",
                    "Static review rejected executor actions after fix.\n"
                    + "\n".join(static_review.findings),
                )
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
                    after_fix_output,
                )

                maybe_record_engineering_shadow()
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
        save_stage_output(
            run_id,
            "tester_output_before_fix",
            str(tester_result.to_dict()),
        )

        if tester_result.success:
            readiness_ok, _ = run_runtime_readiness_stage(run_id, project["workspace_path"])
            if not readiness_ok:
                maybe_record_engineering_shadow()
                return

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

            maybe_record_engineering_shadow()
            return

        fix_result = run_fix_stage(
            run_id,
            project["workspace_path"],
            coder_output,
            tester_result,
        )

        sanitized_fix = sanitize_fix_output_or_fail(
            run_id,
            fix_result["output"],
            project["workspace_path"],
            coder_output,
            tester_result,
        )
        if sanitized_fix is None:
            maybe_record_engineering_shadow()
            return
        actions, coder_output = sanitized_fix

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

            maybe_record_engineering_shadow()
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
        save_stage_output(
            run_id,
            "tester_output_after_fix",
            str(tester_result.to_dict()),
        )

        if tester_result.success:
            readiness_ok, _ = run_runtime_readiness_stage(run_id, project["workspace_path"])
            if not readiness_ok:
                maybe_record_engineering_shadow()
                return

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

            maybe_record_engineering_shadow()
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
        maybe_record_engineering_shadow()
