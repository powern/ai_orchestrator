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
- `project_specification`
- `project_graph`
- `project_state`
- `project_execution_contract`
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
    "acceptance_criteria": [],
    "project_specification": {}
  },
  "project": {
    "project_id": 0,
    "run_id": 0,
    "workspace_path": "",
    "project_state": {},
    "project_state_summary": {},
    "project_specification": {},
    "project_graph": {},
    "project_execution_contract": {},
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

## Decision Handoff

Agent handoffs are decision records, not implementation logs. Source code belongs in workspace
files and Executor actions. Handoffs should capture:

- decisions made by the producing agent;
- why those decisions were made;
- assumptions that remain active;
- protected decisions the next agent should preserve;
- risks and open questions;
- expected next agent and validation.

Large code blocks, file contents, and raw Executor JSON should be summarized before persistence.
The latest handoff is primary, while the full handoff history remains available as collective
engineering memory.

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

## Project Execution Contract

Every generated project should have a language-agnostic execution contract describing how it is
built, run, tested, imported or linked, and validated. The contract is the shared source of truth
for Architect, Coder, Tester, Runtime Readiness, Failure Analyzer, Repair Planner, Fix Agent, and
Decision Records.

Required top-level fields:

- `language`
- `project_root`
- `source_roots`
- `test_roots`
- `build`
- `run`
- `test`
- `module_strategy`
- `artifacts`

Language-specific details belong under `module_strategy`, such as `python_imports`,
`dotnet_namespace`, `cpp_include`, `node_module`, `go_module`, or `java_package`.

## Project Specification

`project_specification` is the structured intent extracted from the original user request before
Planner, Architect, and Coder operate. It is not source code. It captures project type, language,
framework, runtime expectations, required features, entities, expected files/tests, acceptance
criteria, constraints, confidence, and source evidence.

Agents should treat Project Specification as the source of truth for intent. Do not contradict it
unless validation evidence proves it wrong; when confidence is low, stay conservative and preserve
the original request.

## Unified Project State

`project_state` is the shared evidence snapshot for stages. It distinguishes materialized
workspace files from planned Executor actions and exposes merged virtual files for pre-execution
analysis. Major components should consume `project_state` when available instead of rebuilding
their own project view.

Required summary fields:

- actual file count;
- planned file count;
- merged file count;
- graph source;
- contract source;
- detected project types;
- entrypoints, routes, source roots, and test roots.

## Required Context Per Agent

- Planner: original request, acceptance criteria, and project specification.
- Architect: original request, planner output, project specification, constraints, project assumptions, execution contract.
- Coder: original request, planner output, architect output, project specification, execution contract, project graph if available.
- Sanitizer: raw agent output, canonical action contract, schema errors.
- Static Reviewer: canonical actions, original request, architecture, project_state if available.
- Tester: workspace path, execution contract test command, expected behavior.
- Failure Analyzer: tester output, workspace state, project graph, execution contract, bug report.
- Repair Planner: failure analysis, affected files, execution contract, project graph, original request.
- Fix Agent: original request, acceptance criteria, non-negotiable requirements, project graph,
  execution contract, workspace state, static review findings, tester output, failure analysis,
  repair plan, rejected actions, previous outputs.
- Runtime Readiness: workspace state, project graph, execution contract, dependency files,
  entrypoint hints.
- Engineering Assessment: workspace state, project graph, validation evidence.

## Output Contracts

- `PlannerOutput`: `goals`, `requirements`, `acceptance_criteria`, `risks`.
- `ArchitectOutput`: `files`, `modules`, `interfaces`, `test_strategy`, `project_execution_contract`.
- `CoderOutput`: canonical Executor JSON actions only.
- `SanitizerOutput`: `actions`, `repairs_applied`, `schema_warnings`.
- `StaticReviewOutput`: `approved`, `score`, `findings`, `rejected_actions`.
- `TesterOutput`: `success`, `returncode`, `stdout`, `stderr`.
- `FailureAnalysisOutput`: `root_cause`, `exception_type`, `failure_class`, `affected_files`,
  `project_execution_contract`, `evidence`.
- `RepairPlanOutput`: `primary_targets`, `secondary_targets`, `reason`,
  `project_execution_contract`, `expected_validation`.
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
