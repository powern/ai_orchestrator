# AI Orchestrator Technical Audit

Audit date: 2026-06-27

## Executive Summary

The project has a useful MVP shape for an AI software development orchestrator,
with clear stage names and a growing test suite. The main production risks were
not algorithmic complexity; they were contract drift between modules, execution
safety gaps, event-system fragmentation, and generated artifacts living beside
source code.

Current scores after this audit:

- Overall quality: 72/100
- Architecture: 70/100
- Maintainability: 73/100
- Reliability: 76/100
- Security: 74/100
- Test quality: 78/100
- Production readiness: 66/100

Test status: 110 passing tests.

## Critical Issues

- Fix actions were executed before sanitizer/static review, then potentially
  executed again by `RunPipeline`. This allowed unreviewed LLM output to mutate
  workspaces and created duplicate side effects. Fixed.
- Executor path containment used string-prefix checks, which can be bypassed by
  sibling paths with shared prefixes. Fixed with resolved `Path.parents` checks.
- Command allowlisting accepted broad `python -m ...` execution. Restricted to
  pytest-only commands.
- The checked-out repository could not run tests cleanly on Windows because
  legacy imports and `/tmp` database handling were broken. Fixed.

## Major Issues

- Event persistence and runtime projection were split between ad hoc direct
  handler calls and a mostly unused `EventBus`. Event writes now publish a
  rehydrated `RunEvent` through the global bus and support replay.
- Executor AST existed but execution still operated primarily on dictionaries.
  Execution now normalizes to `ExecutorProgram`/`ExecutorAction` internally.
- Sanitizer flow performed duplicate LLM sanitation calls in the coder stage.
  Removed the duplicate call while preserving audit events.
- Runtime/generated workspaces and Python caches were not ignored. Added
  repository hygiene rules.
- Missing compatibility modules (`agents.*`, `core.ollama_client`) broke current
  tests and older integration expectations. Restored as thin facades.

## Minor Issues

- There is no root README or packaging metadata.
- Several functions remain dynamically typed and would benefit from stricter
  type annotations.
- `studio/workspaces` still contains previously committed generated examples.
- SQLite migrations are simple and lack versioning.
- Static review is rule-based and intentionally conservative, but it still mixes
  policy scoring with validation.
- LLM prompt contracts are duplicated across coder, sanitizer, and repair agent.

## Improvements Implemented

- Added legacy-compatible `agents` facades for Planner, Architect, Coder, and
  Tester agent model defaults.
- Added `core.ollama_client.OllamaClient` with Ollama API support and safe
  offline model-list fallback for tests.
- Strengthened `ExecutorProgram` and `ExecutorAction` conversion, metadata
  preservation, and iterable behavior.
- Updated executor execution to operate through `ExecutorProgram`.
- Hardened workspace/path safety against absolute paths and sibling-prefix
  escapes.
- Restricted executor command allowlist to pytest command forms.
- Added event IDs to `RunEvent` and runtime projection updates.
- Routed persisted events through `global_event_bus`.
- Added `replay_events()` and row-to-event rehydration.
- Removed duplicate sanitizer invocation in coder stage.
- Changed fix stage to generate fix actions only; execution now happens only
  after sanitizer and static review in the pipeline.
- Made SQLite test database path handling portable on Windows.
- Improved test isolation for mapped `/tmp` database paths.
- Added executor action documentation.
- Added tests for event replay, path-prefix escapes, absolute paths, and command
  allowlist tightening.
- Added `.gitignore` entries for local environments, DBs, caches, and runtime
  workspaces.

## Remaining Technical Debt

Priority 1:

- Move committed generated workspaces out of source control.
- Split stage orchestration from persistence side effects so pipeline behavior
  can be tested without SQLite.
- Introduce a single canonical Executor contract module shared by sanitizer,
  reviewer, executor, and docs.

Priority 2:

- Replace ad hoc migrations with ordered schema versions.
- Add structured event payload serialization instead of free-form strings.
- Add typed repository interfaces for runs, projects, runtime, and events.
- Add integration tests for full queued run processing with mocked LLM output.

Priority 3:

- Add root README, package metadata, and developer setup instructions.
- Add linting/type-checking in CI.
- Extract provider abstractions for Ollama/OpenAI/Claude/Gemini/DeepSeek.

## Future Recommendations

- Define stable ports/interfaces for Planner, Architect, Coder, Reviewer,
  Executor, Tester, and Fix Agent. This will make Aider, OpenHands, Claude Code,
  GPT-5, DeepSeek, Gemini, Git, PR, Docker, and Kubernetes backends pluggable.
- Promote `ExecutorProgram` to the only internal representation after LLM
  normalization. Dictionaries should be limited to API/DB serialization edges.
- Turn the event system into an explicit event store plus projection model:
  append-only persistence, replay, idempotent projections, and last-event
  checkpoints.
- Introduce workspace lifecycle management: create, mark active, archive,
  cleanup, and never commit generated runtime outputs.
- Add policy objects for command execution and filesystem access so different
  backends can enforce different sandbox profiles.
