import sqlite3

import pytest

from warehouse import database


def run_sql(sql, params=()):
    """Run one SQL statement in its own transaction."""
    connection = database.get_connection()
    try:
        with connection:
            connection.execute(sql, params)
    finally:
        connection.close()


def add_zone_a():
    run_sql("INSERT INTO zones (zone_code, name, zone_type) "
            "VALUES ('A', 'Bulk storage', 'Storage')")


def add_bin(zone_id, bin_code, rack, level):
    run_sql("INSERT INTO storage_bins (zone_id, bin_code, rack, level) "
            "VALUES (?, ?, ?, ?)", (zone_id, bin_code, rack, level))


def test_zone_code_is_unique_ignoring_case(test_db):
    add_zone_a()
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        run_sql("INSERT INTO zones (zone_code, name, zone_type) "
                "VALUES ('a', 'Another zone', 'Storage')")


def test_bin_must_belong_to_an_existing_zone(test_db):
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        add_bin(999, "X-01-01", 1, 1)


def test_same_position_cannot_exist_twice_in_a_zone(test_db):
    add_zone_a()
    add_bin(1, "A-01-01", 1, 1)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        add_bin(1, "A-1-1", 1, 1)


def test_rack_and_level_must_be_in_range(test_db):
    add_zone_a()
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        add_bin(1, "A-00-01", 0, 1)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        add_bin(1, "A-01-100", 1, 100)