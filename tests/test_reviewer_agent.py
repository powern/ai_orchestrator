from studio.reviewer.agent import ReviewerAgent
from studio.reviewer.result import ReviewerResult


def test_reviewer_returns_result(tmp_path):
    app_dir = tmp_path / "app"
    tests_dir = tmp_path / "tests"

    app_dir.mkdir()
    tests_dir.mkdir()

    (app_dir / "main.py").write_text(
        "def main():\n    return 'ok'\n",
        encoding="utf-8",
    )

    (tests_dir / "test_main.py").write_text(
        "from app.main import main\n\n" "def test_main():\n" "    assert main() == 'ok'\n",
        encoding="utf-8",
    )

    reviewer = ReviewerAgent()

    result = reviewer.review(str(tmp_path))

    assert isinstance(result, ReviewerResult)
    assert result.score == 100
    assert result.approved is True
    assert result.findings == []


def test_reviewer_finds_missing_files(tmp_path):
    reviewer = ReviewerAgent()

    result = reviewer.review(str(tmp_path))

    assert result.approved is False
    assert result.score < 100
    assert "Missing expected file: app/main.py" in result.findings
    assert "Missing expected file: tests/test_main.py" in result.findings


def test_reviewer_finds_placeholder_text(tmp_path):
    app_dir = tmp_path / "app"
    tests_dir = tmp_path / "tests"

    app_dir.mkdir()
    tests_dir.mkdir()

    (app_dir / "main.py").write_text(
        "def main():\n    print('Hello, World!')\n",
        encoding="utf-8",
    )

    (tests_dir / "test_main.py").write_text(
        "def test_main():\n" "    pass\n",
        encoding="utf-8",
    )

    reviewer = ReviewerAgent()

    result = reviewer.review(str(tmp_path))

    assert result.approved is False
    assert any("Placeholder text" in finding for finding in result.findings)
    assert any("pass statement" in finding for finding in result.findings)
