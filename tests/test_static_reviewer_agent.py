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
