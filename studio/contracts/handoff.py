import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
    graph_summary = project.get("project_graph", {}).get("summary", {})
    assumptions = {
        "project_types": graph_summary.get("project_types", []),
        "workspace_path": project.get("workspace_path", ""),
    }
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
        decisions=decisions or _decisions_from_contract(implementation_contract or {}),
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
        implementation_contract=implementation_contract or {},
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
