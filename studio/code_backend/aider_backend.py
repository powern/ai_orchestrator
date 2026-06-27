import shutil


class AiderBackend:
    name = "aider"

    def is_available(self) -> bool:
        return shutil.which("aider") is not None

    def build_command(self, repo_path: str, task: str) -> list[str]:
        return [
            "aider",
            "--yes",
            "--message",
            task,
            repo_path,
        ]
