import re
from pathlib import Path

from studio.config.settings import WORKSPACES_DIR
from studio.database.db import get_connection


def slugify(name):
    value = name.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "project"


def create_project(name, description):
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
        return conn.execute(
            "SELECT * FROM projects ORDER BY id DESC"
        ).fetchall()


def get_project(project_id):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
