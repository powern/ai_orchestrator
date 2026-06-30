import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from studio.contracts.execution import infer_execution_contract
from studio.database.db import get_connection
from studio.events.publisher import publish_run_event


@dataclass(frozen=True)
class DecisionRecord:
    agent: str
    summary: str
    decisions: list[str] = field(default_factory=list)
    protected_decisions: list[str] = field(default_factory=list)
    assumptions: dict[str, Any] = field(default_factory=dict)
    risks: list[str] = field(default_factory=list)
    confidence: float = 0.7
    expected_next_agent: str = ""
    expected_validation: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "summary": self.summary,
            "decisions": self.decisions,
            "protected_decisions": self.protected_decisions,
            "assumptions": self.assumptions,
            "risks": self.risks,
            "confidence": self.confidence,
            "expected_next_agent": self.expected_next_agent,
            "expected_validation": self.expected_validation,
        }


@dataclass(frozen=True)
class AgentHandoff:
    producer: str
    consumer: str
    summary: str
    project_assumptions: dict[str, Any] = field(default_factory=dict)
    non_negotiable_requirements: list[str] = field(default_factory=list)
    implementation_contract: dict[str, Any] = field(default_factory=dict)
    known_risks: list[str] = field(default_factory=list)
    recommended_focus: list[str] = field(default_factory=list)
    do_not_change: list[str] = field(default_factory=list)
    decision_record: DecisionRecord | None = None

    def to_dict(self) -> dict[str, Any]:
        decision_record = self.decision_record or DecisionRecord(
            agent=self.producer,
            summary=self.summary,
            assumptions=self.project_assumptions,
            risks=self.known_risks,
            expected_next_agent=self.consumer,
        )
        return {
            "producer": self.producer,
            "consumer": self.consumer,
            "summary": self.summary,
            "project_assumptions": self.project_assumptions,
            "non_negotiable_requirements": self.non_negotiable_requirements,
            "implementation_contract": self.implementation_contract,
            "known_risks": self.known_risks,
            "recommended_focus": self.recommended_focus,
            "do_not_change": self.do_not_change,
            "decision_record": decision_record.to_dict(),
            "decisions": decision_record.decisions,
            "protected_decisions": decision_record.protected_decisions,
            "assumptions": decision_record.assumptions,
            "risks": decision_record.risks,
            "confidence": decision_record.confidence,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def build_handoff(
    producer: str,
    consumer: str,
    summary: str,
    agent_context=None,
    implementation_contract: dict[str, Any] | None = None,
    known_risks: list[str] | None = None,
    recommended_focus: list[str] | None = None,
    do_not_change: list[str] | None = None,
    decisions: list[str] | None = None,
    protected_decisions: list[str] | None = None,
    confidence: float = 0.7,
    expected_validation: list[str] | None = None,
) -> AgentHandoff:
    context = agent_context.to_dict() if hasattr(agent_context, "to_dict") else agent_context or {}
    task = context.get("task", {})
    project = context.get("project", {})
    project_graph = project.get("project_graph", {})
    execution_contract = _execution_contract_for_context(project, summary)
    project_specification = project.get("project_specification") or project.get(
        "project_state",
        {},
    ).get("project_specification", {})
    graph_summary = project_graph.get("summary", {})
    assumptions = {
        "project_types": graph_summary.get("project_types", []),
        "workspace_path": project.get("workspace_path", ""),
    }
    assumptions.update(_assumptions_from_graph(project_graph))
    assumptions.update(_assumptions_from_summary(summary))
    concrete_contract = _compact_contract(
        implementation_contract or {},
        summary,
        project_graph,
        producer,
        execution_contract,
        project_specification,
    )
    decision_summary = _decision_summary(summary)
    effective_risks = known_risks or []
    effective_focus = recommended_focus or _focus_from_summary(summary)
    effective_protected = protected_decisions or do_not_change or [
        "original_user_request",
        "acceptance_criteria",
        "project_graph",
    ]
    decision_record = DecisionRecord(
        agent=producer,
        summary=decision_summary,
        decisions=decisions or _decisions_from_contract(concrete_contract),
        protected_decisions=effective_protected,
        assumptions=assumptions,
        risks=effective_risks,
        confidence=confidence,
        expected_next_agent=consumer,
        expected_validation=expected_validation or _expected_validation_for_consumer(consumer),
    )
    return AgentHandoff(
        producer=producer,
        consumer=consumer,
        summary=decision_summary,
        project_assumptions=assumptions,
        non_negotiable_requirements=task.get("non_negotiable_requirements", []),
        implementation_contract=concrete_contract,
        known_risks=effective_risks,
        recommended_focus=effective_focus,
        do_not_change=do_not_change or effective_protected,
        decision_record=decision_record,
    )


def append_handoff(
    run_id: int,
    stage: str,
    handoff: AgentHandoff,
    workspace_path: str | None = None,
) -> int:
    payload = handoff.to_json()
    with get_connection() as conn:
        project_id = _project_id_for_run(conn, run_id)
        cur = conn.execute(
            """
            INSERT INTO agent_handoffs
            (
                run_id,
                stage,
                producer,
                consumer,
                payload_json
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, stage, handoff.producer, handoff.consumer, payload),
        )
        conn.commit()
        handoff_id = cur.lastrowid

    if workspace_path:
        _write_handoff_artifact(workspace_path, handoff_id, stage, payload)

    publish_run_event(
        run_id,
        project_id,
        "agent_handoff_recorded",
        stage,
        f"{handoff.producer} handoff recorded for {handoff.consumer}.",
        payload,
    )
    return handoff_id


def load_latest_handoff(run_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM agent_handoffs
            WHERE run_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
    return _row_to_handoff(row)


def load_handoff_history(run_id: int) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM agent_handoffs
            WHERE run_id = ?
            ORDER BY id ASC
            """,
            (run_id,),
        ).fetchall()
    return [_row_to_handoff(row) for row in rows if row is not None]


def _row_to_handoff(row) -> dict[str, Any] | None:
    if row is None:
        return None
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, json.JSONDecodeError):
        payload = {}
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "stage": row["stage"],
        "producer": row["producer"],
        "consumer": row["consumer"],
        "created_at": row["created_at"],
        "payload": payload,
    }


