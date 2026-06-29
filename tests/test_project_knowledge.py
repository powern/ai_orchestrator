from studio.core.project_knowledge import ProjectKnowledgeGraphBuilder
from studio.core.workspace_observer import WorkspaceObserver


def test_project_graph_detects_python_package_imports_and_dependencies(tmp_path):
    (tmp_path / "app" / "services").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("")
    (tmp_path / "app" / "services" / "__init__.py").write_text("")
    (tmp_path / "app" / "main.py").write_text(
        "from app.services.calc import add\n"
        "import flask\n"
        "def main():\n"
        "    return add(1, 2)\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )
    (tmp_path / "app" / "services" / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_main.py").write_text(
        "from app.main import main\n"
        "def test_main():\n"
        "    assert main() == 3\n",
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text("Flask==3.0.0\n")

    graph = WorkspaceObserver().observe(tmp_path)["project_graph"]

    assert graph["summary"]["project_types"] == ["python"]
    assert {package["name"] for package in graph["packages"]} == {"app", "app.services"}
    assert {
        (edge["source"], edge["target"], edge["relationship"])
        for edge in graph["import_graph"]
    } >= {("app.main", "app.services.calc", "imports")}
    assert graph["dependencies"][0]["name"] == "Flask"
    assert graph["entrypoints"][0]["module"] == "app.main"
    assert any(
        item["module"] == "app.main" and item["covered"]
        for item in graph["test_coverage_map"]["modules"]
    )


def test_project_graph_detects_flask_routes_and_route_coverage(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "app" / "main.py").write_text(
        "from flask import Flask\n"
        "app = Flask(__name__)\n"
        "@app.route('/')\n"
        "def index():\n"
        "    return 'home'\n"
        "@app.route('/increase', methods=['POST'])\n"
        "def increase():\n"
        "    return 'ok'\n"
        "if __name__ == '__main__':\n"
        "    app.run()\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_app.py").write_text(
        "def test_home(client):\n"
        "    response = client.get('/')\n"
        "    assert response.status_code == 200\n",
        encoding="utf-8",
    )

    graph = WorkspaceObserver().observe(tmp_path)["project_graph"]

    assert "flask" in graph["summary"]["project_types"]
    assert graph["entrypoints"][0]["kind"] == "web"
    assert {route["path"] for route in graph["routes"]} == {"/", "/increase"}
    assert graph["summary"]["covered_routes"] == 1
    assert graph["summary"]["uncovered_routes"] == 1


def test_project_graph_detects_fastapi_and_cli_projects(tmp_path):
    (tmp_path / "api").mkdir()
    (tmp_path / "tools").mkdir()
    (tmp_path / "api" / "main.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "@app.get('/items')\n"
        "async def items():\n"
        "    return []\n",
        encoding="utf-8",
    )
    (tmp_path / "tools" / "cli.py").write_text(
        "import argparse\n"
        "def main():\n"
        "    parser = argparse.ArgumentParser()\n"
        "    parser.parse_args()\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )

    graph = WorkspaceObserver().observe(tmp_path)["project_graph"]

    assert "fastapi" in graph["summary"]["project_types"]
    assert "cli" in graph["summary"]["project_types"]
    assert graph["routes"][0]["framework"] == "fastapi"
    assert {entrypoint["kind"] for entrypoint in graph["entrypoints"]} == {"cli"}


def test_project_graph_serializes_empty_model():
    graph = ProjectKnowledgeGraphBuilder().empty()

    assert graph["schema_version"] == 1
    assert graph["summary"]["module_count"] == 0
    assert graph["nodes"] == []
    assert graph["edges"] == []
