import pytest

from warehouse.locations import add_zone, list_zones, validate_zone


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