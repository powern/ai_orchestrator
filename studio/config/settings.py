from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

STUDIO_DIR = BASE_DIR / "studio"
DATABASE_PATH = BASE_DIR / "studio.db"

PROJECTS_DIR = STUDIO_DIR / "projects"
WORKSPACES_DIR = STUDIO_DIR / "workspaces"
LOGS_DIR = STUDIO_DIR / "logs"

FLASK_HOST = "0.0.0.0"
FLASK_PORT = 8090

DEFAULT_MODELS = {
    "planner": "qwen2.5:7b",
    "architect": "qwen2.5:7b",
    "coder": "qwen2.5-coder:3b",
    "tester": "qwen2.5-coder:1.5b",
}

# Executor safety
EXECUTOR_ISOLATION = True

OLLAMA_GENERATE_TIMEOUT = 900
OLLAMA_NUM_PREDICT = 1200
OLLAMA_TEMPERATURE = 0.2

SCHEDULER_POLL_INTERVAL_SECONDS = 5
CODER_MAX_SANITIZE_ATTEMPTS = 2
CODER_MAX_OUTPUT_RETRIES = 3
FIX_MAX_SANITIZE_ATTEMPTS = 2

STAGE_PROGRESS = {
    "queued": 0,
    "planner": 10,
    "architect": 20,
    "coder": 35,
    "coder_failed": 35,
    "static_reviewer": 50,
    "fix_failed": 50,
    "executor": 65,
    "tester": 80,
    "reviewer": 90,
    "tester_completed": 100,
    "static_review_failed": 50,
    "tester_failed": 80,
    "pipeline_failed": 100,
    "cancelled": 100,
}
