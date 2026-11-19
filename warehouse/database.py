import os
import sqlite3
from pathlib import Path

# Location of the database file: <project folder>/data/warehouse.db, unless the
# environment variable WAREHOUSE_DB names another file (used for the demo data).
PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("WAREHOUSE_DB") or PROJECT_DIR / "data" / "warehouse.db")
if not DB_PATH.is_absolute():
    DB_PATH = PROJECT_DIR / DB_PATH


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
        connection.execute("""
            CREATE TABLE IF NOT EXISTS stock_counts (
                count_id          INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id        INTEGER NOT NULL REFERENCES products (product_id),
                bin_id            INTEGER NOT NULL REFERENCES storage_bins (bin_id),
                system_quantity   REAL    NOT NULL CHECK (system_quantity >= 0),
                counted_quantity  REAL    NOT NULL CHECK (counted_quantity >= 0),
                difference        REAL    NOT NULL,
                difference_value  REAL    NOT NULL,
                reason            TEXT,
                status            TEXT    NOT NULL CHECK (status IN
                                  ('Matched', 'Pending approval', 'Adjusted', 'Rejected')),
                counted_by        TEXT    NOT NULL,
                counted_at        TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                decided_by        TEXT,
                decided_at        TEXT,
                decision_note     TEXT,
                movement_id       INTEGER REFERENCES stock_movements (movement_id)
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS sales_orders (
                order_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name  TEXT    NOT NULL,
                requested_date TEXT    NOT NULL,
                priority       TEXT    NOT NULL CHECK (priority IN ('Normal', 'Urgent')),
                status         TEXT    NOT NULL DEFAULT 'Open' CHECK (status IN
                               ('Open', 'Released', 'Picked', 'Shipped', 'Cancelled')),
                created_by     TEXT    NOT NULL,
                created_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                released_by    TEXT,
                released_at    TEXT,
                closed_by      TEXT,
                closed_at      TEXT,
                cancel_reason  TEXT
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS sales_order_lines (
                line_id         INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id        INTEGER NOT NULL REFERENCES sales_orders (order_id),
                product_id      INTEGER NOT NULL REFERENCES products (product_id),
                quantity        REAL    NOT NULL CHECK (quantity > 0),
                picked_quantity REAL    NOT NULL DEFAULT 0 CHECK (picked_quantity >= 0),
                UNIQUE (order_id, product_id)
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS pick_tasks (
                task_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id    INTEGER NOT NULL REFERENCES sales_orders (order_id),
                line_id     INTEGER NOT NULL REFERENCES sales_order_lines (line_id),
                product_id  INTEGER NOT NULL REFERENCES products (product_id),
                bin_id      INTEGER NOT NULL REFERENCES storage_bins (bin_id),
                quantity    REAL    NOT NULL CHECK (quantity > 0),
                sequence    INTEGER NOT NULL,
                status      TEXT    NOT NULL DEFAULT 'Open' CHECK (status IN ('Open', 'Picked')),
                created_by  TEXT    NOT NULL,
                created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                picked_by   TEXT,
                picked_at   TEXT,
                movement_id INTEGER REFERENCES stock_movements (movement_id)
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS pick_routes (
                order_id          INTEGER PRIMARY KEY REFERENCES sales_orders (order_id),
                method            TEXT    NOT NULL,
                distance_m        REAL    NOT NULL,
                naive_distance_m  REAL    NOT NULL
            )
        """)
    connection.close()