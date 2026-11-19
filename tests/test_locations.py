import pytest

from warehouse.locations import (
    add_bin,
    add_bins_bulk,
    add_zone,
    format_bin_code,
    list_bins,
    list_zones,
    validate_bin,
    validate_zone,
)


# ---- Zone validation (no database needed) ----

def test_valid_zone_has_no_errors():
    assert validate_zone("A", "Bulk storage", "Storage") == []


@pytest.mark.parametrize("bad_code", ["", "   ", "A1", "A-B", "ABCD", "Ä"])
def test_bad_zone_codes_are_rejected(bad_code):
    assert len(validate_zone(bad_code, "Bulk storage", "Storage")) == 1


def test_unknown_zone_type_is_rejected():
    errors = validate_zone("A", "Bulk storage", "Garage")
    assert errors == [
        "Zone type must be one of: Receiving, Storage, Picking, "
        "Shipping, Quarantine, Damaged."
    ]


# ---- Saving zones ----

def test_add_zone_cleans_and_uppercases(test_db):
    add_zone(" b ", "  Picking   area ", "Picking")
    zone = list_zones()[0]
    assert zone["zone_code"] == "B"
    assert zone["name"] == "Picking area"


def test_duplicate_zone_code_is_rejected_ignoring_case(test_db):
    add_zone("A", "Bulk storage", "Storage")
    with pytest.raises(ValueError, match="Zone A already exists"):
        add_zone("a", "Another zone", "Storage")
    assert len(list_zones()) == 1


def test_invalid_zone_is_not_saved(test_db):
    with pytest.raises(ValueError, match="Zone name is required"):
        add_zone("Q", "", "Quarantine")
    assert list_zones() == []


def test_zones_are_listed_by_code(test_db):
    add_zone("C", "Shipping dock", "Shipping")
    add_zone("A", "Bulk storage", "Storage")
    assert [z["zone_code"] for z in list_zones()] == ["A", "C"]


# ---- Bin codes and bin validation (no database needed) ----

def test_bin_code_uses_two_digits():
    assert format_bin_code("A", 1, 2) == "A-01-02"
    assert format_bin_code("BUL", 12, 3) == "BUL-12-03"


@pytest.mark.parametrize("rack, level", [(1, 1), (99, 99)])
def test_bin_limits_are_allowed(rack, level):
    assert validate_bin(rack, level) == []


@pytest.mark.parametrize("rack, level", [(0, 1), (100, 1), (1, 0), (1, 100)])
def test_bin_outside_limits_is_rejected(rack, level):
    assert len(validate_bin(rack, level)) == 1


# ---- Saving bins ----

def test_add_bin_generates_code_from_zone(test_db):
    zone_id = add_zone("A", "Bulk storage", "Storage")
    assert add_bin(zone_id, 1, 2) == "A-01-02"
    bin_row = list_bins()[0]
    assert bin_row["zone_code"] == "A"
    assert bin_row["zone_type"] == "Storage"
    assert bin_row["is_blocked"] == 0


def test_duplicate_bin_is_rejected(test_db):
    zone_id = add_zone("A", "Bulk storage", "Storage")
    add_bin(zone_id, 1, 2)
    with pytest.raises(ValueError, match="Bin A-01-02 already exists"):
        add_bin(zone_id, 1, 2)
    assert len(list_bins()) == 1


def test_bin_for_missing_zone_is_rejected(test_db):
    with pytest.raises(ValueError, match="zone does not exist"):
        add_bin(999, 1, 1)
    assert list_bins() == []


def test_same_position_is_allowed_in_different_zones(test_db):
    zone_a = add_zone("A", "Bulk storage", "Storage")
    zone_q = add_zone("Q", "Quarantine area", "Quarantine")
    assert add_bin(zone_a, 1, 1) == "A-01-01"
    assert add_bin(zone_q, 1, 1) == "Q-01-01"


def test_bins_are_listed_in_code_order(test_db):
    zone_id = add_zone("A", "Bulk storage", "Storage")
    add_bin(zone_id, 1, 10)
    add_bin(zone_id, 2, 1)
    add_bin(zone_id, 1, 2)
    codes = [b["bin_code"] for b in list_bins()]
    assert codes == ["A-01-02", "A-01-10", "A-02-01"]

# ---- Creating many bins at once ----

def test_bulk_creates_every_rack_and_level(test_db):
    zone_id = add_zone("A", "Bulk storage", "Storage")
    codes = add_bins_bulk(zone_id, 1, 2, 1, 3)
    assert codes == ["A-01-01", "A-01-02", "A-01-03", "A-02-01", "A-02-02", "A-02-03"]
    assert len(list_bins()) == 6


def test_bulk_is_all_or_nothing(test_db):
    zone_id = add_zone("A", "Bulk storage", "Storage")
    add_bin(zone_id, 2, 2)
    with pytest.raises(ValueError, match="A-02-02 already exists. No bins were created"):
        add_bins_bulk(zone_id, 1, 3, 1, 3)
    assert [b["bin_code"] for b in list_bins()] == ["A-02-02"]


def test_bulk_rejects_reversed_range(test_db):
    zone_id = add_zone("A", "Bulk storage", "Storage")
    with pytest.raises(ValueError, match="'Rack from' must not be greater"):
        add_bins_bulk(zone_id, 5, 1, 1, 1)


def test_bulk_has_a_size_limit(test_db):
    zone_id = add_zone("A", "Bulk storage", "Storage")
    with pytest.raises(ValueError, match="limit is 500"):
        add_bins_bulk(zone_id, 1, 99, 1, 99)
    assert list_bins() == []
