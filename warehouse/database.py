import sqlite3
from pathlib import Path

# Location of the database file: <project folder>/data/warehouse.db
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "warehouse.db"


def get_connection():
    """Open a connection to the SQLite database."""
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
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
        connection.execute("""
            CREATE TABLE IF NOT EXISTS product_changes (
                change_id  INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL REFERENCES products (product_id),
                field_name TEXT    NOT NULL,
                old_value  TEXT,
                new_value  TEXT,
                changed_by TEXT    NOT NULL,
                changed_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS zones (
                zone_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                zone_code  TEXT    NOT NULL UNIQUE COLLATE NOCASE,
                name       TEXT    NOT NULL,
                zone_type  TEXT    NOT NULL,
                created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS storage_bins (
                bin_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                zone_id    INTEGER NOT NULL REFERENCES zones (zone_id),
                bin_code   TEXT    NOT NULL UNIQUE COLLATE NOCASE,
                rack       INTEGER NOT NULL CHECK (rack BETWEEN 1 AND 99),
                level      INTEGER NOT NULL CHECK (level BETWEEN 1 AND 99),
                is_blocked INTEGER NOT NULL DEFAULT 0,
                created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (zone_id, rack, level)
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS stock (
                product_id INTEGER NOT NULL REFERENCES products (product_id),
                bin_id     INTEGER NOT NULL REFERENCES storage_bins (bin_id),
                quantity   REAL    NOT NULL CHECK (quantity > 0),
                PRIMARY KEY (product_id, bin_id)
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS stock_movements (
                movement_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                movement_type TEXT    NOT NULL,
                product_id    INTEGER NOT NULL REFERENCES products (product_id),
                from_bin_id   INTEGER REFERENCES storage_bins (bin_id),
                to_bin_id     INTEGER REFERENCES storage_bins (bin_id),
                quantity      REAL    NOT NULL CHECK (quantity > 0),
                reason        TEXT,
                reference     TEXT,
                created_by    TEXT    NOT NULL,
                created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK (from_bin_id IS NOT NULL OR to_bin_id IS NOT NULL)
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS goods_receipts (
                receipt_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id    INTEGER NOT NULL REFERENCES products (product_id),
                quantity      REAL    NOT NULL CHECK (quantity > 0),
                delivery_note TEXT    NOT NULL,
                to_bin_id     INTEGER NOT NULL REFERENCES storage_bins (bin_id),
                received_by   TEXT    NOT NULL,
                received_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
    connection.close()