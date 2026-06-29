import json

from studio.core.engineering_critic import EngineeringCritic


def actions(*items):
    return json.dumps(list(items))


def write_file(path, content):
    return {"action": "write_file", "path": path, "content": content}


def test_critic_rejects_pass_only_tests():
    result = EngineeringCritic().review(
        original_request="Create a calculator with add and subtract.",
        planner_output="",
        architect_output="",
        coder_output=actions(
            write_file("app/calculator.py", "def add(a, b):\n    return a + b\n"),
            write_file("tests/test_calculator.py", "def test_add():\n    pass\n"),
        ),
    )

    assert result.status == "revision_required"
    assert any(issue.type == "pass_only_tests" for issue in result.issues)


def test_critic_rejects_hello_world_for_richer_request():
    result = EngineeringCritic().review(
        original_request="Create a Flask counter app with Increase and Reset buttons.",
        planner_output="",
        architect_output="",
        coder_output=actions(
            write_file("app/main.py", "print('Hello World')\n"),
            write_file("tests/test_main.py", "def test_ok():\n    assert True\n"),
        ),
    )

    assert result.status == "revision_required"
    assert any(issue.type == "hello_world_replacement" for issue in result.issues)
    assert any(issue.type == "requirements_lost" for issue in result.issues)


def test_critic_detects_missing_runtime_behavior():
    result = EngineeringCritic().review(
        original_request="Create a visual Flask web app.",
        planner_output="",
        architect_output="",
        coder_output=actions(
            write_file("app/main.py", "from flask import Flask\napp = Flask(__name__)\n"),
            write_file("tests/test_main.py", "def test_ok():\n    assert True\n"),
        ),
    )

    assert result.status == "revision_required"
    assert any(issue.type == "missing_runtime_entrypoint" for issue in result.issues)


def test_critic_uses_project_graph_for_route_coverage():
    result = EngineeringCritic().review(
        original_request="Create a Flask app with home and reset routes.",
        planner_output="",
        architect_output="",
        coder_output=actions(
            write_file(
                "app/main.py",
                "from flask import Flask\n"
                "app = Flask(__name__)\n"
                "@app.route('/')\n"
                "def index():\n"
                "    return 'home'\n"
                "@app.route('/reset')\n"
                "def reset():\n"
                "    return 'reset'\n"
                "if __name__ == '__main__':\n"
                "    app.run()\n",
            ),
            write_file(
                "tests/test_main.py",
                "def test_home(client):\n"
                "    assert client.get('/').status_code == 200\n",
            ),
        ),
    )

    assert result.status == "approved"
    assert any(issue.type == "weak_route_coverage" for issue in result.issues)
    assert result.project_graph["summary"]["uncovered_routes"] == 1


def test_critic_result_schema_validation():
    critic = EngineeringCritic()
    result = critic.review(
        original_request="Create a calculator with add.",
        planner_output="",
        architect_output="",
        coder_output=actions(
            write_file("app/calculator.py", "def add(a, b):\n    return a + b\n"),
            write_file(
                "tests/test_calculator.py",
                "from app.calculator import add\n"
                "def test_add():\n"
                "    assert add(1, 2) == 3\n",
            ),
        ),
    )

    critic.validate_result_schema(result)
    assert set(result.to_dict()) == {
        "status",
        "confidence",
        "issues",
        "recommended_objective",
        "project_graph",
    }
