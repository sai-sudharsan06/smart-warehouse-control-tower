import sqlite3

from warehouse.database import get_connection
from warehouse.products import clean_text

# Allowed zone types. Quarantine and Damaged stock will not count as available.
ZONE_TYPES = [
    "Receiving",
    "Storage",
    "Picking",
    "Shipping",
    "Quarantine",
    "Damaged",
]
MAX_ZONE_CODE_LENGTH = 3


def validate_zone(zone_code, name, zone_type):
    """Check zone data. Return a list of error messages (empty = valid)."""
    errors = []

    code = zone_code.strip()
    if not code:
        errors.append("Zone code is required.")
    elif not (code.isascii() and code.isalpha()):
        errors.append("Zone code must contain only the letters A-Z.")
    elif len(code) > MAX_ZONE_CODE_LENGTH:
        errors.append(f"Zone code must be at most {MAX_ZONE_CODE_LENGTH} letters.")

    if not name or not name.strip():
        errors.append("Zone name is required.")

    if zone_type not in ZONE_TYPES:
        errors.append(f"Zone type must be one of: {', '.join(ZONE_TYPES)}.")

    return errors


def add_zone(zone_code, name, zone_type):
    """Validate and save a new zone. Return its database ID."""
    errors = validate_zone(zone_code, name, zone_type)
    if errors:
        raise ValueError(" ".join(errors))

    code = zone_code.strip().upper()
    connection = get_connection()
    try:
        with connection:
            cursor = connection.execute(
                "INSERT INTO zones (zone_code, name, zone_type) VALUES (?, ?, ?)",
                (code, clean_text(name), zone_type),
            )
        return cursor.lastrowid
    except sqlite3.IntegrityError as error:
        if "UNIQUE" in str(error):
            raise ValueError(f"Zone {code} already exists.")
        raise
    finally:
        connection.close()


def list_zones():
    """Return all zones, sorted by zone code."""
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT zone_id, zone_code, name, zone_type, created_at
            FROM zones
            ORDER BY zone_code
            """
        ).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]