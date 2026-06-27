import compileall
from pathlib import Path

SOURCE_PATHS = (
    "agents",
    "core",
    "studio",
    "tests",
)

EXCLUDED_PARTS = {
    ".venv",
    "venv",
    "env",
    "fresh_clone_verify",
    "workspaces",
    "__pycache__",
}


def should_compile(path: Path) -> bool:
    return not any(part in EXCLUDED_PARTS for part in path.parts)


def main() -> int:
    ok = True

    for source_path in SOURCE_PATHS:
        root = Path(source_path)
        if not root.exists():
            continue

        for file_path in root.rglob("*.py"):
            if not should_compile(file_path):
                continue
            ok = compileall.compile_file(str(file_path), quiet=1) and ok

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
