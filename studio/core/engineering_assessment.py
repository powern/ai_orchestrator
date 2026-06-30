import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConfidenceAssessment:
    score: float
    reasons: list[str]
    evidence: dict[str, Any]

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "reasons": self.reasons,
            "evidence": self.evidence,
        }


class ConfidenceAssessor:
    def assess(self, run: dict, events: list[dict], observation: dict) -> ConfidenceAssessment:
        score = 0.0
        reasons: list[str] = []
        evidence = {
            "run_status": run.get("status"),
            "current_stage": run.get("current_stage"),
            "events": [event.get("event_type") for event in events],
            "has_tests": observation.get("tests", {}).get("count", 0) > 0,
            "has_run_metadata": bool(observation.get("run_metadata_files")),
            "project_graph_summary": observation.get("project_graph", {}).get("summary", {}),
            "project_specification": observation.get("project_state_summary", {}),
        }
        spec_summary = evidence["project_specification"]
        if spec_summary.get("specification_confidence", 0) > 0:
            reasons.append(
                "Project specification exists "
                f"({spec_summary.get('language')}/{spec_summary.get('framework')})."
            )

        event_types = set(evidence["events"])
        if (
            "static_review_completed" in event_types
            or "static_review_completed_after_fix" in event_types
        ):
            score += 0.15
            reasons.append("Static review completed.")
        if "static_review_failed" in event_types:
            reasons.append("Static review reported unresolved findings.")

        if "executor_completed" in event_types or run.get("executor_output"):
            score += 0.15
            reasons.append("Executor produced output.")

        tester_passed = run.get("status") == "completed" or "tester_completed" in event_types
        if tester_passed:
            score += 0.25
            reasons.append("Tester passed.")
        elif "tester_failed" in event_types or run.get("tester_output_after_fix"):
            reasons.append("Tester still has failing evidence.")

        readiness = self._parse_json(run.get("runtime_readiness"))
        evidence["runtime_readiness"] = readiness
        validation_report = self._parse_json(run.get("validation_report"))
        evidence["validation_report"] = validation_report
        if validation_report:
            summary = validation_report.get("summary") or {}
            critical = summary.get("critical", 0)
            major = summary.get("major", 0)
            minor = summary.get("minor", 0)
            if validation_report.get("approved") is True:
                score += 0.1
                reasons.append("Structured validation passed.")
            else:
                reasons.append(
                    "Structured validation has unresolved findings "
                    f"(critical={critical}, major={major}, minor={minor})."
                )
        if readiness:
            if readiness.get("manual_run_ready") is True:
                score += 0.25
                reasons.append("Runtime readiness passed.")
            else:
                reasons.append("Runtime readiness did not pass.")
        elif run.get("status") == "completed":
            reasons.append("Runtime readiness evidence is missing.")

        if evidence["has_run_metadata"]:
            score += 0.1
            reasons.append("Manual run metadata is present.")
        else:
            reasons.append("Manual run metadata is missing.")

        if evidence["has_tests"]:
            score += 0.1
            reasons.append("Workspace contains tests.")
        else:
            reasons.append("Workspace contains no detected tests.")

        if run.get("status") == "failed":
            score = min(score, 0.45)
            reasons.append("Run ended in failed status.")

        return ConfidenceAssessment(
            score=round(min(score, 1.0), 2),
            reasons=reasons,
            evidence=evidence,
        )

    def _parse_json(self, value: str | None) -> dict:
        if not value:
            return {}
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}


class EngineeringDecisionModel:
    def decide(
        self,
        confidence: ConfidenceAssessment,
        observation: dict,
        run: dict,
    ) -> dict:
        evidence = confidence.evidence
        readiness = evidence.get("runtime_readiness") or {}
        validation_report = evidence.get("validation_report") or {}
        validation_summary = validation_report.get("summary") or {}

        if run.get("status") == "completed" and confidence.score >= 0.85:
            objective = "No further engineering needed."
            target_area = "none"
            expected_validation = "Existing validation remains green."
            should_continue = False
        elif readiness and readiness.get("manual_run_ready") is not True:
            objective = "Repair runtime readiness issues before considering the project complete."
            target_area = "runtime_readiness"
            expected_validation = "Runtime readiness validation passes."
            should_continue = True
        elif validation_report and validation_report.get("approved") is not True:
            objective = "Repair structured validation report violations."
            target_area = "validation_report"
            expected_validation = (
                "Validation Report passes with zero critical violations; current summary: "
                f"{validation_summary}."
            )
            should_continue = True
        elif run.get("status") == "failed" or "tester_failed" in evidence.get("events", []):
            objective = "Analyze and repair the failing validation path."
            target_area = "validation"
            expected_validation = "Tester and runtime readiness stages pass."
            should_continue = True
        elif observation.get("tests", {}).get("count", 0) == 0:
            objective = "Add tests that validate the generated project behavior."
            target_area = "tests"
            expected_validation = "Behavioral tests exist and pass."
            should_continue = True
        elif self._has_uncovered_routes(observation):
            objective = "Improve behavior coverage for uncovered web routes."
            target_area = "tests"
            expected_validation = "Each detected route is validated by tests."
            should_continue = True
        elif not observation.get("run_metadata_files"):
            objective = "Add manual run metadata for the generated project."
            target_area = "documentation"
            expected_validation = "RUN.md or README.md documents install, test, and run commands."
            should_continue = True
        else:
            objective = "Review remaining validation evidence and harden the generated project."
            target_area = "general"
            expected_validation = "Static review, tests, and runtime readiness pass."
            should_continue = confidence.score < 0.9

        return {
            "next_objective": objective,
            "reason": "; ".join(confidence.reasons),
            "target_area": target_area,
            "expected_validation": expected_validation,
            "confidence_before": confidence.score,
            "should_continue": should_continue,
        }

    def _has_uncovered_routes(self, observation: dict) -> bool:
        summary = observation.get("project_graph", {}).get("summary", {})
        return summary.get("uncovered_routes", 0) > 0
