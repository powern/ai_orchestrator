import inspect
import json

from studio.config.settings import (
    DEFAULT_MODELS,
    FIX_MAX_OUTPUT_RETRIES,
    FIX_MAX_SANITIZE_ATTEMPTS,
)
from studio.contracts.project_specification import build_project_specification
from studio.core.executor_schema import validate_executor_actions
from studio.core.json_utils import normalize_coder_json
from studio.core.llm_adapter import LLMAdapter
from studio.core.project_state import ProjectStateBuilder
from studio.core.runtime_readiness import RuntimeReadinessValidator
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
    validation_report=None,
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
                    "validation_report": validation_report,
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


def static_review_payload(static_review):
    if getattr(static_review, "validation_report", None):
        return static_review.validation_report.to_json()
    if hasattr(static_review, "to_dict"):
        payload = static_review.to_dict()
    else:
        payload = {
            "summary": getattr(static_review, "summary", "Static review completed."),
            "score": getattr(static_review, "score", 0),
            "approved": getattr(static_review, "approved", False),
            "findings": getattr(static_review, "findings", []),
        }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def record_validation_report(run_id, static_review, event_type="validation_completed"):
    payload = static_review_payload(static_review)
    save_stage_output(run_id, "validation_report", payload)
    add_event(
        run_id,
        event_type,
        "static_reviewer",
        "Structured validation report generated.",
        payload,
    )
    if event_type != "validation_report_generated":
        add_event(
            run_id,
            "validation_report_generated",
            "static_reviewer",
            "Validation Report persisted for downstream agents.",
            payload,
        )
    report = getattr(static_review, "validation_report", None)
    for item in report.violations if report else []:
        add_event(
            run_id,
            "validation_violation_detected",
            "static_reviewer",
            item.message,
            json.dumps(item.to_dict(), ensure_ascii=False, indent=2),
        )
    return payload


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
    from studio.contracts import build_agent_context

    add_event(
        run_id,
        "runtime_readiness_started",
        "runtime_readiness",
        "Runtime readiness validation started.",
    )
    context = build_agent_context(run_id, "runtime_readiness", workspace_path=workspace_path)
    report = RuntimeReadinessValidator().validate(
        workspace_path,
        context.project.get("execution_contract"),
    )
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

        project_data = dict(project) if not isinstance(project, dict) else project
        project_id = get_project_id(project_data) or get_project_id_for_run(run_id)
        project_description = project_data.get("description", "")
        add_event(
            run_id,
            "project_specification_started",
            "project_specification",
            "Project specification extraction started.",
        )
        project_specification = build_project_specification(project_description).to_dict()
        add_event(
            run_id,
            "project_specification_completed",
            "project_specification",
            "Project specification extracted from original request.",
            json.dumps(project_specification, ensure_ascii=False),
        )
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

        coder_actions = normalize_coder_json(coder_output)
        static_project_state = ProjectStateBuilder().build(
            run_id=run_id,
            project_id=project_id,
            workspace_path=project_data["workspace_path"],
            executor_actions=coder_actions,
            project_specification=project_specification,
        )
        add_event(
            run_id,
            "validation_started",
            "static_reviewer",
            "Structured validation started.",
        )
        static_review = StaticReviewerAgent().review(
            coder_actions,
            static_project_state,
        )
        validation_report_output = record_validation_report(run_id, static_review)

        add_event(
            run_id,
            "static_review_completed",
            "static_reviewer",
            "Static review completed.",
            validation_report_output,
        )

        if not static_review.approved:
            static_review_output = validation_report_output
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
                project_data["workspace_path"],
                coder_output,
                static_failure,
                {
                    "trigger_stage": "static_review_failed",
                    "static_review_output": static_review_output,
                    "validation_report": static_review_output,
                    "rejected_actions": coder_output,
                    "project_state": static_project_state.to_dict(),
                },
            )

            sanitized_fix = sanitize_fix_output_or_fail(
                run_id,
                fix_result["output"],
                project_data["workspace_path"],
                coder_output,
                static_failure,
                trigger_stage="static_review_failed",
                static_review_output=static_review_output,
                validation_report=static_review_output,
                rejected_actions=coder_output,
            )
            if sanitized_fix is None:
                maybe_record_engineering_shadow()
                return
            actions, coder_output = sanitized_fix

            static_project_state = ProjectStateBuilder().build(
                run_id=run_id,
                project_id=project_id,
                workspace_path=project_data["workspace_path"],
                executor_actions=actions,
                project_specification=project_specification,
            )
            add_event(
                run_id,
                "validation_started",
                "static_reviewer",
                "Structured validation started after static review fix.",
            )
            static_review = StaticReviewerAgent().review(actions, static_project_state)
            validation_report_output = record_validation_report(
                run_id,
                static_review,
                event_type="validation_completed_after_fix",
            )

            add_event(
                run_id,
                "static_review_completed_after_fix",
                "static_reviewer",
                "Static review completed after static review fix.",
                validation_report_output,
            )

            if not static_review.approved:
                after_fix_output = validation_report_output
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
            project_data["workspace_path"],
            coder_output,
        )

        tester_result = run_tester_stage(
            run_id,
            project_data["workspace_path"],
        )
        save_stage_output(
            run_id,
            "tester_output_before_fix",
            str(tester_result.to_dict()),
        )

        if tester_result.success:
            readiness_ok, _ = run_runtime_readiness_stage(run_id, project_data["workspace_path"])
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
            project_data["workspace_path"],
            coder_output,
            tester_result,
        )

        sanitized_fix = sanitize_fix_output_or_fail(
            run_id,
            fix_result["output"],
            project_data["workspace_path"],
            coder_output,
            tester_result,
        )
        if sanitized_fix is None:
            maybe_record_engineering_shadow()
            return
        actions, coder_output = sanitized_fix

        fix_project_state = ProjectStateBuilder().build(
            run_id=run_id,
            project_id=project_id,
            workspace_path=project_data["workspace_path"],
            executor_actions=actions,
            project_specification=project_specification,
        )
        add_event(
            run_id,
            "validation_started",
            "static_reviewer",
            "Structured validation started after tester fix.",
        )
        static_review = StaticReviewerAgent().review(actions, fix_project_state)
        validation_report_output = record_validation_report(
            run_id,
            static_review,
            event_type="validation_completed_after_fix",
        )

        add_event(
            run_id,
            "static_review_completed_after_fix",
            "static_reviewer",
            "Static review completed after tester fix.",
            validation_report_output,
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
            project_data["workspace_path"],
            coder_output,
        )

        tester_result = run_tester_stage(
            run_id,
            project_data["workspace_path"],
        )
        save_stage_output(
            run_id,
            "tester_output_after_fix",
            str(tester_result.to_dict()),
        )

        if tester_result.success:
            readiness_ok, _ = run_runtime_readiness_stage(run_id, project_data["workspace_path"])
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
