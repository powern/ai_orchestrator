import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from studio.contracts.handoff import load_handoff_history, load_latest_handoff
from studio.core.workspace_observer import WorkspaceObserver
from studio.services.engineering_service import get_latest_engineering_assessment
from studio.services.event_service import list_events
from studio.services.project_service import get_project
from studio.services.run_service import get_run


@dataclass
class AgentContext:
    task: dict[str, Any]
    project: dict[str, Any]
    pipeline: dict[str, Any]
    evidence: dict[str, Any]
    validation_evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "project": self.project,
            "pipeline": self.pipeline,
            "evidence": self.evidence,
            "validation_evidence": self.validation_evidence,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_prompt_json(self) -> str:
        payload = deepcopy(self.to_dict())
        workspace_state = payload.get("project", {}).get("workspace_state", {})
        ignored_summary = workspace_state.get("ignored_files_summary")
        if isinstance(ignored_summary, dict):
            ignored_summary["examples"] = []
        return json.dumps(payload, ensure_ascii=False, indent=2)


def build_agent_context(
    run_id: int,
    current_stage: str,
    workspace_path: str | None = None,
    previous_stage_outputs: dict[str, Any] | None = None,
    evidence_overrides: dict[str, Any] | None = None,
) -> AgentContext:
    run_row = get_run(run_id)
    run = dict(run_row) if run_row is not None else {}
    project_id = run.get("project_id")
    project = _project(project_id)
    resolved_workspace = workspace_path or project.get("workspace_path") or ""
    workspace_state = _workspace_state(resolved_workspace)
    project_graph = workspace_state.get("project_graph", {})
    engineering_assessment = get_latest_engineering_assessment(run_id) if run else None

    task = {
        "original_user_request": project.get("description", ""),
        "non_negotiable_requirements": _extract_requirement_lines(project.get("description", "")),
        "acceptance_criteria": _extract_acceptance_criteria(project.get("description", "")),
    }
    outputs = {
        "planner_output": run.get("planner_output"),
        "architect_output": run.get("architect_output"),
        "coder_output": run.get("coder_output"),
        "fix_output": run.get("fix_output"),
    }
    outputs.update(previous_stage_outputs or {})

    evidence = {
        "static_review": _json_or_text(run.get("executor_output")),
        "tester": {
            "tester_output": run.get("tester_output"),
            "tester_output_before_fix": run.get("tester_output_before_fix"),
            "tester_output_after_fix": run.get("tester_output_after_fix"),
        },
        "runtime_readiness": _json_or_text(run.get("runtime_readiness")),
        "failure_analysis": _json_or_text(run.get("failure_analysis")),
        "repair_plan": _json_or_text(run.get("repair_plan")),
        "engineering_assessment": engineering_assessment or {},
    }
    evidence.update(evidence_overrides or {})

    return AgentContext(
        task=task,
        project={
            "project_id": project_id,
            "run_id": run_id,
            "workspace_path": resolved_workspace,
            "project_graph": project_graph,
            "workspace_state": workspace_state,
        },
        pipeline={
            "current_stage": current_stage,
            "previous_stage_outputs": outputs,
            "events": [dict(row) for row in list_events(run_id)] if run else [],
            "latest_handoff": load_latest_handoff(run_id) if run else None,
            "handoff_history": load_handoff_history(run_id) if run else [],
        },
        evidence=evidence,
        validation_evidence=evidence,
    )


def _project(project_id: int | None) -> dict[str, Any]:
    if project_id is None:
        return {}
    row = get_project(project_id)
    return dict(row) if row is not None else {}


def _workspace_state(workspace_path: str) -> dict[str, Any]:
    if not workspace_path:
        return {}
    return WorkspaceObserver().observe(workspace_path)


def _json_or_text(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {"text": value}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _extract_requirement_lines(description: str) -> list[str]:
    return [
        line.strip("-* ")
        for line in (description or "").splitlines()
        if line.strip().startswith(("-", "*"))
    ]


def _extract_acceptance_criteria(description: str) -> list[str]:
    markers = ("must", "should", "all tests", "pass", "raise", "return")
    return [
        line.strip("-* ")
        for line in (description or "").splitlines()
        if any(marker in line.lower() for marker in markers)
    ]
