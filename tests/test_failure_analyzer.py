from pathlib import Path

from studio.core.failure_analysis import FailureAnalyzer
from studio.core.repair_plan import RepairPlanner
from studio.core.tester_result import StageTestResult


def write_file(root: Path, relative_path: str, content: str = "") -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_analyzer_identifies_main_as_root_cause_for_bad_package_import(tmp_path):
    write_file(
        tmp_path,
        "tests/test_calculator.py",
        "from app.main import main\n",
    )
    write_file(
        tmp_path,
        "app/main.py",
        "from application.calculator import Calculator\n",
    )
    write_file(
        tmp_path,
        "app/application/calculator.py",
        "class Calculator:\n    pass\n",
    )

    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="",
        stderr=(
            f'  File "{tmp_path / "tests" / "test_calculator.py"}", line 1, in <module>\n'
            "    from app.main import main\n"
            f'  File "{tmp_path / "app" / "main.py"}", line 1, in <module>\n'
            "    from application.calculator import Calculator\n"
            "ModuleNotFoundError: No module named 'application'\n"
        ),
    )

    analysis = FailureAnalyzer().analyze(tmp_path, tester_result)
    plan = RepairPlanner().plan(analysis)

    assert analysis.root_cause == "app/main.py"
    assert analysis.reason == "Invalid package import for missing module 'application'."
    assert plan.primary_target == "app/main.py"
    assert "app/main.py" in plan.repair_targets
    assert "tests/test_calculator.py" in plan.secondary_targets


def test_analyzer_prefers_flask_app_module_for_test_client_attribute_error(tmp_path):
    write_file(tmp_path, "app/__init__.py", "from . import app\n")
    write_file(tmp_path, "app/app.py", "def index():\n    return 'hello'\n")
    write_file(
        tmp_path,
        "tests/test_app.py",
        "from app import app\n\n"
        "def test_home():\n"
        "    with app.test_client() as client:\n"
        "        assert client.get('/').status_code == 200\n",
    )

    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="",
        stderr=(
            f'  File "{tmp_path / "tests" / "test_app.py"}", line 5, in test_home\n'
            "    with app.test_client() as client:\n"
            "AttributeError: module 'app.app' has no attribute 'test_client'\n"
        ),
    )

    analysis = FailureAnalyzer().analyze(tmp_path, tester_result)
    plan = RepairPlanner().plan(analysis)

    assert analysis.exception_type == "AttributeError"
    assert analysis.failure_class == "WrongObjectOrMissingAttribute"
    assert analysis.root_cause == "app/app.py"
    assert analysis.primary_target == "app/app.py"
    assert plan.primary_target == "app/app.py"
    assert "tests/test_app.py" in analysis.affected_files
    assert analysis.confidence >= 0.8
    assert "Flask app object" in analysis.reason


def test_analyzer_identifies_import_error_missing_export(tmp_path):
    write_file(
        tmp_path,
        "tests/test_analyzer.py",
        "from app.application.analyzer import analyze_temperatures\n",
    )
    write_file(tmp_path, "app/application/analyzer.py", "def other():\n    return []\n")

    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="",
        stderr=(
            f'  File "{tmp_path / "tests" / "test_analyzer.py"}", line 1, in <module>\n'
            "    from app.application.analyzer import analyze_temperatures\n"
            "ImportError: cannot import name 'analyze_temperatures' "
            "from 'app.application.analyzer'\n"
        ),
    )

    analysis = FailureAnalyzer().analyze(tmp_path, tester_result)
    plan = RepairPlanner().plan(analysis)

    assert analysis.exception_type == "ImportError"
    assert analysis.failure_class == "MissingExport"
    assert analysis.root_cause == "app/application/analyzer.py"
    assert analysis.primary_target == "app/application/analyzer.py"
    assert plan.primary_target == "app/application/analyzer.py"
    assert "Production module does not export" in analysis.reason


