import json
from dataclasses import dataclass, field

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

    def to_dict(self) -> dict:
        return {
            "root_cause": self.root_cause,
            "primary_target": self.primary_target,
            "repair_targets": self.repair_targets,
            "secondary_targets": self.secondary_targets,
            "reason": self.reason,
            "test_modification_policy": self.test_modification_policy,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


class RepairPlanner:
    def plan(self, analysis: FailureAnalysis) -> RepairPlan:
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

        primary_target = self._primary_target(root_cause, repair_targets, secondary_targets)

        return RepairPlan(
            root_cause=root_cause,
            primary_target=primary_target,
            repair_targets=repair_targets,
            secondary_targets=secondary_targets,
            reason=analysis.reason,
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
