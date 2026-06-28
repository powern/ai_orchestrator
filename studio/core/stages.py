import json

from studio.config.settings import CODER_MAX_OUTPUT_RETRIES, CODER_MAX_SANITIZE_ATTEMPTS
from studio.core.executor_schema import validate_executor_actions
from studio.core.llm_adapter import LLMAdapter
from studio.core.tester_result import StageTestResult
from studio.events.publisher import publish_run_event
from studio.sanitizer.agent import ActionSanitizerAgent
from studio.services.run_service import get_stage_output, save_stage_output, update_run_status


def add_event(run_id, event_type, stage=None, message="", payload=None):
    return publish_run_event(
        run_id=run_id,
        event_type=event_type,
        stage=stage,
        message=message,
        payload=payload,
    )


def run_architect_placeholder(run_id, planner_output):
    update_run_status(run_id, "running", "architect")

    add_event(
        run_id,
        "architect_started",
        "architect",
        "Architect placeholder started.",
    )

    architect_output = f"ARCHITECT PLACEHOLDER\n\nInput from planner:\n{planner_output}"

    save_stage_output(run_id, "architect_output", architect_output)

    add_event(
        run_id,
        "architect_completed",
        "architect",
        "Architect placeholder completed.",
        architect_output,
    )

    return architect_output


def run_coder_placeholder(run_id, planner_output, architect_output):
    from studio.config.settings import DEFAULT_MODELS

    update_run_status(run_id, "running", "coder")

    add_event(
        run_id,
        "coder_started",
        "coder",
        "LLM Coder started.",
    )

    system_prompt = """
You are the Coder Agent of AI Studio.

You must generate ONLY valid JSON.
Do not use markdown.
Do not explain anything.
Do not add comments.

The JSON root must be an array of executor actions.

Supported actions:
- mkdir
- write_file
- read_file
- run

Safety rules:
- All paths must be relative.
- Do not use absolute paths.
- Do not use path traversal.
- Do not modify AI Studio directly.
- Generate files only for the target project workspace.

Prefer creating a minimal working Python project with tests.
"""

    user_prompt = f"""
Planner output:

{planner_output}

Architect output:

{architect_output}

Generate executor actions now.
"""

    adapter = LLMAdapter()
    coder_raw_output = adapter.ask(
        model=DEFAULT_MODELS["coder"],
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        json_mode=True,
    )
    save_stage_output(run_id, "coder_raw_output", coder_raw_output)

    sanitizer = ActionSanitizerAgent(
        adapter=adapter,
        model=DEFAULT_MODELS["coder"],
    )

    current_raw_output = coder_raw_output
    last_error = None
    invalid_sanitized_actions = None

    for retry_number in range(0, CODER_MAX_OUTPUT_RETRIES + 1):
        invalid_sanitized_actions = None
        try:
            pipeline_result = sanitizer.process(
                current_raw_output,
                max_attempts=CODER_MAX_SANITIZE_ATTEMPTS,
            )
            validate_executor_actions(pipeline_result.actions)
            break
        except Exception as exc:
            last_error = exc
            invalid_sanitized_actions = getattr(exc, "invalid_actions", None)
            save_stage_output(run_id, "coder_sanitizer_error", str(exc))

            if retry_number >= CODER_MAX_OUTPUT_RETRIES:
                update_run_status(
                    run_id,
                    "failed",
                    "coder_failed",
                    f"Coder output could not be sanitized: {exc}",
                )

                add_event(
                    run_id,
                    "coder_failed",
                    "coder_failed",
                    "Coder output could not be sanitized after retries.",
                    str(exc),
                )

                add_event(
                    run_id,
                    "run_failed",
                    "coder_failed",
                    "Run failed because coder output was invalid after retries.",
                    str(exc),
                )

                return None

            add_event(
                run_id,
                "coder_retry",
                "coder",
                f"Coder retry #{retry_number + 1} after sanitizer error.",
                str(exc),
            )

            current_raw_output = ask_coder_retry(
                adapter=adapter,
                model=DEFAULT_MODELS["coder"],
                previous_raw_output=current_raw_output,
                error=exc,
                invalid_sanitized_actions=invalid_sanitized_actions,
            )
    else:
        raise last_error

    normalized_output = json.dumps(
        pipeline_result.program.to_dicts(),
        ensure_ascii=False,
        indent=2,
    )

    save_stage_output(run_id, "coder_output", normalized_output)

    add_event(
        run_id,
        "coder_sanitized",
        "coder",
        "Coder output sanitized to Executor JSON.",
        normalized_output,
    )

    add_event(
        run_id,
        "coder_completed",
        "coder",
        (
            "LLM Coder completed. "
            f"Attempts: {pipeline_result.attempts}, retried: {pipeline_result.retried}."
        ),
        normalized_output,
    )

    return normalized_output