def _write_handoff_artifact(workspace_path: str, handoff_id: int, stage: str, payload: str) -> None:
    root = Path(workspace_path) / ".orchestrator" / "handoff"
    root.mkdir(parents=True, exist_ok=True)
    numbered = root / f"{handoff_id:04d}-{stage}.json"
    latest = root / f"{stage}.json"
    numbered.write_text(payload, encoding="utf-8")
    latest.write_text(payload, encoding="utf-8")


def _project_id_for_run(conn, run_id: int) -> int | None:
    row = conn.execute("SELECT project_id FROM runs WHERE id = ?", (run_id,)).fetchone()
    return row["project_id"] if row is not None else None


def _summarize(value: str, max_chars: int = 700) -> str:
    text = (value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def _decision_summary(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return "No decision summary was provided."
    executor_summary = _executor_action_summary(text)
    if executor_summary:
        return executor_summary
    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if _looks_like_implementation_line(line):
            continue
        if line:
            lines.append(line)
        if len(lines) >= 8:
            break
    return _summarize("\n".join(lines) or "Implementation details were omitted from handoff.")


def _executor_action_summary(text: str) -> str | None:
    try:
        parsed = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, list):
        return None
    action_counts: dict[str, int] = {}
    write_paths = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        action = item.get("action", "unknown")
        action_counts[action] = action_counts.get(action, 0) + 1
        if action == "write_file" and item.get("path"):
            write_paths.append(item["path"])
    action_text = ", ".join(f"{name}: {count}" for name, count in sorted(action_counts.items()))
    paths = ", ".join(write_paths[:8])
    if len(write_paths) > 8:
        paths += ", ..."
    return (
        f"Produced canonical Executor action plan ({action_text}). "
        f"Target files: {paths or 'none'}."
    )


def _compact_contract(
    contract: dict[str, Any],
    summary: str,
    project_graph: dict[str, Any],
    producer: str,
    execution_contract: dict[str, Any],
    project_specification: dict[str, Any],
) -> dict[str, Any]:
    compact = dict(contract)
    compact.update(_contract_from_graph(project_graph))
    compact.update(_contract_from_executor_actions(summary, producer))
    if project_specification:
        compact["project_specification"] = project_specification
        compact.update(_specification_decision_fields(project_specification))
    if execution_contract:
        compact["project_execution_contract"] = execution_contract
        compact.update(_execution_contract_decision_fields(execution_contract))
    return {key: value for key, value in compact.items() if value not in (None, [], {}, "")}


def _execution_contract_for_context(project: dict[str, Any], summary: str) -> dict[str, Any]:
    existing = project.get("project_execution_contract") or project.get("execution_contract")
    if existing:
        return existing
    actions = _executor_actions(summary)
    return infer_execution_contract(
        workspace_path=project.get("workspace_path") or None,
        workspace_state=project.get("workspace_state") or {},
        project_graph=project.get("project_graph") or {},
        executor_actions=actions,
        project_specification=project.get("project_specification")
        or project.get("project_state", {}).get("project_specification"),
    ).to_dict()


def _contract_from_graph(project_graph: dict[str, Any]) -> dict[str, Any]:
    if not project_graph:
        return {}
    entrypoints = project_graph.get("entrypoints", [])
    routes = project_graph.get("routes", [])
    dependencies = project_graph.get("dependencies", [])
    tests = project_graph.get("tests", [])
    modules = project_graph.get("modules", [])
    contract = {
        "framework": _framework_from_graph(project_graph),
        "package_root": _package_root(project_graph),
        "entrypoint": entrypoints[0]["path"] if entrypoints else None,
        "run_command": f"python {entrypoints[0]['path']}" if entrypoints else None,
        "test_command": "pytest -q" if tests else None,
        "route_contract": [route["path"] for route in routes],
        "dependency_files": [dependency.get("source") for dependency in dependencies],
        "modules": [module.get("path") for module in modules],
        "test_files": [test.get("path") for test in tests],
    }
    if contract["framework"] == "flask" and entrypoints:
        module = entrypoints[0]["module"]
        contract["flask_app_symbol"] = f"{module}.app"
        contract["test_import_contract"] = f"from {module} import app"
    return contract


def _contract_from_executor_actions(summary: str, producer: str) -> dict[str, Any]:
    actions = _executor_actions(summary)
    if not isinstance(actions, list):
        return {}
    write_paths = [
        action.get("path")
        for action in actions
        if isinstance(action, dict)
        and action.get("action") == "write_file"
        and action.get("path")
    ]
    run_commands = [
        action.get("command")
        for action in actions
        if isinstance(action, dict)
        and action.get("action") == "run"
        and action.get("command")
    ]
    contract = {
        "generated_files": write_paths,
        "changed_files": write_paths if producer == "fix" else [],
        "dependency_files": [path for path in write_paths if _is_dependency_file(path)],
        "runtime_entrypoints": [
            path for path in write_paths if path in {"app/main.py", "main.py", "app.py"}
        ],
        "run_command": _first_runtime_command(run_commands, write_paths),
        "test_command": _first_test_command(run_commands)
        or ("pytest -q" if any(path.startswith("tests/") for path in write_paths) else None),
    }
    return contract


def _executor_actions(summary: str) -> list[dict[str, Any]]:
    try:
        actions = json.loads(summary)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(actions, list):
        return []
    return [action for action in actions if isinstance(action, dict)]


def _execution_contract_decision_fields(contract: dict[str, Any]) -> dict[str, Any]:
    build = contract.get("build") or {}
    run = contract.get("run") or {}
    test = contract.get("test") or {}
    module = contract.get("module_strategy") or {}
    artifacts = contract.get("artifacts") or {}
    fields = {
        "language": contract.get("language"),
        "project_root": contract.get("project_root"),
        "source_roots": contract.get("source_roots"),
        "test_roots": contract.get("test_roots"),
        "build_command": build.get("command"),
        "run_command": run.get("command"),
        "test_command": test.get("command"),
        "module_strategy": module.get("type"),
        "import_root": module.get("import_root"),
        "namespace_root": module.get("namespace_root"),
        "include_roots": module.get("include_roots"),
        "expected_files": artifacts.get("expected_files"),
        "expected_directories": artifacts.get("expected_directories"),
    }
    return {key: value for key, value in fields.items() if value not in (None, [], {}, "")}


def _specification_decision_fields(specification: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "specified_project_type": specification.get("project_type"),
        "specified_language": specification.get("language"),
        "specified_framework": specification.get("framework"),
        "required_features": [
            feature.get("name") for feature in specification.get("features", [])
        ],
        "required_entities": [
            entity.get("name") for entity in specification.get("entities", [])
        ],
        "specification_confidence": specification.get("confidence"),
    }
    return {key: value for key, value in fields.items() if value not in (None, [], {}, "")}


def _assumptions_from_graph(project_graph: dict[str, Any]) -> dict[str, Any]:
    if not project_graph:
        return {}
    return {
        "framework": _framework_from_graph(project_graph),
        "package_root": _package_root(project_graph),
    }


def _assumptions_from_summary(summary: str) -> dict[str, Any]:
    try:
        actions = json.loads(summary)
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(actions, list):
        return {}
    write_paths = [
        action.get("path")
        for action in actions
        if isinstance(action, dict)
        and action.get("action") == "write_file"
        and action.get("path")
    ]
    roots = sorted({path.split("/", 1)[0] for path in write_paths if "/" in path})
    return {"package_root": "app"} if "app" in roots else {}


def _framework_from_graph(project_graph: dict[str, Any]) -> str | None:
    project_types = project_graph.get("summary", {}).get("project_types", [])
    if "flask" in project_types:
        return "flask"
    if "fastapi" in project_types:
        return "fastapi"
    if "django" in project_types:
        return "django"
    return None


def _package_root(project_graph: dict[str, Any]) -> str | None:
    packages = project_graph.get("packages", [])
    package_names = [package.get("name") for package in packages]
    if "app" in package_names:
        return "app"
    return package_names[0] if package_names else None


def _is_dependency_file(path: str) -> bool:
    return path in {"requirements.txt", "requirements-dev.txt", "pyproject.toml"}


def _first_runtime_command(commands: list[str], write_paths: list[str]) -> str | None:
    for command in commands:
        if command.startswith("python "):
            return command
    for path in ("app/main.py", "app.py", "main.py"):
        if path in write_paths:
            return f"python {path}"
    return None


def _first_test_command(commands: list[str]) -> str | None:
    for command in commands:
        if "pytest" in command:
            return command
    return None


def _looks_like_implementation_line(line: str) -> bool:
    if not line:
        return False
    implementation_prefixes = (
        "def ",
        "class ",
        "import ",
        "from ",
        "return ",
        "assert ",
        "{",
        "}",
        "[",
        "]",
        '"content"',
        '"action"',
    )
    return line.startswith(implementation_prefixes)


def _decisions_from_contract(contract: dict[str, Any]) -> list[str]:
    decisions = []
    for key, value in contract.items():
        decisions.append(f"{key}: {value}")
    return decisions[:12]


def _expected_validation_for_consumer(consumer: str) -> list[str]:
    mapping = {
        "architect": ["architecture preserves planner goals"],
        "coder": ["canonical Executor JSON implements architecture"],
        "executor": ["executor actions apply cleanly"],
        "tester": ["pytest validates requested behavior"],
        "failure_analyzer": ["root cause is identified from evidence"],
        "repair_planner": ["repair targets are specific and justified"],
        "fix": ["fix preserves original requirements"],
        "static_reviewer": ["static review approves repaired actions"],
        "runtime_readiness": ["manual runtime readiness passes"],
    }
    return mapping.get(consumer, ["next stage consumes decision record"])


def _focus_from_summary(summary: str) -> list[str]:
    text = (summary or "").lower()
    focus = []
    for keyword in ("tests", "runtime", "imports", "flask", "requirements", "repair"):
        if keyword in text:
            focus.append(keyword)
    return focus
