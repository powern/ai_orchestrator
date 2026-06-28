import re
from pathlib import Path
from typing import Any

from studio.config.settings import WORKSPACES_DIR
from studio.database.db import get_connection


def slugify(name: str) -> str:
    value = name.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "project"


def create_project(name: str, description: str) -> int:
    slug = slugify(name)

    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO projects (name, description, workspace_path)
            VALUES (?, ?, ?)
            """,
            (name, description, ""),
        )
        project_id = cur.lastrowid

        workspace_path = WORKSPACES_DIR / f"{project_id}-{slug}"
        Path(workspace_path).mkdir(parents=True, exist_ok=True)

        conn.execute(
            """
            UPDATE projects
            SET workspace_path = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (str(workspace_path), project_id),
        )

        conn.commit()

    return project_id


def list_projects():
    with get_connection() as conn:
        return conn.execute("SELECT * FROM projects ORDER BY id DESC").fetchall()


def get_project(project_id: int):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()


def list_project_summaries() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT
                projects.*,
                project_runtime.status AS runtime_status,
                project_runtime.current_stage AS runtime_stage,
                project_runtime.current_agent AS runtime_agent,
                project_runtime.progress AS runtime_progress,
                project_runtime.run_id AS runtime_run_id,
                project_runtime.message AS runtime_message,
                project_runtime.updated_at AS runtime_updated_at,
                latest_run.id AS last_run_id,
                latest_run.status AS last_run_status,
                latest_run.current_stage AS last_run_stage,
                latest_run.updated_at AS last_run_updated_at
            FROM projects
            LEFT JOIN project_runtime ON project_runtime.project_id = projects.id
            LEFT JOIN runs latest_run ON latest_run.id = (
                SELECT id FROM runs
                WHERE runs.project_id = projects.id
                ORDER BY id DESC
                LIMIT 1
            )
            ORDER BY projects.id DESC
            """).fetchall()

    return [_with_dashboard_state(dict(row)) for row in rows]


def get_project_summary(project_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                projects.*,
                project_runtime.status AS runtime_status,
                project_runtime.current_stage AS runtime_stage,
                project_runtime.current_agent AS runtime_agent,
                project_runtime.progress AS runtime_progress,
                project_runtime.run_id AS runtime_run_id,
                project_runtime.message AS runtime_message,
                project_runtime.updated_at AS runtime_updated_at,
                latest_run.id AS last_run_id,
                latest_run.status AS last_run_status,
                latest_run.current_stage AS last_run_stage,
                latest_run.updated_at AS last_run_updated_at
            FROM projects
            LEFT JOIN project_runtime ON project_runtime.project_id = projects.id
            LEFT JOIN runs latest_run ON latest_run.id = (
                SELECT id FROM runs
                WHERE runs.project_id = projects.id
                ORDER BY id DESC
                LIMIT 1
            )
            WHERE projects.id = ?
            """,
            (project_id,),
        ).fetchone()

    return _with_dashboard_state(dict(row)) if row is not None else None


def _with_dashboard_state(project: dict[str, Any]) -> dict[str, Any]:
    current_status = (
        project.get("runtime_status")
        or project.get("last_run_status")
        or project.get("status")
        or "created"
    )
    current_stage = project.get("runtime_stage") or project.get("last_run_stage") or "new"
    latest_run_id = project.get("runtime_run_id") or project.get("last_run_id")
    progress = project.get("runtime_progress")

    if progress is None:
        progress = 100 if current_status == "completed" else 0

    project.update(
        {
            "latest_run_id": latest_run_id,
            "current_status": current_status,
            "current_stage": current_stage,
            "current_agent": project.get("runtime_agent"),
            "current_progress": progress,
            "current_message": project.get("runtime_message") or "",
            "current_updated_at": (
                project.get("runtime_updated_at")
                or project.get("last_run_updated_at")
                or project.get("updated_at")
            ),
        }
    )
    return project


def get_dashboard_metrics() -> dict[str, Any]:
    projects = list_project_summaries()

    total_runs = 0
    completed_runs = 0
    active_run = None

    with get_connection() as conn:
        run_counts = conn.execute("""
            SELECT
                COUNT(*) AS total_runs,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_runs
            FROM runs
            """).fetchone()
        active_run = conn.execute("""
            SELECT *
            FROM runs
            WHERE status IN ('queued', 'running')
            ORDER BY id ASC
            LIMIT 1
            """).fetchone()

    if run_counts is not None:
        total_runs = run_counts["total_runs"] or 0
        completed_runs = run_counts["completed_runs"] or 0

    counts = {
        "total_projects": len(projects),
        "queued": 0,
        "running": 0,
        "completed": 0,
        "failed": 0,
        "total_runs": total_runs,
        "success_rate": round((completed_runs / total_runs) * 100, 1) if total_runs else 0,
        "scheduler_status": "active" if active_run is not None else "idle",
        "active_run": dict(active_run) if active_run is not None else None,
        "total_execution_time": None,
    }

    for project in projects:
        status = project.get("current_status") or project.get("status") or "queued"
        if status in counts:
            counts[status] += 1

    return counts
