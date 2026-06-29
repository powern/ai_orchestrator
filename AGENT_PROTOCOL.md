# Agent Protocol

## Purpose

The Agent Protocol defines the shared communication contract for AI Orchestrator agents.
Agents may still receive legacy evidence, but new agent outputs must use canonical fields and
schemas. Compatibility normalization is allowed at boundaries; it is not permission for agents to
emit non-canonical output.

## Canonical Field Names

Use these names across prompts, context, persistence, and validation:

- `action`
- `path`
- `content`
- `command`
- `original_user_request`
- `non_negotiable_requirements`
- `acceptance_criteria`
- `project_graph`
- `workspace_state`
- `previous_stage_outputs`
- `validation_evidence`

## Forbidden Aliases

Agents must not output:

- `file_path`
- `filename`
- `cmd`
- `body`
- `add_content`
- mkdir shorthand, such as `{ "mkdir": "app" }`
- run shorthand, such as `{ "run": "pytest -q" }`
- write-file shorthand, such as `{ "write_file": { ... } }`

## AgentContext Structure

```json
{
  "task": {
    "original_user_request": "",
    "non_negotiable_requirements": [],
    "acceptance_criteria": []
  },
  "project": {
    "project_id": 0,
    "run_id": 0,
    "workspace_path": "",
    "project_graph": {},
    "workspace_state": {}
  },
  "pipeline": {
    "current_stage": "",
    "previous_stage_outputs": {},
    "events": []
  },
  "evidence": {
    "static_review": {},
    "tester": {},
    "runtime_readiness": {},
    "failure_analysis": {},
    "repair_plan": {},
    "engineering_assessment": {}
  }
}
```

## Executor Action Contract

The canonical Executor JSON root is an array. Allowed actions:

```json
{ "action": "mkdir", "path": "app" }
```

```json
{ "action": "write_file", "path": "app/main.py", "content": "..." }
```

```json
{ "action": "read_file", "path": "app/main.py" }
```

```json
{ "action": "run", "command": "pytest -q" }
```

## Required Context Per Agent

- Planner: original request and acceptance criteria.
- Architect: original request, planner output, constraints, project assumptions.
- Coder: original request, planner output, architect output, project graph if available.
- Sanitizer: raw agent output, canonical action contract, schema errors.
- Static Reviewer: canonical actions, original request, architecture, project graph if available.
- Tester: workspace path, test command, expected behavior.
- Failure Analyzer: tester output, workspace state, project graph, bug report.
- Repair Planner: failure analysis, affected files, project graph, original request.
- Fix Agent: original request, acceptance criteria, non-negotiable requirements, project graph,
  workspace state, static review findings, tester output, failure analysis, repair plan, rejected
  actions, previous outputs.
- Runtime Readiness: workspace state, project graph, dependency files, entrypoint hints.
- Engineering Assessment: workspace state, project graph, validation evidence.

## Output Contracts

- `PlannerOutput`: `goals`, `requirements`, `acceptance_criteria`, `risks`.
- `ArchitectOutput`: `files`, `modules`, `interfaces`, `test_strategy`, `runtime_entrypoint`.
- `CoderOutput`: canonical Executor JSON actions only.
- `SanitizerOutput`: `actions`, `repairs_applied`, `schema_warnings`.
- `StaticReviewOutput`: `approved`, `score`, `findings`, `rejected_actions`.
- `TesterOutput`: `success`, `returncode`, `stdout`, `stderr`.
- `FailureAnalysisOutput`: `root_cause`, `exception_type`, `affected_files`, `evidence`.
- `RepairPlanOutput`: `primary_targets`, `secondary_targets`, `reason`, `expected_validation`.
- `FixOutput`: canonical Executor JSON actions only.
- `RuntimeReadinessOutput`: runtime readiness report schema.
- `EngineeringAssessmentOutput`: `confidence`, `decision`, `workspace_summary`, `project_graph`.

## Protocol Violation Handling

Protocol checks start non-blocking. A stage should emit at most one summarized event:

- `agent_context_built`
- `agent_protocol_violation`
- `agent_context_missing_required_field`
- `agent_output_forbidden_alias`

Severe violations may become blocking only after the pipeline has enough compatibility telemetry.

## Normalizer Compatibility Policy

Normalizers may tolerate legacy or malformed input to preserve recoverability. Agents must still be
prompted to emit canonical protocol output. Tolerated input is not allowed output.

## Migration Strategy

1. Introduce `AgentContext` and validator in non-blocking mode.
2. Make Coder and Fix Agent protocol-aware.
3. Log summarized protocol violations.
4. Gradually convert Planner, Architect, Static Reviewer, Failure Analyzer, Repair Planner, Runtime
   Readiness, and Engineering Assessment to consume `AgentContext`.
5. Make selected protocol violations blocking only when tests and telemetry show it is safe.
