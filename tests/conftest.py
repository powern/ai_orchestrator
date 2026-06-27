import os
from pathlib import Path
from uuid import uuid4


def pytest_configure(config):
    test_db = Path(f"/tmp/ai_studio_test_{os.getpid()}_{uuid4().hex}.db")
    os.environ["AI_STUDIO_DB_PATH"] = str(test_db)

    from studio.database.db import get_database_path

    Path(get_database_path()).unlink(missing_ok=True)
