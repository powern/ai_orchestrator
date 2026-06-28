import json

from studio.core.runtime_readiness import RuntimeReadinessValidator


def write_file(root, relative_path, content):
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_runtime_readiness_fails_missing_entrypoint(tmp_path):
    write_file(tmp_path, "app/main.py", "def main():\n    return 'ok'\n")
    write_file(tmp_path, "RUN.md", "Install\nRun\nTest\n")

    report = RuntimeReadinessValidator().validate(tmp_path)

    assert report.runtime_entrypoint == "failed"
    assert report.manual_run_ready is False
    assert "Runtime entrypoint is missing." in report.findings


def test_runtime_readiness_fails_flask_werkzeug_incompatibility(tmp_path):
    write_file(
        tmp_path,
        "app/main.py",
        (
            "from flask import Flask\n\n"
            "app = Flask(__name__)\n\n"
            "if __name__ == \"__main__\":\n"
            "    app.run(host=\"0.0.0.0\", port=5000)\n"
        ),
    )
    write_file(tmp_path, "requirements.txt", "Flask==2.0.1\n")
    write_file(tmp_path, "RUN.md", "Install\npip install -r requirements.txt\nRun\nTest\n")

    report = RuntimeReadinessValidator().validate(tmp_path)

    assert report.dependency_check == "failed"
    assert report.dependency_installation == "failed"
    assert any("Werkzeug 3.x is incompatible" in finding for finding in report.findings)


def test_runtime_readiness_fails_missing_import_during_startup(tmp_path):
    write_file(
        tmp_path,
        "app/main.py",
        (
            "from missing_runtime_dependency import boom\n\n"
            "if __name__ == \"__main__\":\n"
            "    boom()\n"
        ),
    )
    write_file(tmp_path, "RUN.md", "Install\nRun\npython app/main.py\nTest\npytest -q\n")

    report = RuntimeReadinessValidator().validate(tmp_path)

    assert report.runtime_entrypoint == "passed"
    assert report.runtime_smoke == "failed"
    assert report.manual_run_ready is False
    assert any("Runtime smoke failed" in finding for finding in report.findings)


def test_runtime_readiness_passes_visual_flask_counter_project(tmp_path):
    write_file(
        tmp_path,
        "app/main.py",
        (
            "from flask import Flask, redirect, render_template_string, url_for\n\n"
            "app = Flask(__name__)\n"
            "counter = {'value': 0}\n\n"
            "TEMPLATE = '<h1>Visual Smoke Test</h1><p>Counter: {{ value }}</p>"
            "<a href=\"/increase\">Increase</a><a href=\"/reset\">Reset</a>'\n\n"
            "@app.route('/')\n"
            "def index():\n"
            "    return render_template_string(TEMPLATE, value=counter['value'])\n\n"
            "@app.route('/increase')\n"
            "def increase():\n"
            "    counter['value'] += 1\n"
            "    return redirect(url_for('index'))\n\n"
            "@app.route('/reset')\n"
            "def reset():\n"
            "    counter['value'] = 0\n"
            "    return redirect(url_for('index'))\n\n"
            "if __name__ == \"__main__\":\n"
            "    app.run(host=\"0.0.0.0\", port=5000)\n"
        ),
    )
    write_file(tmp_path, "requirements.txt", "Flask==3.0.0\nWerkzeug==3.0.1\n")
    write_file(
        tmp_path,
        "tests/test_main.py",
        (
            "def test_visible_behavior():\n"
            "    assert 'Visual Smoke Test'\n"
            "    assert 'Counter: 0'\n"
            "    assert 'Counter: 1'\n"
            "    assert 'Increase'\n"
            "    assert 'Reset'\n"
        ),
    )
    write_file(
        tmp_path,
        "RUN.md",
        (
            "Install dependencies:\n"
            "pip install -r requirements.txt\n\n"
            "Run:\n"
            "python app/main.py\n\n"
            "Test:\n"
            "pytest -q\n\n"
            "Open:\n"
            "http://127.0.0.1:5000/\n"
        ),
    )

    report = RuntimeReadinessValidator().validate(tmp_path)
    payload = json.loads(report.to_json())

    assert payload["dependency_check"] == "passed"
    assert payload["runtime_entrypoint"] == "passed"
    assert payload["runtime_smoke"] == "passed"
    assert payload["behavior_tests"] == "passed"
    assert payload["manual_run_ready"] is True
