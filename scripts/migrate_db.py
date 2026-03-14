"""
One-shot migration: add any columns present in the SQLAlchemy models
but missing from the live SQLite database.

Run from the repo root:
    backend/.venv/Scripts/python scripts/migrate_db.py
"""
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "backend" / "data" / "campaign.db"

# (table, column, sqlite_type, default)
MIGRATIONS = [
    ("avatars", "voice_embedding_path", "VARCHAR(500)", "NULL"),
]


def columns_for(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def main() -> None:
    if not DB_PATH.exists():
        print(f"[SKIP] No database found at {DB_PATH} — nothing to migrate.")
        sys.exit(0)

    conn = sqlite3.connect(DB_PATH)
    try:
        for table, col, col_type, default in MIGRATIONS:
            existing = columns_for(conn, table)
            if col in existing:
                print(f"[OK]   {table}.{col} already exists")
                continue
            sql = f"ALTER TABLE {table} ADD COLUMN {col} {col_type} DEFAULT {default}"
            conn.execute(sql)
            conn.commit()
            print(f"[ADD]  {table}.{col} {col_type}")
    finally:
        conn.close()

    print("Migration complete.")


if __name__ == "__main__":
    main()
