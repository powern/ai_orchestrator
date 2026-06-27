from pathlib import Path

from studio.database.db import init_db
from studio.services.project_service import create_project, get_project, slugify


def test_slugify():
    assert slugify("My Flask App") == "my-flask-app"
    assert slugify(" AI Studio!!! ") == "ai-studio"


def test_create_project_creates_workspace():
    init_db()

    project_id = create_project(
        "Test Project",
        "Create a test project workspace",
    )

    project = get_project(project_id)

    assert project is not None
    assert project["name"] == "Test Project"
    assert Path(project["workspace_path"]).exists()