def ask_coder_retry(
    adapter,
    model,
    previous_raw_output: str,
    error: Exception,
    invalid_sanitized_actions=None,
) -> str:
    invalid_actions_text = (
        json.dumps(invalid_sanitized_actions, ensure_ascii=False, indent=2)
        if invalid_sanitized_actions is not None
        else "not available"
    )
    system_prompt = """
You are the Coder Agent of AI Studio.

Return ONLY valid Executor JSON.
Do not use markdown.
Do not explain anything.
"""

    user_prompt = f"""
Your previous response could not be parsed.
It may also have failed Executor Action Schema validation.

Return ONLY Executor JSON.
Do not use markdown.
Do not explain.

Strict Executor JSON contract:
- Root must be a JSON array.
- Every item must be an object.
- mkdir requires string fields: action, path.
- write_file requires string fields: action, path, content.
- read_file requires string fields: action, path.
- run requires string fields: action, command.
- Paths must be relative and must not contain traversal.
- Do not put objects or arrays inside path, content, or command.

Previous parser error:
{error}

Invalid sanitized actions:
{invalid_actions_text}

Previous raw response:
{previous_raw_output}
"""

    return adapter.ask(
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        json_mode=True,
    )


def run_executor_stage(run_id, workspace_path, coder_output):
    from studio.core.json_utils import normalize_coder_json
    from studio.executor.actions import execute_actions

    update_run_status(run_id, "running", "executor")

    add_event(
        run_id,
        "executor_started",
        "executor",
        "Executor stage started.",
    )

    actions = normalize_coder_json(coder_output)
    results = execute_actions(workspace_path, actions)
    result_text = str(results)

    save_stage_output(run_id, "executor_output", result_text)
    save_stage_output(run_id, "result", result_text)

    add_event(
        run_id,
        "executor_completed",
        "executor",
        "Executor stage completed.",
        result_text,
    )

    return results


def run_tester_stage(run_id, workspace_path):
    from studio.executor.actions import action_run

    update_run_status(run_id, "running", "tester")

    add_event(
        run_id,
        "tester_started",
        "tester",
        "Tester stage started.",
    )

    result = action_run(
        workspace_path,
        "pytest -q",
        timeout=120,
    )

    tester_result = StageTestResult.from_executor_result(result)

    if not tester_result.success:
        try:
            from studio.core.bug_report import BugReportBuilder
            from studio.core.failure_analysis import FailureAnalyzer
            from studio.core.fix_prompt import FixPromptBuilder, FixWorkspaceContextBuilder
            from studio.core.repair_plan import RepairPlanner

            bug_report = BugReportBuilder().build(tester_result)
            save_stage_output(run_id, "bug_report", bug_report)
            analysis = FailureAnalyzer().analyze(workspace_path, tester_result, bug_report)
            repair_plan = RepairPlanner().plan(analysis)
            repair_plan_json = repair_plan.to_json()
            save_stage_output(
                run_id,
                "failure_analysis",
                json.dumps(analysis.to_dict(), ensure_ascii=False, indent=2),
            )
            save_stage_output(run_id, "repair_plan", repair_plan_json)
            add_event(
                run_id,
                "failure_analyzed",
                "failure_analyzer",
                "Failure Analyzer identified probable root cause.",
                json.dumps(analysis.to_dict(), ensure_ascii=False, indent=2),
            )
            add_event(
                run_id,
                "repair_planned",
                "repair_planner",
                "Repair Planner generated structured repair instructions.",
                repair_plan_json,
            )

            coder_output = get_stage_output(run_id, "coder_output") or ""
            executor_output = get_stage_output(run_id, "executor_output") or ""
            context_builder = FixWorkspaceContextBuilder()

            fix_prompt = FixPromptBuilder().build(
                original_coder_output=coder_output,
                tester_result=tester_result,
                task_description=get_task_description_for_run(run_id),
                workspace_files=context_builder.build(workspace_path, tester_result),
                workspace_tree=context_builder.build_tree(workspace_path),
                bug_report=bug_report,
                executor_output=executor_output,
                repair_plan=repair_plan_json,
            )

            save_stage_output(run_id, "result", fix_prompt)

        except Exception:
            pass

    result_text = str(result)

    save_stage_output(run_id, "tester_output", result_text)

    if tester_result.success:
        add_event(
            run_id,
            "tester_completed",
            "tester",
            "Tester stage completed successfully.",
            result_text,
        )
    else:
        add_event(
            run_id,
            "tester_failed",
            "tester",
            "Tester stage failed.",
            result_text,
        )

    return tester_result


