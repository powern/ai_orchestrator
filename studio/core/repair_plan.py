import json
from dataclasses import dataclass, field
from typing import Any

from studio.contracts.validation_report import ValidationReport
from studio.core.failure_analysis import FailureAnalysis


@dataclass(frozen=True)
class RepairPlan:
    root_cause: str
    primary_target: str | None = None
    repair_targets: list[str] = field(default_factory=list)
    secondary_targets: list[str] = field(default_factory=list)
    reason: str = ""
    test_modification_policy: str = (
        "Modify tests only when the tests are wrong, requirements changed, "
        "or production-code repair cannot address the failure."
    )
    project_execution_contract: dict[str, Any] = field(default_factory=dict)
    validation_report: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "root_cause": self.root_cause,
            "primary_target": self.primary_target,
            "repair_targets": self.repair_targets,
            "secondary_targets": self.secondary_targets,
            "reason": self.reason,
            "test_modification_policy": self.test_modification_policy,
            "project_execution_contract": self.project_execution_contract,
            "validation_report": self.validation_report,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


class RepairPlanner:
    def plan(
        self,
        analysis: FailureAnalysis,
        execution_contract: dict[str, Any] | None = None,
        validation_report: dict[str, Any] | ValidationReport | str | None = None,
    ) -> RepairPlan:
        contract = execution_contract or analysis.execution_contract
        report = self._validation_report(validation_report)
        diagnosis = self._actionable_diagnosis(analysis.verified_diagnosis or {}, analysis)
        root_cause = analysis.root_cause or "unknown"
        repair_targets = []
        secondary_targets = []

        if report:
            for violation in report.violations:
                for target in violation.affected_files:
                    if target.startswith("tests/"):
                        if target not in secondary_targets:
                            secondary_targets.append(target)
                    elif target and target not in repair_targets:
                        repair_targets.append(target)
                if violation.location and not violation.location.startswith("tests/"):
                    if violation.location not in repair_targets:
                        repair_targets.append(violation.location)
            primary_violation = self._primary_validation_violation(report)
            if primary_violation:
                root_cause = primary_violation.message or root_cause

        if diagnosis:
            if diagnosis.get("confidence", 1.0) >= 0.55:
                root_cause = diagnosis.get("root_cause") or root_cause
            for target in diagnosis.get("repair_targets") or []:
                if target.startswith("tests/"):
                    if target not in secondary_targets:
                        secondary_targets.append(target)
                elif target not in repair_targets:
                    repair_targets.append(target)

        if analysis.root_cause and analysis.root_cause not in repair_targets:
            repair_targets.append(analysis.root_cause)

        for path in analysis.affected_files:
            if path.startswith("tests/"):
                if path not in secondary_targets:
                    secondary_targets.append(path)
            elif path not in repair_targets and not self._looks_missing_module_placeholder(path):
                repair_targets.append(path)

        primary_target = (
            diagnosis.get("primary_target")
            or analysis.primary_target
            or self._primary_target(
                root_cause,
                repair_targets,
                secondary_targets,
            )
        )

        if (
            primary_target
            and primary_target not in repair_targets
            and primary_target.startswith("app/")
        ):
            repair_targets.insert(0, primary_target)

        if analysis.failure_class == "InvalidExecutionContract":
            contract_targets = self._contract_targets(contract)
            for target in contract_targets:
                if target not in repair_targets:
                    repair_targets.append(target)

        if diagnosis and diagnosis.get("confidence", 1.0) < 0.55:
            for target in analysis.affected_files:
                if target.startswith("tests/"):
                    if target not in secondary_targets:
                        secondary_targets.append(target)
                elif (
                    target not in repair_targets
                    and not self._looks_missing_module_placeholder(target)
                ):
                    repair_targets.append(target)

        return RepairPlan(
            root_cause=root_cause,
            primary_target=primary_target,
            repair_targets=repair_targets,
            secondary_targets=secondary_targets,
            reason=(
                diagnosis.get("reason")
                if diagnosis.get("confidence", 1.0) >= 0.55
                else analysis.reason
            ),
            project_execution_contract=contract,
            validation_report=report.to_dict() if report else {},
        )

    def _validation_report(
        self,
        value: dict[str, Any] | ValidationReport | str | None,
    ) -> ValidationReport | None:
        if value is None or value == "":
            return None
        if isinstance(value, ValidationReport):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except (TypeError, json.JSONDecodeError):
                return None
            value = parsed
        if isinstance(value, dict):
            return ValidationReport.from_dict(value)
        return None

    def _primary_validation_violation(self, report: ValidationReport):
        severity_rank = {"critical": 0, "major": 1, "minor": 2}
        actionable = [item for item in report.violations if item.affected_files or item.location]
        if not actionable:
            return None
        return sorted(actionable, key=lambda item: severity_rank.get(item.severity, 1))[0]

    def _looks_missing_module_placeholder(self, path: str) -> bool:
        return not (path.startswith("app/") or path.startswith("tests/"))

    def _primary_target(
        self,
        root_cause: str,
        repair_targets: list[str],
        secondary_targets: list[str],
    ) -> str | None:
        if root_cause and root_cause.startswith("app/"):
            return root_cause

        for path in repair_targets:
            if path.startswith("app/"):
                return path

        if root_cause != "unknown":
            return root_cause

        return secondary_targets[0] if secondary_targets else None

    def _contract_targets(self, contract: dict[str, Any]) -> list[str]:
        targets = []
        module = contract.get("module_strategy") or {}
        import_root = module.get("import_root")
        if import_root and "-" in import_root:
            root_path = import_root.replace(".", "/").split("/", 1)[0]
            targets.append(root_path)
        run_command = (contract.get("run") or {}).get("command")
        if run_command:
            parts = [part.strip("'\"") for part in run_command.split()]
            targets.extend(part for part in parts if part.endswith(".py"))
        return targets

    def _actionable_diagnosis(
        self,
        diagnosis: dict[str, Any],
        analysis: FailureAnalysis,
    ) -> dict[str, Any]:
        if diagnosis.get("diagnosis_id") == "production-export-mismatch":
            return diagnosis
        if diagnosis.get("confidence", 1.0) < 0.55 and analysis.failure_class == "UnknownFailure":
            return diagnosis
        return {}