def test_analyzer_identifies_nested_import_origin(tmp_path):
    write_file(tmp_path, "tests/test_calculator.py", "from app.main import main\n")
    write_file(tmp_path, "app/main.py", "from app.application.calculator import Calculator\n")
    write_file(
        tmp_path,
        "app/application/calculator.py",
        "from domain.temperature import Temperature\n",
    )

    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="",
        stderr=(
            f'  File "{tmp_path / "tests" / "test_calculator.py"}", line 1, in <module>\n'
            "    from app.main import main\n"
            f'  File "{tmp_path / "app" / "main.py"}", line 1, in <module>\n'
            "    from app.application.calculator import Calculator\n"
            f'  File "{tmp_path / "app" / "application" / "calculator.py"}", '
            "line 1, in <module>\n"
            "    from domain.temperature import Temperature\n"
            "ModuleNotFoundError: No module named 'domain'\n"
        ),
    )

    analysis = FailureAnalyzer().analyze(tmp_path, tester_result)

    assert analysis.root_cause == "app/application/calculator.py"
    assert "app/application/calculator.py" in analysis.affected_files


def test_analyzer_points_to_imported_source_file_for_syntax_error(tmp_path):
    write_file(tmp_path, "tests/test_calculator.py", "from app.application.calculator import add\n")
    write_file(tmp_path, "app/application/calculator.py", "def add(a, b):\n    return a +\n")

    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="",
        stderr=(
            f'  File "{tmp_path / "tests" / "test_calculator.py"}", line 1, in <module>\n'
            "    from app.application.calculator import add\n"
            f'  File "{tmp_path / "app" / "application" / "calculator.py"}", line 2\n'
            "    return a +\n"
            "SyntaxError: invalid syntax\n"
        ),
    )

    analysis = FailureAnalyzer().analyze(tmp_path, tester_result)

    assert analysis.exception_type == "SyntaxError"
    assert analysis.failure_class == "SyntaxError"
    assert analysis.root_cause == "app/application/calculator.py"
    assert analysis.primary_target == "app/application/calculator.py"


def test_analyzer_identifies_missing_dependency_file(tmp_path):
    write_file(tmp_path, "tests/test_main.py", "from app.main import main\n")
    write_file(tmp_path, "app/main.py", "from app.missing_service import MissingService\n")

    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="",
        stderr=(
            f'  File "{tmp_path / "tests" / "test_main.py"}", line 1, in <module>\n'
            "    from app.main import main\n"
            f'  File "{tmp_path / "app" / "main.py"}", line 1, in <module>\n'
            "    from app.missing_service import MissingService\n"
            "ModuleNotFoundError: No module named 'app.missing_service'\n"
        ),
    )

    analysis = FailureAnalyzer().analyze(tmp_path, tester_result)
    plan = RepairPlanner().plan(analysis)

    assert analysis.root_cause == "app/main.py"
    assert "app/missing_service.py" in analysis.affected_files
    assert "Missing dependency file" in analysis.reason
    assert plan.primary_target == "app/main.py"
    assert "app/main.py" in plan.repair_targets


def test_analyzer_prefers_production_source_for_assertion_behavior_failure(tmp_path):
    write_file(
        tmp_path,
        "tests/test_calculator.py",
        "from app.calculator import add\n\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n",
    )
    write_file(tmp_path, "app/calculator.py", "def add(a, b):\n    return a - b\n")

    tester_result = StageTestResult(
        success=False,
        returncode=1,
        stdout="",
        stderr=(
            f'  File "{tmp_path / "tests" / "test_calculator.py"}", line 4, in test_add\n'
            "    assert add(2, 3) == 5\n"
            "AssertionError: assert -1 == 5\n"
        ),
    )

    analysis = FailureAnalyzer().analyze(tmp_path, tester_result)
    plan = RepairPlanner().plan(analysis)

    assert analysis.exception_type == "AssertionError"
    assert analysis.failure_class == "BehaviorMismatch"
    assert analysis.root_cause == "app/calculator.py"
    assert analysis.primary_target == "app/calculator.py"
    assert plan.primary_target == "app/calculator.py"
    assert "Production behavior" in analysis.reason
