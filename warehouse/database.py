import sqlite3
from pathlib import Path

# Location of the database file: <project folder>/data/warehouse.db
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "warehouse.db"


def get_connection():
    """Open a connection to the SQLite database."""
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def create_tables():
    """Create the database tables if they do not exist yet."""
    connection = get_connection()
    with connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS products (
                product_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT    NOT NULL UNIQUE COLLATE NOCASE,
                category        TEXT    NOT NULL,
                unit_of_measure TEXT    NOT NULL,
                unit_cost       REAL    NOT NULL CHECK (unit_cost >= 0),
                supplier_name   TEXT    NOT NULL,
                lead_time_days  INTEGER NOT NULL CHECK (lead_time_days >= 0),
                is_active       INTEGER NOT NULL DEFAULT 1,
                created_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at      TEXT
            )
        """)
    connection.close()