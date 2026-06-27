from studio.database.db import init_db, get_connection


def test_studio_database_tables_exist():
    init_db()

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()

    table_names = {row["name"] for row in rows}

    assert "projects" in table_names
    assert "runs" in table_names
