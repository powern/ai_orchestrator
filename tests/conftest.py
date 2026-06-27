import os
from pathlib import Path


def pytest_configure(config):
    test_db = Path("/tmp/ai_studio_test.db")
    test_db.unlink(missing_ok=True)
    os.environ["AI_STUDIO_DB_PATH"] = str(test_db)

    from studio.database.db import get_database_path

    Path(get_database_path()).unlink(missing_ok=True)
