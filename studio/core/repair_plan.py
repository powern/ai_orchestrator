import json
from dataclasses import dataclass, field
from typing import Any

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

    def to_dict(self) -> dict:
        return {
            "root_cause": self.root_cause,
            "primary_target": self.primary_target,
            "repair_targets": self.repair_targets,
            "secondary_targets": self.secondary_targets,
            "reason": self.reason,
            "test_modification_policy": self.test_modification_policy,
            "project_execution_contract": self.project_execution_contract,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


class RepairPlanner:
    def plan(
        self,
        analysis: FailureAnalysis,
        execution_contract: dict[str, Any] | None = None,
    ) -> RepairPlan:
        contract = execution_contract or analysis.execution_contract
        root_cause = analysis.root_cause or "unknown"
        repair_targets = []
        secondary_targets = []

        if analysis.root_cause:
            repair_targets.append(analysis.root_cause)

        for path in analysis.affected_files:
            if path.startswith("tests/"):
                if path not in secondary_targets:
                    secondary_targets.append(path)
            elif path not in repair_targets and not self._looks_missing_module_placeholder(path):
                repair_targets.append(path)

        primary_target = analysis.primary_target or self._primary_target(
            root_cause,
            repair_targets,
            secondary_targets,
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

        return RepairPlan(
            root_cause=root_cause,
            primary_target=primary_target,
            repair_targets=repair_targets,
            secondary_targets=secondary_targets,
            reason=analysis.reason,
            project_execution_contract=contract,
        )

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
