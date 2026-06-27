from dataclasses import dataclass


@dataclass
class StageTestResult:
    success: bool
    returncode: int
    stdout: str
    stderr: str

    @classmethod
    def from_executor_result(cls, result):
        return cls(
            success=result.get("returncode") == 0,
            returncode=result.get("returncode"),
            stdout=result.get("stdout", ""),
            stderr=result.get("stderr", ""),
        )

    def to_dict(self):
        return {
            "success": self.success,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }

    def __getitem__(self, key):
        return self.to_dict()[key]
