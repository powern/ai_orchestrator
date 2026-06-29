import json

from studio.config.settings import CODER_MAX_OUTPUT_RETRIES, CODER_MAX_SANITIZE_ATTEMPTS
from studio.contracts import (
    PROTOCOL_SUMMARY,
    ProtocolValidator,
    append_handoff,
    build_agent_context,
    build_handoff,
)
from studio.contracts.execution import infer_execution_contract
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


def record_protocol_context(run_id, stage, context):
    add_event(
        run_id,
        "agent_context_built",
        stage,
        f"AgentContext built for {stage}.",
    )
    violations = ProtocolValidator().validate_agent_context(context, stage)
    record_protocol_violations(run_id, stage, violations)


def record_protocol_output(run_id, stage, output):
    violations = ProtocolValidator().validate_agent_output(output, stage)
    record_protocol_violations(run_id, stage, violations)


def record_protocol_violations(run_id, stage, violations):
    if not violations:
        return
    event_type = (
        "agent_context_missing_required_field"
        if any(violation.code.startswith("missing_") for violation in violations)
        else "agent_output_forbidden_alias"
        if any(violation.code == "forbidden_alias" for violation in violations)
        else "agent_protocol_violation"
    )
    add_event(
        run_id,
        event_type,
        stage,
        f"Agent Protocol reported {len(violations)} violation(s).",
        json.dumps([violation.to_dict() for violation in violations], ensure_ascii=False),
    )


def record_agent_handoff(
    run_id,
    stage,
    producer,
    consumer,
    summary,
    agent_context=None,
    implementation_contract=None,
    known_risks=None,
    recommended_focus=None,
):
    context = agent_context or build_agent_context(run_id, stage)
    workspace_path = context.project.get("workspace_path") if hasattr(context, "project") else None
    handoff = build_handoff(
        producer=producer,
        consumer=consumer,
        summary=summary,
        agent_context=context,
        implementation_contract=implementation_contract,
        known_risks=known_risks,
        recommended_focus=recommended_focus,
    )
    return append_handoff(run_id, stage, handoff, workspace_path=workspace_path)


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
    agent_context = build_agent_context(
        run_id=run_id,
        current_stage="coder",
        previous_stage_outputs={
            "planner_output": planner_output,
            "architect_output": architect_output,
        },
    )
    record_protocol_context(run_id, "coder", agent_context)

    system_prompt = f"""
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

Agent Protocol:
{PROTOCOL_SUMMARY}

For simple Flask or visual smoke-test web apps:
- Make the app manually runnable with python app/main.py when app/main.py exists.
- Include if __name__ == "__main__": app.run(host="0.0.0.0", port=5000).
- If using redirect, url_for, or render_template_string, import them from flask.
- Expose a real Flask app object named app.
- Add tests for visible page text and user-visible state changes, not only HTTP 200.
- For counter apps, tests should verify title text, Counter: 0, Increase, Reset,
  increase changes the visible counter to 1, and reset changes it back to 0.
- Add RUN.md with install, run, and open-browser instructions for visual apps.
"""

    user_prompt = f"""
AgentContext:
{agent_context.to_prompt_json()}

Decision collaboration:
- Read latest_handoff and handoff_history before implementing.
- Preserve protected_decisions unless new validation evidence makes them invalid.
- Record implementation decisions, assumptions, and risks in the next handoff.

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
    try:
        record_protocol_output(run_id, "coder", json.loads(coder_raw_output))
    except json.JSONDecodeError:
        pass

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
    record_agent_handoff(
        run_id,
        "coder",
        "coder",
        "executor",
        "Implementation plan converted to canonical Executor actions.",
        agent_context=agent_context,
        implementation_contract={
            "output": "canonical_executor_actions",
            "action_source": "coder",
        },
        recommended_focus=["execute generated actions", "preserve original requirements"],
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
    system_prompt = f"""
You are the Coder Agent of AI Studio.

Return ONLY valid Executor JSON.
Do not use markdown.
Do not explain anything.

