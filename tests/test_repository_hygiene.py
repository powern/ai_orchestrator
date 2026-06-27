import subprocess
from pathlib import Path
from shutil import which


def test_no_generated_artifacts_are_tracked_by_git():
    git = which("git") or r"C:\Program Files\Git\cmd\git.exe"
    assert Path(git).exists() or which("git")
    repo_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [git, "-c", f"safe.directory={repo_root}", "ls-files"],
        capture_output=True,
        cwd=repo_root,
        text=True,
        check=True,
    )

    forbidden_fragments = (
        "__pycache__",
        ".pytest_cache",
        "studio/workspaces/",
    )
    forbidden_suffixes = (
        ".pyc",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".log",
    )

    tracked_generated = [
        path
        for path in result.stdout.splitlines()
        if any(fragment in path for fragment in forbidden_fragments)
        or path.endswith(forbidden_suffixes)
    ]

    assert tracked_generated == []
