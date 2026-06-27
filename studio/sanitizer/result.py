from dataclasses import dataclass

from studio.execution_model.program import ExecutorProgram


@dataclass
class SanitizerResult:
    actions: list
    raw_output: str
    attempts: int
    retried: bool
    validation_error: str | None = None

    @property
    def program(self):
        return ExecutorProgram.from_dicts(self.actions)