Agent Protocol:
{PROTOCOL_SUMMARY}
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
- Output MUST be valid JSON.
- Output MUST contain ONLY Executor JSON.
- No markdown.
- No ``` blocks.
- No Python literals.
- Do not use triple quoted strings.
- Every file content must be a normal JSON string.
- Escape newlines with \\n.
- Escape quotes inside strings with \\".
- Do not invent new action types.
- Supported actions are ONLY: mkdir, write_file, read_file, run.
- mkdir requires string fields: action, path.
- write_file requires string fields: action, path, content.
- read_file requires string fields: action, path.
- run requires string fields: action, command.
- Paths must be relative and must not contain traversal.
- Do not put objects or arrays inside path, content, or command.
- Replace unsupported actions such as install_packages with supported Executor actions.

BAD:
"content": \"\"\"
print("Hello")
\"\"\"

GOOD:
"content": "print(\\"Hello\\")\\nprint(\\"World\\")\\n"

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

    agent_context = build_agent_context(run_id, "tester", workspace_path=workspace_path)
    execution_contract = agent_context.project.get("execution_contract") or {}
    test_contract = execution_contract.get("test") or {}
    test_command = test_contract.get("command") or "pytest -q"
    test_working_directory = test_contract.get("working_directory") or "."

    result = action_run(
        workspace_path,
        test_command,
        timeout=120,
        working_directory=test_working_directory,
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
            analysis = FailureAnalyzer().analyze(
                workspace_path,
                tester_result,
                bug_report,
                execution_contract=execution_contract,
            )
            repair_plan = RepairPlanner().plan(analysis, execution_contract=execution_contract)
            repair_plan_json = repair_plan.to_json()
            save_stage_output(
                run_id,
                "failure_analysis",
                json.dumps(analysis.to_dict(), ensure_ascii=False, indent=2),
            )
            save_stage_output(run_id, "repair_plan", repair_plan_json)
            add_event(
                run_id,
                "diagnostic_case_built",
                "failure_analyzer",
                "Diagnostic case built from tester output and workspace evidence.",
                json.dumps(analysis.diagnostic_case, ensure_ascii=False, indent=2),
            )
            add_event(
                run_id,
                "hypotheses_generated",
                "failure_analyzer",
                f"Generated {len(analysis.hypotheses)} diagnostic hypothesis/hypotheses.",
                json.dumps(analysis.hypotheses, ensure_ascii=False, indent=2),
            )
            add_event(
                run_id,
                "verified_diagnosis_completed",
                "failure_analyzer",
                "Verified diagnosis selected from evidence-backed hypotheses.",
                json.dumps(analysis.verified_diagnosis, ensure_ascii=False, indent=2),
            )
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
            context = build_agent_context(
                run_id,
                "repair_planner",
                workspace_path=workspace_path,
                evidence_overrides={
                    "tester": tester_result.to_dict(),
                    "failure_analysis": analysis.to_dict(),
                    "repair_plan": repair_plan.to_dict(),
                },
            )
            record_agent_handoff(
                run_id,
                "failure_analyzer",
                "failure_analyzer",
                "repair_planner",
                "Failure Analyzer identified the most likely root cause.",
                agent_context=context,
                implementation_contract={"primary_target": analysis.primary_target},
                known_risks=["root cause may span multiple files"],
                recommended_focus=[analysis.primary_target or analysis.root_cause],
            )
            record_agent_handoff(
                run_id,
                "repair_planner",
                "repair_planner",
                "fix",
                "Repair Planner selected concrete repair targets.",
                agent_context=context,
                implementation_contract=repair_plan.to_dict(),
                recommended_focus=repair_plan.repair_targets + repair_plan.secondary_targets,
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
                project_execution_contract=json.dumps(
                    execution_contract,
                    ensure_ascii=False,
                    indent=2,
                ),
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
        record_agent_handoff(
            run_id,
            "tester",
            "tester",
            "runtime_readiness",
            "Tester verified the generated project behavior with pytest.",
            agent_context=build_agent_context(run_id, "tester", workspace_path=workspace_path),
            implementation_contract={
                "tests_passed": True,
                "project_execution_contract": execution_contract,
            },
            recommended_focus=["runtime readiness", "manual run metadata"],
        )
    else:
        add_event(
            run_id,
            "tester_failed",
            "tester",
            "Tester stage failed.",
            result_text,
        )
        record_agent_handoff(
            run_id,
            "tester",
            "tester",
            "failure_analyzer",
            "Tester observed failing validation that requires root cause analysis.",
            agent_context=build_agent_context(run_id, "tester", workspace_path=workspace_path),
            implementation_contract={
                "tests_passed": False,
                "project_execution_contract": execution_contract,
            },
            known_risks=["test failure needs root cause analysis"],
            recommended_focus=["traceback", "workspace files", "project graph"],
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
    trigger_stage="tester_failed",
    static_review_output=None,
    rejected_actions=None,
    project_state=None,
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
            f"Fix stage started after {trigger_stage}.",
        )

    adapter = LLMAdapter()
    task_description = get_task_description_for_run(run_id)
    bug_report = get_stage_output(run_id, "bug_report") or ""
    executor_output = get_stage_output(run_id, "executor_output") or ""
    coder_raw_output = get_stage_output(run_id, "coder_raw_output") or ""
    planner_output = get_stage_output(run_id, "planner_output") or ""
    architect_output = get_stage_output(run_id, "architect_output") or ""
    base_context = build_agent_context(
        run_id=run_id,
        current_stage="fix",
        workspace_path=workspace_path,
    )
    execution_contract = base_context.project.get("execution_contract") or infer_execution_contract(
        workspace_path=workspace_path,
    ).to_dict()
    analysis = FailureAnalyzer().analyze(
        workspace_path,
        tester_result,
        bug_report,
        execution_contract=execution_contract,
        project_state=project_state,
    )
    repair_plan = RepairPlanner().plan(analysis, execution_contract=execution_contract)
    repair_plan_json = repair_plan.to_json()
    save_stage_output(
        run_id,
        "failure_analysis",
        json.dumps(analysis.to_dict(), ensure_ascii=False, indent=2),
    )
    save_stage_output(run_id, "repair_plan", repair_plan_json)
    add_event(
        run_id,
        "diagnostic_case_built",
        "failure_analyzer",
        "Diagnostic case built from validation evidence.",
        json.dumps(analysis.diagnostic_case, ensure_ascii=False, indent=2),
    )
    add_event(
        run_id,
        "hypotheses_generated",
        "failure_analyzer",
        f"Generated {len(analysis.hypotheses)} diagnostic hypothesis/hypotheses.",
        json.dumps(analysis.hypotheses, ensure_ascii=False, indent=2),
    )
    add_event(
        run_id,
        "verified_diagnosis_completed",
        "failure_analyzer",
        "Verified diagnosis selected from evidence-backed hypotheses.",
        json.dumps(analysis.verified_diagnosis, ensure_ascii=False, indent=2),
    )
    context_builder = FixWorkspaceContextBuilder()
    workspace_files = context_builder.build(workspace_path, tester_result)
    agent_context = build_agent_context(
        run_id=run_id,
        current_stage="fix",
        workspace_path=workspace_path,
        previous_stage_outputs={
            "planner_output": planner_output,
            "architect_output": architect_output,
            "coder_output": coder_output,
            "fix_output": get_stage_output(run_id, "fix_output"),
        },
        evidence_overrides={
            "tester": tester_result.to_dict(),
            "failure_analysis": analysis.to_dict(),
            "repair_plan": repair_plan.to_dict(),
            "project_execution_contract": execution_contract,
            "static_review": static_review_output or {},
        },
    )
    record_protocol_context(run_id, "fix", agent_context)

    fix_prompt = FixPromptBuilder().build(
        original_coder_output=coder_output,
        tester_result=tester_result,
        task_description=task_description,
        workspace_files=workspace_files,
        workspace_tree=context_builder.build_tree(workspace_path),
        bug_report=bug_report,
        executor_output=executor_output,
        repair_plan=repair_plan_json,
        trigger_stage=trigger_stage,
        static_review_output=static_review_output,
        rejected_actions=rejected_actions,
        coder_raw_output=coder_raw_output,
        planner_output=planner_output,
        architect_output=architect_output,
        agent_context_json=agent_context.to_prompt_json(),
        protocol_summary=PROTOCOL_SUMMARY,
        project_execution_contract=json.dumps(execution_contract, ensure_ascii=False, indent=2),
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
    try:
        record_protocol_output(run_id, "fix", json.loads(fix_output))
    except json.JSONDecodeError:
        pass

    add_event(
        run_id,
        "fix_generated",
        "fix",
        "Fix actions generated.",
        fix_output,
    )
    record_agent_handoff(
        run_id,
        "fix",
        "fix",
        "static_reviewer",
        "Fix Agent generated repair actions for the planned targets.",
        agent_context=agent_context,
        implementation_contract={
            "output": "canonical_executor_actions",
            "trigger_stage": trigger_stage,
            "project_execution_contract": execution_contract,
        },
        recommended_focus=["review fix actions", "run repaired tests"],
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
    agent_context = build_agent_context(
        run_id,
        "architect",
        previous_stage_outputs={"planner_output": planner_output},
    )
    record_protocol_context(run_id, "architect", agent_context)

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
- for Flask visual apps, app/main.py must be runnable with python app/main.py
- for Flask visual apps, include RUN.md and visible behavior tests
- define a Project Execution Contract with language, project_root, source_roots, test_roots,
  build/run/test commands, module strategy, and expected artifacts
- keep the contract language-agnostic; language-specific details belong under module strategy
"""

    user_prompt = f"""
AgentContext:
{agent_context.to_prompt_json()}

Latest Decision Handoff:
{json.dumps(agent_context.pipeline.get("latest_handoff"), ensure_ascii=False, indent=2)}

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
    record_agent_handoff(
        run_id,
        "architect",
        "architect",
        "coder",
        "Architect selected project structure and implementation boundaries.",
        agent_context=agent_context,
        implementation_contract={"architecture": "files, functions, tests, constraints"},
        recommended_focus=["follow file layout", "preserve package assumptions"],
    )

    return architect_output
