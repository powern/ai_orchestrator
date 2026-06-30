from studio.contracts.execution import infer_execution_contract, validate_execution_contract
from studio.contracts.validation_report import build_validation_report, violation
from studio.core.agent import BaseAgent
from studio.core.project_state import ProjectStateBuilder
from studio.execution_model.program import ExecutorProgram
from studio.reviewer.result import ReviewerResult

FLASK_HELPERS = ("redirect", "url_for", "render_template_string")


class StaticReviewerAgent(BaseAgent):
    name = "static_reviewer"

    def process(self, actions: list, project_state=None) -> ReviewerResult:
        violations = []
        program = ExecutorProgram.from_dicts(actions)

        seen_paths = set()
        raw_actions = [executor_action.to_dict() for executor_action in program]
        planned_files = [
            action.get("path")
            for action in raw_actions
            if action.get("action") == "write_file" and action.get("path")
        ]

        for action in raw_actions:
            action_type = action.get("action")
            path = action.get("path")

            if path:
                if path.startswith("/"):
                    violations.append(
                        violation(
                            "absolute_path",
                            "critical",
                            "security",
                            f"Absolute path is not allowed: {path}",
                            location=path,
                            expected={"path": "relative workspace path"},
                            actual={"path": path},
                            repair_hint="Use a workspace-relative path.",
                            related_execution_contract="workspace isolation",
                        )
                    )

                if ".." in path.split("/"):
                    violations.append(
                        violation(
                            "path_traversal",
                            "critical",
                            "security",
                            f"Path traversal is not allowed: {path}",
                            location=path,
                            expected={"path": "inside workspace"},
                            actual={"path": path},
                            repair_hint="Remove parent-directory traversal from the action path.",
                            related_execution_contract="workspace isolation",
                        )
                    )

                if path in seen_paths:
                    violations.append(
                        violation(
                            "duplicate_path_action",
                            "major",
                            "executor_schema",
                            f"Duplicate path action: {path}",
                            location=path,
                            expected={"write_file": "one authoritative action per path"},
                            actual={"path": path, "duplicate": True},
                            repair_hint="Merge duplicate writes into one final write_file action.",
                            related_project_state="planned_files",
                        )
                    )

                seen_paths.add(path)

            if action_type == "write_file":
                content = action.get("content", "")

                if "Hello, World!" in content or "Hello, World!" in content.replace("\\'", "'"):
                    violations.append(
                        violation(
                            "placeholder_text",
                            "critical",
                            "static_analysis",
                            f"Placeholder text found in {path}",
                            location=path,
                            expected={"content": "task-specific implementation"},
                            actual={"placeholder": "Hello, World!"},
                            repair_hint="Replace placeholder content with requested behavior.",
                        )
                    )

                if "TODO" in content:
                    violations.append(
                        violation(
                            "todo_left_in_generated_file",
                            "major",
                            "static_analysis",
                            f"TODO found in {path}",
                            location=path,
                            expected={"content": "complete implementation"},
                            actual={"todo": True},
                            repair_hint="Complete or remove TODO-backed incomplete code.",
                        )
                    )

                if content.strip() == "pass":
                    violations.append(
                        violation(
                            "pass_only_file",
                            "major",
                            "static_analysis",
                            f"Suspicious pass-only file: {path}",
                            location=path,
                            expected={"content": "implementation or tests"},
                            actual={"content": "pass"},
                            repair_hint="Replace pass-only file with real implementation.",
                        )
                    )

                violations.extend(self._review_flask_file(path, content))

            if action_type == "run":
                command = action.get("command", "")

                dangerous = [
                    "rm -rf",
                    "curl ",
                    "wget ",
                    "sudo ",
                    "chmod 777",
                ]

                for item in dangerous:
                    if item in command:
                        violations.append(
                            violation(
                                "dangerous_command",
                                "critical",
                                "security",
                                f"Dangerous command found: {command}",
                                expected={"command": "safe project-local command"},
                                actual={"command": command, "dangerous_marker": item},
                                repair_hint="Remove destructive or network/system-level command.",
                                related_execution_contract="command safety",
                            )
                        )

        state = project_state or ProjectStateBuilder().build(executor_actions=raw_actions)
        state_payload = state.to_dict() if hasattr(state, "to_dict") else state
        violations.extend(self._review_project_specification(state_payload))
        execution_contract = state_payload.get("execution_contract") or infer_execution_contract(
            executor_actions=raw_actions,
        ).to_dict()
        for contract_violation in validate_execution_contract(
            execution_contract,
            planned_files=planned_files,
        ):
            if contract_violation.code in {
                "missing_source_root",
                "missing_test_root",
                "missing_python_import_root",
            }:
                continue
            if contract_violation.severity == "error":
                violations.append(
                    self._contract_violation_to_report_violation(contract_violation)
                )

        single_source_audit = self._audit_single_source_of_truth(state_payload)
        for audit_violation in single_source_audit.get("violations", []):
            violations.append(audit_violation)

        report = build_validation_report(
            violations,
            source="static_reviewer",
            single_source_of_truth={
                "status": "passed" if not single_source_audit["findings"] else "failed",
                "findings": [
                    item.message if hasattr(item, "message") else str(item)
                    for item in single_source_audit["findings"]
                ],
                "canonical_source_order": [
                    "ProjectSpecification",
                    "ExecutionContract",
                    "ProjectState",
                    "AgentContext",
                    "ValidationReport",
                ],
            },
        )
        findings = report.findings()

        return ReviewerResult(
            score=report.score,
            summary="Static action review completed.",
            findings=findings,
            approved=report.approved,
            validation_report=report,
        )

    def review(self, actions: list, project_state=None) -> ReviewerResult:
        return self.process(actions, project_state=project_state)

    def _review_flask_file(self, path: str | None, content: str) -> list:
        if not path or not path.endswith(".py") or not path.startswith("app"):
            return []

        violations = []
        uses_flask = "Flask(" in content or "@app.route" in content
        if not uses_flask:
            return violations

        if (
            "Flask(" in content
            and "from flask import" not in content
            and "import flask" not in content
        ):
            violations.append(
                violation(
                    "missing_flask_import",
                    "critical",
                    "imports",
                    f"Flask app uses Flask but does not import it in {path}",
                    location=path,
                    expected={"import": "Flask"},
                    actual={"imports_flask": False},
                    repair_hint="Import Flask from flask or use a valid flask module import.",
                    related_project_specification="framework",
                )
            )

        for helper in FLASK_HELPERS:
            if f"{helper}(" in content and not self._imports_flask_name(content, helper):
                violations.append(
                    violation(
                        f"missing_flask_helper_import_{helper}",
                        "critical",
                        "imports",
                        f"Flask helper {helper} used but not imported in {path}",
                        location=path,
                        expected={"from flask import": helper},
                        actual={"uses": helper, "imported": False},
                        repair_hint=f"Add {helper} to the from flask import line.",
                        related_project_specification="framework",
                    )
                )

        if "@app.route" in content and "app = Flask(" not in content:
            violations.append(
                violation(
                    "missing_flask_app_object",
                    "critical",
                    "routes",
                    f"Flask route exists but app object is not defined in {path}",
                    location=path,
                    expected={"app_object": "app = Flask(__name__)"},
                    actual={"route_decorator": True, "app_object": False},
                    repair_hint="Define and expose a Flask app object named app.",
                    related_execution_contract="run.entrypoint",
                )
            )

        if self._is_visual_flask_entrypoint(path, content):
            if "app.run(" not in content:
                violations.append(
                    violation(
                        "missing_entrypoint",
                        "critical",
                        "entrypoints",
                        f"Flask app is missing manual app.run entrypoint in {path}",
                        location=path,
                        expected={
                            "framework": "flask",
                            "entrypoint": "app.run(host=\"0.0.0.0\", port=5000)",
                        },
                        actual={"app_run": False},
                        contract_source="project_specification",
                        repair_hint="Add an if __name__ == \"__main__\" app.run block.",
                        related_project_specification="runtime",
                        related_execution_contract="run.command",
                    )
                )
            elif "host=\"0.0.0.0\"" not in content or "port=5000" not in content:
                violations.append(
                    violation(
                        "invalid_flask_entrypoint_binding",
                        "major",
                        "entrypoints",
                        f"Flask app.run should use host=\"0.0.0.0\" and port=5000 in {path}",
                        location=path,
                        expected={"host": "0.0.0.0", "port": 5000},
                        actual={"app_run": True},
                        repair_hint="Use app.run(host=\"0.0.0.0\", port=5000).",
                        related_execution_contract="run.host/run.port",
                    )
                )

        return violations

    def _review_project_specification(self, project_state: dict) -> list:
        specification = project_state.get("project_specification") or {}
        if specification.get("framework") != "flask":
            return []
        for item in (project_state.get("merged_files") or {}).get("files", []):
            if item.get("path") != "app/main.py":
                continue
            preview = item.get("content_preview", "")
            if "Flask(" not in preview and "@app.route" not in preview:
                return [
                    violation(
                        "project_specification_framework_mismatch",
                        "critical",
                        "project_specification",
                        "Project specification mismatch: app/main.py does not match "
                        "requested framework.",
                        location="app/main.py",
                        expected={"framework": "flask"},
                        actual={"contains_flask": False},
                        contract_source="project_specification",
                        repair_hint="Implement app/main.py as a Flask application.",
                        related_project_specification="framework",
                        related_project_state="merged_files",
                    )
                ]
        return []

    def _contract_violation_to_report_violation(self, contract_violation):
        category = "execution_contract"
        if "command" in contract_violation.code:
            category = "execution_contract"
        elif "import" in contract_violation.code:
            category = "imports"
        elif "path" in contract_violation.code or "root" in contract_violation.code:
            category = "project_structure"
        severity = "major" if contract_violation.severity == "warning" else "critical"
        return violation(
            contract_violation.code,
            severity,
            category,
            f"Execution contract violation: {contract_violation.message}",
            expected={"contract": "valid executable project contract"},
            actual={"code": contract_violation.code},
            contract_source="execution_contract",
            repair_hint="Update generated files so they satisfy the execution contract.",
            related_execution_contract=contract_violation.code,
        )

    def _audit_single_source_of_truth(self, project_state: dict) -> dict:
        findings = []
        violations = []
        specification = project_state.get("project_specification") or {}
        contract = project_state.get("execution_contract") or {}
        summary = project_state.get("summary") or {}
        graph_summary = (project_state.get("project_graph") or {}).get("summary") or {}

        checks = [
            (
                "language",
                specification.get("language"),
                contract.get("language"),
                "ProjectSpecification.language",
                "ExecutionContract.language",
            ),
            (
                "framework",
                specification.get("framework"),
                summary.get("framework"),
                "ProjectSpecification.framework",
                "ProjectState.summary.framework",
            ),
            (
                "project_type",
                specification.get("project_type"),
                summary.get("project_type"),
                "ProjectSpecification.project_type",
                "ProjectState.summary.project_type",
            ),
        ]

        for field, expected, actual, expected_source, actual_source in checks:
            if not expected or expected in {"unknown", "none"}:
                continue
            if actual in {None, "", "unknown", "none"}:
                continue
            if expected != actual:
                message = (
                    f"Single source of truth mismatch for {field}: "
                    f"{expected_source}={expected}, {actual_source}={actual}."
                )
                audit_violation = violation(
                    f"source_of_truth_mismatch_{field}",
                    "major",
                    "architecture",
                    message,
                    expected={expected_source: expected},
                    actual={actual_source: actual},
                    contract_source="project_specification",
                    repair_hint=(
                        "Derive downstream project metadata from ProjectSpecification "
                        "or document the intentional override."
                    ),
                    related_project_specification=field,
                    related_project_state=field,
                    confidence=0.9,
                )
                findings.append(audit_violation)
                violations.append(audit_violation)

        spec_framework = specification.get("framework")
        project_types = set(graph_summary.get("project_types") or [])
        if spec_framework and spec_framework not in {"unknown", "none"}:
            if project_types and spec_framework not in project_types:
                message = (
                    "Project graph project_types do not include canonical framework "
                    f"{spec_framework}."
                )
                audit_violation = violation(
                    "source_of_truth_mismatch_framework_project_types",
                    "minor",
                    "architecture",
                    message,
                    expected={"project_types": spec_framework},
                    actual={"project_types": sorted(project_types)},
                    contract_source="project_specification",
                    repair_hint=(
                        "Synchronize project graph classification with "
                        "ProjectSpecification."
                    ),
                    related_project_specification="framework",
                    related_project_state="project_graph.summary.project_types",
                    confidence=0.75,
                )
                findings.append(audit_violation)
                violations.append(audit_violation)

        return {"findings": findings, "violations": violations}

    def _imports_flask_name(self, content: str, name: str) -> bool:
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped.startswith("from flask import "):
                continue
            imported = stripped.removeprefix("from flask import ")
            names = {item.strip().split(" as ")[0] for item in imported.split(",")}
            if name in names:
                return True

        return False

    def _is_visual_flask_entrypoint(self, path: str, content: str) -> bool:
        return path in {"app/main.py", "app/app.py", "app.py"} and "@app.route" in content
