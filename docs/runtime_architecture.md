# Runtime Architecture

## Run Lifecycle

Projects may have at most one active run at a time. Active statuses are:

- `queued`
- `running`

Production code should create runs through:

```python
create_run_if_not_active(project_id)
```

If a queued or running run already exists, the existing run ID is returned and
no duplicate run row is inserted. The Flask route
`POST /projects/<project_id>/run` redirects to the existing active run.

## Event Publication Path

The public production event entry point is:

```python
publish_run_event(...)
```

The path is:

```text
publish_run_event
  -> event_service.add_event
      -> insert one run_events row
      -> publish persisted RunEvent to global_event_bus
          -> RuntimeHandler updates project_runtime
```

`event_service.add_event()` is an internal persistence/projection helper. Event
handlers must not call it; that would create recursive writes.

`project_runtime.last_event_id` is set to the persisted `run_events.id` used to
drive the projection.

## Runtime Projection Replay

If `project_runtime` becomes stale, rebuild it from persisted events:

```python
rebuild_runtime_projection(project_id)
```

The function deletes the existing runtime projection for the project, reads all
events for all runs in persisted event order, reapplies the runtime projection,
and returns the final runtime row.

## Project Status Compatibility

`projects.status` is retained for compatibility and is updated by scheduler
finalization through `update_project_status(project_id)`. The richer live state
is `project_runtime`.

Longer term, project status should either be derived from runtime or deprecated
as a separately stored lifecycle field.

## Executor Actions

External LLM output remains JSON-compatible, but internal execution should move
toward `ExecutorProgram` and `ExecutorAction` as the canonical action model.

Executor command execution is intentionally narrow. Supported command families:

- `pytest ...`
- `python -m pytest ...`
- `python3 -m pytest ...`
- `python -m unittest ...`
- `python3 -m unittest ...`

Python module commands are normalized to the current interpreter to avoid
environment-specific `python: not found` failures.

## Local Development

Run tests:

```bash
pytest -q
```

Start the scheduler:

```bash
python -m studio.scheduler.worker
```

Generated workspaces, local DBs, caches, and virtual environments are ignored by
Git.

## Extension Points

Future integrations should implement narrow backend interfaces from
`studio.integrations.interfaces` instead of depending on stage internals.

Prepared integration categories:

- planning backends: OpenAI, Claude, Gemini, DeepSeek
- coding backends: Aider, OpenHands, Claude Code
- execution backends: local executor, Docker, Kubernetes
- source-control backends: Git branches, pull requests
- deployment backends: local, Docker, Kubernetes
- external clients: REST API now, WebSocket/MCP later
