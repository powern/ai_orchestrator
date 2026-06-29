import json
import os
from typing import Any

from studio.core.engineering_assessment import (
    ConfidenceAssessor,
    EngineeringDecisionModel,
)
from studio.core.workspace_observer import WorkspaceObserver
from studio.database.db import get_connection
from studio.events.publisher import publish_run_event
from studio.services.event_service import list_events
from studio.services.project_service import get_project
from studio.services.run_service import get_run


def is_engineering_shadow_enabled() -> bool:
    return os.environ.get("AI_ORCHESTRATOR_ENGINEERING_SHADOW") == "1"


def record_engineering_shadow_assessment(run_id: int, project: dict | None) -> dict | None:
    if not is_engineering_shadow_enabled():
        return None

    run_row = get_run(run_id)
    if run_row is None:
        return None

    run = dict(run_row)
    project_data = dict(project or {})
    if not project_data:
        project_row = get_project(run["project_id"])
        project_data = dict(project_row) if project_row is not None else {}

    workspace_path = project_data.get("workspace_path")
    if not workspace_path:
        return None

    publish_run_event(
        run_id,
        run["project_id"],
        "engineering_observation_started",
        "engineering",
        "Engineering shadow observation started.",
    )

    observation = WorkspaceObserver().observe(workspace_path)
    publish_run_event(
        run_id,
        run["project_id"],
        "engineering_observation_completed",
        "engineering",
        "Engineering shadow observation completed.",
        json.dumps(observation, ensure_ascii=False),
    )

    events = [dict(row) for row in list_events(run_id)]
    confidence = ConfidenceAssessor().assess(run, events, observation)
    decision = EngineeringDecisionModel().decide(confidence, observation, run)
    persisted = persist_engineering_assessment(
        project_id=run["project_id"],
        run_id=run_id,
        observation=observation,
        confidence=confidence.to_dict(),
        decision=decision,
        run=run,
    )

    publish_run_event(
        run_id,
        run["project_id"],
        "engineering_assessment_completed",
        "engineering",
        "Engineering shadow assessment completed.",
        json.dumps(
            {
                "confidence": confidence.to_dict(),
                "decision": decision,
            },
            ensure_ascii=False,
        ),
    )

    return persisted


def persist_engineering_assessment(
    project_id: int,
    run_id: int,
    observation: dict,
    confidence: dict,
    decision: dict,
    run: dict,
) -> dict:
    with get_connection() as conn:
        session_cur = conn.execute(
            """
            INSERT INTO engineering_sessions
            (
                project_id,
                run_id,
                status,
                confidence,
                proposed_objective,
                should_continue
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                run_id,
                "observed",
                confidence["score"],
                decision["next_objective"],
                int(bool(decision["should_continue"])),
            ),
        )
        session_id = session_cur.lastrowid

        cycle_cur = conn.execute(
            """
            INSERT INTO engineering_cycles
            (
                session_id,
                cycle_number,
                objective,
                status,
                confidence_before
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session_id,
                0,
                decision["next_objective"],
                "proposed",
                confidence["score"],
            ),
        )
        cycle_id = cycle_cur.lastrowid

        conn.execute(
            """
            INSERT INTO project_state_snapshots
            (
                session_id,
                run_id,
                payload_json,
                confidence_json,
                decision_json
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session_id,
                run_id,
                json.dumps(observation, ensure_ascii=False),
                json.dumps(confidence, ensure_ascii=False),
                json.dumps(decision, ensure_ascii=False),
            ),
        )

        for result in _validation_results(run):
            conn.execute(
                """
                INSERT INTO validation_results
                (
                    session_id,
                    cycle_id,
                    run_id,
                    kind,
                    status,
                    payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    cycle_id,
                    run_id,
                    result["kind"],
                    result["status"],
                    result["payload_json"],
                ),
            )

        conn.commit()

    return {
        "session_id": session_id,
        "cycle_id": cycle_id,
        "confidence": confidence,
        "decision": decision,
        "observation": observation,
    }


def get_latest_engineering_assessment(run_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                s.id AS session_id,
                s.confidence,
                s.proposed_objective,
                s.should_continue,
                s.status,
                p.payload_json,
                p.confidence_json,
                p.decision_json,
                p.created_at
            FROM engineering_sessions s
            JOIN project_state_snapshots p ON p.session_id = s.id
            WHERE s.run_id = ?
            ORDER BY s.id DESC
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()

    if row is None:
        return None

    return {
        "session": {
            "id": row["session_id"],
            "status": row["status"],
            "confidence": row["confidence"],
            "proposed_objective": row["proposed_objective"],
            "should_continue": bool(row["should_continue"]),
            "created_at": row["created_at"],
        },
        "observation": _loads(row["payload_json"]),
        "project_graph": _loads(row["payload_json"]).get("project_graph", {}),
        "confidence": _loads(row["confidence_json"]),
        "decision": _loads(row["decision_json"]),
    }


def _validation_results(run: dict) -> list[dict[str, Any]]:
    results = []
    if run.get("runtime_readiness"):
        payload = run["runtime_readiness"]
        readiness = _loads(payload)
        status = "passed" if readiness.get("manual_run_ready") else "failed"
        results.append(
            {
                "kind": "runtime_readiness",
                "status": status,
                "payload_json": payload,
            }
        )

    if (
        run.get("tester_output_after_fix")
        or run.get("tester_output_before_fix")
        or run.get("tester_output")
    ):
        status = "passed" if run.get("status") == "completed" else "failed"
        results.append(
            {
                "kind": "tester",
                "status": status,
                "payload_json": json.dumps(
                    {
                        "tester_output": run.get("tester_output"),
                        "tester_output_before_fix": run.get("tester_output_before_fix"),
                        "tester_output_after_fix": run.get("tester_output_after_fix"),
                    },
                    ensure_ascii=False,
                ),
            }
        )

    return results


def _loads(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