def run_fix_stage(
    run_id,
    workspace_path,
    coder_output,
    tester_result,
    previous_error=None,
    previous_raw_output=None,
    emit_started=True,
):
    from studio.config.settings import DEFAULT_MODELS
    from studio.core.failure_analysis import FailureAnalyzer
    from studio.core.fix_prompt import FixPromptBuilder, FixWorkspaceContextBuilder
    from studio.core.repair_plan import RepairPlanner

    update_run_status(run_id, "running", "fix")

    if emit_started:
        add_event(
            run_id,
            "fix_started",
            "fix",
            "Fix stage started after tester failure.",
        )

    adapter = LLMAdapter()
    task_description = get_task_description_for_run(run_id)
    bug_report = get_stage_output(run_id, "bug_report") or ""
    executor_output = get_stage_output(run_id, "executor_output") or ""
    analysis = FailureAnalyzer().analyze(workspace_path, tester_result, bug_report)
    repair_plan = RepairPlanner().plan(analysis)
    repair_plan_json = repair_plan.to_json()
    save_stage_output(
        run_id,
        "failure_analysis",
        json.dumps(analysis.to_dict(), ensure_ascii=False, indent=2),
    )
    save_stage_output(run_id, "repair_plan", repair_plan_json)
    context_builder = FixWorkspaceContextBuilder()
    workspace_files = context_builder.build(workspace_path, tester_result)

    fix_prompt = FixPromptBuilder().build(
        original_coder_output=coder_output,
        tester_result=tester_result,
        task_description=task_description,
        workspace_files=workspace_files,
        workspace_tree=context_builder.build_tree(workspace_path),
        bug_report=bug_report,
        executor_output=executor_output,
        repair_plan=repair_plan_json,
    )

    if previous_error is not None:
        fix_prompt = f"""
{fix_prompt}

Previous Fix Agent response could not be sanitized.

Return ONLY Executor JSON actions.
Do not use markdown.
Do not explain.

Previous sanitizer error:
{previous_error}

Previous raw Fix Agent response:
{previous_raw_output or ""}
""".strip()

    fix_output = adapter.ask(
        model=DEFAULT_MODELS["coder"],
        system_prompt="You fix generated projects by returning Executor JSON only.",
        user_prompt=fix_prompt,
        json_mode=True,
    )

    save_stage_output(run_id, "fix_raw_output", fix_output)

    add_event(
        run_id,
        "fix_generated",
        "fix",
        "Fix actions generated.",
        fix_output,
    )

    return {
        "output": fix_output,
        "results": None,
    }


def get_task_description_for_run(run_id):
    from studio.database.db import get_connection

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT projects.description
            FROM runs
            JOIN projects ON projects.id = runs.project_id
            WHERE runs.id = ?
            """,
            (run_id,),
        ).fetchone()

    if row is None:
        return None

    return row["description"]


def run_architect_stage(run_id, planner_output):
    from studio.config.settings import DEFAULT_MODELS

    update_run_status(run_id, "running", "architect")

    add_event(
        run_id,
        "architect_started",
        "architect",
        "LLM Architect started.",
    )

    system_prompt = """
You are the Architect Agent of AI Studio.

Return ONLY a concise implementation plan.

Maximum 20 lines.

Format exactly like this:

Files:
- app/__init__.py
- app/main.py
- tests/test_main.py

Functions:
- main()

Tests:
- unittest
- import from app.main

Constraints:
- relative paths only
- no absolute paths
- no markdown
- no explanations
- no code
"""

    user_prompt = f"""
Planner output:

{planner_output}

Create the implementation architecture now.
"""

    adapter = LLMAdapter()

    architect_output = adapter.ask(
        model=DEFAULT_MODELS["planner"],
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )

    save_stage_output(run_id, "architect_output", architect_output)

    add_event(
        run_id,
        "architect_completed",
        "architect",
        "LLM Architect completed.",
        architect_output,
    )

    return architect_output
