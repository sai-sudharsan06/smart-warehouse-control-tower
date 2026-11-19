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
MAX_RACK = 99
MAX_LEVEL = 99


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


def format_bin_code(zone_code, rack, level):
    """Build a bin code such as A-01-02 from zone A, rack 1, level 2."""
    return f"{zone_code}-{rack:02d}-{level:02d}"


def validate_bin(rack, level):
    """Check a bin position. Return a list of error messages (empty = valid)."""
    errors = []
    if not 1 <= rack <= MAX_RACK:
        errors.append(f"Rack must be between 1 and {MAX_RACK}.")
    if not 1 <= level <= MAX_LEVEL:
        errors.append(f"Level must be between 1 and {MAX_LEVEL}.")
    return errors


def add_bin(zone_id, rack, level):
    """Validate and save a new storage bin. Return its generated bin code."""
    errors = validate_bin(rack, level)
    if errors:
        raise ValueError(" ".join(errors))

    connection = get_connection()
    try:
        with connection:
            zone = connection.execute(
                "SELECT zone_code FROM zones WHERE zone_id = ?",
                (zone_id,),
            ).fetchone()
            if zone is None:
                raise ValueError("The selected zone does not exist.")

            bin_code = format_bin_code(zone["zone_code"], rack, level)
            connection.execute(
                """
                INSERT INTO storage_bins (zone_id, bin_code, rack, level)
                VALUES (?, ?, ?, ?)
                """,
                (zone_id, bin_code, rack, level),
            )
        return bin_code
    except sqlite3.IntegrityError as error:
        if "UNIQUE" in str(error):
            raise ValueError(f"Bin {bin_code} already exists.")
        raise
    finally:
        connection.close()


def list_bins():
    """Return all storage bins with their zone code and type, sorted by bin code."""
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT b.bin_id, b.bin_code, z.zone_code, z.zone_type,
                   b.rack, b.level, b.is_blocked, b.created_at
            FROM storage_bins AS b
            JOIN zones AS z ON z.zone_id = b.zone_id
            ORDER BY b.bin_code
            """
        ).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]

MAX_BINS_PER_BULK = 500


def add_bins_bulk(zone_id, rack_from, rack_to, level_from, level_to):
    """Create every bin in a rack and level range in one transaction.

    Either all bins are created or none (for example if one already exists).
    Return the list of generated bin codes.
    """
    errors = validate_bin(rack_from, level_from) + validate_bin(rack_to, level_to)
    if rack_from > rack_to:
        errors.append("'Rack from' must not be greater than 'rack to'.")
    if level_from > level_to:
        errors.append("'Level from' must not be greater than 'level to'.")
    if errors:
        raise ValueError(" ".join(errors))

    count = (rack_to - rack_from + 1) * (level_to - level_from + 1)
    if count > MAX_BINS_PER_BULK:
        raise ValueError(
            f"That would create {count} bins. The limit is {MAX_BINS_PER_BULK} at once."
        )

    connection = get_connection()
    try:
        with connection:
            zone = connection.execute(
                "SELECT zone_code FROM zones WHERE zone_id = ?", (zone_id,)
            ).fetchone()
            if zone is None:
                raise ValueError("The selected zone does not exist.")

            codes = []
            for rack in range(rack_from, rack_to + 1):
                for level in range(level_from, level_to + 1):
                    bin_code = format_bin_code(zone["zone_code"], rack, level)
                    connection.execute(
                        """
                        INSERT INTO storage_bins (zone_id, bin_code, rack, level)
                        VALUES (?, ?, ?, ?)
                        """,
                        (zone_id, bin_code, rack, level),
                    )
                    codes.append(bin_code)
        return codes
    except sqlite3.IntegrityError as error:
        if "UNIQUE" in str(error):
            raise ValueError(
                f"Bin {bin_code} already exists. No bins were created."
            )
        raise
    finally:
        connection.close()
