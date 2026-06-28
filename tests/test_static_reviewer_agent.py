from studio.reviewer.static_agent import StaticReviewerAgent


def test_static_reviewer_approves_clean_actions():
    actions = [
        {
            "action": "mkdir",
            "path": "app",
        },
        {
            "action": "write_file",
            "path": "app/main.py",
            "content": "def main():\n    return 'ok'\n",
        },
    ]

    result = StaticReviewerAgent().review(actions)

    assert result.approved is True
    assert result.score == 100
    assert result.findings == []


def test_static_reviewer_rejects_absolute_path():
    actions = [
        {
            "action": "write_file",
            "path": "/etc/passwd",
            "content": "bad",
        }
    ]

    result = StaticReviewerAgent().review(actions)

    assert result.approved is False
    assert any("Absolute path" in finding for finding in result.findings)


def test_static_reviewer_rejects_placeholder_and_dangerous_command():
    actions = [
        {
            "action": "write_file",
            "path": "app/main.py",
            "content": "print('Hello, World!')",
        },
        {
            "action": "run",
            "command": "rm -rf /",
        },
    ]

    result = StaticReviewerAgent().review(actions)

    assert result.approved is False
    assert any("Placeholder text" in finding for finding in result.findings)
    assert any("Dangerous command" in finding for finding in result.findings)


def test_static_reviewer_rejects_single_quote_placeholder():
    actions = [
        {
            "action": "write_file",
            "path": "app/main.py",
            "content": "print('Hello, World!')",
        },
    ]

    result = StaticReviewerAgent().review(actions)

    assert result.approved is False
    assert any("Placeholder text" in finding for finding in result.findings)


def test_static_reviewer_rejects_missing_flask_helper_imports_and_run_block():
    actions = [
        {
            "action": "write_file",
            "path": "app/main.py",
            "content": (
                "from flask import Flask\n\n"
                "app = Flask(__name__)\n\n"
                "@app.route('/increase')\n"
                "def increase():\n"
                "    return redirect(url_for('index'))\n"
            ),
        }
    ]

    result = StaticReviewerAgent().review(actions)

    assert result.approved is False
    assert "Flask helper redirect used but not imported in app/main.py" in result.findings
    assert "Flask helper url_for used but not imported in app/main.py" in result.findings
    assert "Flask app is missing manual app.run entrypoint in app/main.py" in result.findings


def test_static_reviewer_rejects_flask_route_without_app_object():
    actions = [
        {
            "action": "write_file",
            "path": "app/main.py",
            "content": (
                "from flask import Flask\n\n"
                "@app.route('/')\n"
                "def index():\n"
                "    return 'ok'\n\n"
                "if __name__ == '__main__':\n"
                "    app.run(host=\"0.0.0.0\", port=5000)\n"
            ),
        }
    ]

    result = StaticReviewerAgent().review(actions)

    assert result.approved is False
    assert "Flask route exists but app object is not defined in app/main.py" in result.findings


def test_static_reviewer_accepts_visual_flask_counter_ready_for_manual_run():
    actions = [
        {"action": "mkdir", "path": "app"},
        {"action": "mkdir", "path": "tests"},
        {
            "action": "write_file",
            "path": "app/main.py",
            "content": (
                "from flask import Flask, redirect, render_template_string, url_for\n\n"
                "app = Flask(__name__)\n"
                "counter = {'value': 0}\n\n"
                "TEMPLATE = '''<h1>Visual Smoke Test</h1><p>Counter: {{ value }}</p>"
                "<a href=\"/increase\">Increase</a><a href=\"/reset\">Reset</a>'''\n\n"
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
        },
        {
            "action": "write_file",
            "path": "tests/test_main.py",
            "content": (
                "from app.main import app, counter\n\n"
                "def test_counter_visible_behavior():\n"
                "    counter['value'] = 0\n"
                "    client = app.test_client()\n"
                "    response = client.get('/')\n"
                "    assert b'Visual Smoke Test' in response.data\n"
                "    assert b'Counter: 0' in response.data\n"
                "    assert b'Increase' in response.data\n"
                "    assert b'Reset' in response.data\n"
                "    response = client.get('/increase', follow_redirects=True)\n"
                "    assert b'Counter: 1' in response.data\n"
                "    response = client.get('/reset', follow_redirects=True)\n"
                "    assert b'Counter: 0' in response.data\n"
            ),
        },
        {
            "action": "write_file",
            "path": "RUN.md",
            "content": (
                "Install dependencies:\n\n"
                "pip install -r requirements.txt\n\n"
                "Run:\n\n"
                "python app/main.py\n\n"
                "Open:\n\n"
                "http://127.0.0.1:5000/\n"
            ),
        },
    ]

    result = StaticReviewerAgent().review(actions)

    assert result.approved is True
    assert result.findings == []
