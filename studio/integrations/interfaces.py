from typing import Protocol

from studio.execution_model.program import ExecutorProgram


class PlanningBackend(Protocol):
    def plan(self, project_description: str) -> str:
        """Return a planner-readable implementation backlog."""


class CodingBackend(Protocol):
    def generate_actions(self, planner_output: str, architect_output: str) -> ExecutorProgram:
        """Return an executor program for the requested project."""


class ExecutionBackend(Protocol):
    def execute(self, workspace_path: str, program: ExecutorProgram) -> list[dict]:
        """Execute a normalized executor program in an isolated workspace."""


class GitBackend(Protocol):
    def create_change_set(self, workspace_path: str, message: str) -> str:
        """Create a versioned change set and return its identifier."""


class DeploymentBackend(Protocol):
    def deploy(self, workspace_path: str) -> str:
        """Deploy a generated project and return a deployment identifier."""
