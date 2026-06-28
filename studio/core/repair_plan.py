import json
from dataclasses import dataclass, field

from studio.core.failure_analysis import FailureAnalysis


@dataclass(frozen=True)
class RepairPlan:
    root_cause: str
    repair_targets: list[str] = field(default_factory=list)
    secondary_targets: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "root_cause": self.root_cause,
            "repair_targets": self.repair_targets,
            "secondary_targets": self.secondary_targets,
            "reason": self.reason,
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

        return RepairPlan(
            root_cause=root_cause,
            repair_targets=repair_targets,
            secondary_targets=secondary_targets,
            reason=analysis.reason,
        )

    def _looks_missing_module_placeholder(self, path: str) -> bool:
        return not (path.startswith("app/") or path.startswith("tests/"))
