from studio.core.workspace_observer import WorkspaceObserver


def test_workspace_observer_summarizes_project_and_excludes_caches(tmp_path):
    (tmp_path / "app" / "__pycache__").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".pytest_cache").mkdir()

    (tmp_path / "app" / "main.py").write_text(
        "from flask import Flask\napp = Flask(__name__)\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_main.py").write_text("def test_ok():\n    assert True\n")
    (tmp_path / "requirements.txt").write_text("Flask==3.0.0\n")
    (tmp_path / "RUN.md").write_text("Run: python app/main.py\n")
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "app" / "__pycache__" / "main.cpython-311.pyc").write_bytes(b"x")
    (tmp_path / ".git" / "config").write_text("[core]\n")
    (tmp_path / ".venv" / "lib" / "site.py").write_text("ignored = True\n")
    (tmp_path / ".pytest_cache" / "nodeids").write_text("ignored\n")
    (tmp_path / "image.png").write_bytes(b"not source")

    observation = WorkspaceObserver().observe(tmp_path)
    tree = "\n".join(observation["workspace_tree"])

    assert observation["exists"] is True
    assert observation["source_files"]["files"] == ["app/main.py"]
    assert observation["tests"]["files"] == ["tests/test_main.py"]
    assert observation["dependency_files"] == ["requirements.txt"]
    assert observation["run_metadata_files"] == ["RUN.md"]
    assert "pytest.ini" in observation["validation_artifacts"]
    assert "python" in observation["project_type_hints"]
    assert "flask" in observation["project_type_hints"]
    assert observation["project_graph"]["summary"]["module_count"] == 1
    assert observation["project_graph"]["summary"]["test_count"] == 1
    assert "__pycache__" not in tree
    assert ".git" not in tree
    assert ".venv" not in tree
    assert ".pytest_cache" not in tree
    assert observation["ignored_files_summary"]["count"] >= 4
