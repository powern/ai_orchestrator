import json
from studio.core.llm_adapter import LLMAdapter
from studio.coder.pipeline import CoderPipeline
from studio.sanitizer.agent import ActionSanitizerAgent
from studio.core.tester_result import StageTestResult
from studio.services.event_service import add_event
from studio.services.run_service import save_stage_output, update_run_status, get_stage_output


def run_architect_placeholder(run_id, planner_output):
    update_run_status(run_id, "running", "architect")

    add_event(
        run_id,
        "architect_started",
        "architect",
        "Architect placeholder started.",
    )

    architect_output = (
        "ARCHITECT PLACEHOLDER\n\n"
        "Input from planner:\n"
        f"{planner_output}"
    )

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
    coder_output = adapter.ask(
        model=DEFAULT_MODELS["coder"],
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        json_mode=True,
    )

    def retry_fn(original_output, error):
        add_event(
            run_id,
            "coder_retry_started",
            "coder",
            f"Coder retry started after validation error: {error}",
            original_output,
        )

        retry_output = adapter.ask_retry(
            model=DEFAULT_MODELS["coder"],
            original_output=original_output,
            error=error,
        )

        add_event(
            run_id,
            "coder_retry_completed",
            "coder",
            "Coder retry completed.",
            retry_output,
        )

        return retry_output

    sanitizer = ActionSanitizerAgent(
        adapter=adapter,
        model=DEFAULT_MODELS["coder"],
    )

    sanitized_output = sanitizer.sanitize(coder_output)

    add_event(
        run_id,
        "coder_sanitized",
        "coder",
        "Coder output sanitized to Executor JSON.",
        sanitized_output,
    )

    pipeline_result = sanitizer.process(
        coder_output,
        max_attempts=2,
    )

    normalized_output = json.dumps(
        pipeline_result.program.to_dicts(),
        ensure_ascii=False,
        indent=2,
    )

    save_stage_output(run_id, "coder_output", normalized_output)

    add_event(
        run_id,
        "coder_completed",
        "coder",
        f"LLM Coder completed. Attempts: {pipeline_result.attempts}, retried: {pipeline_result.retried}.",
        normalized_output,
    )

    return normalized_output


def run_executor_stage(run_id, workspace_path, coder_output):
    from studio.executor.actions import execute_actions
    from studio.core.json_utils import normalize_coder_json

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
            from studio.core.fix_prompt import FixPromptBuilder

            bug_report = BugReportBuilder().build(tester_result)
            save_stage_output(run_id, "bug_report", bug_report)

            coder_output = get_stage_output(run_id, "coder_output") or ""

            fix_prompt = FixPromptBuilder().build(
                original_coder_output=coder_output,
                tester_result=tester_result,
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



def run_fix_stage(run_id, workspace_path, coder_output, tester_result):
    from studio.config.settings import DEFAULT_MODELS
    from studio.core.fix_prompt import FixPromptBuilder
    from studio.executor.actions import execute_actions
    from studio.core.json_utils import normalize_coder_json

    update_run_status(run_id, "running", "fix")

    add_event(
        run_id,
        "fix_started",
        "fix",
        "Fix stage started after tester failure.",
    )

    adapter = LLMAdapter()

    fix_prompt = FixPromptBuilder().build(
        original_coder_output=coder_output,
        tester_result=tester_result,
    )

    fix_output = adapter.ask(
        model=DEFAULT_MODELS["coder"],
        system_prompt="You fix generated projects by returning Executor JSON only.",
        user_prompt=fix_prompt,
        json_mode=True,
    )

    add_event(
        run_id,
        "fix_generated",
        "fix",
        "Fix actions generated.",
        fix_output,
    )

    actions = normalize_coder_json(fix_output)
    results = execute_actions(workspace_path, actions)

    result_text = str(results)

    add_event(
        run_id,
        "fix_completed",
        "fix",
        "Fix actions executed.",
        result_text,
    )

    return {
        "output": fix_output,
        "results": results,
    }


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
