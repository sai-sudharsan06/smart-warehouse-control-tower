import pytest

from warehouse import database
from warehouse.products import add_product, get_product, list_products, update_product


def add_sample_products():
    add_product("Hex Bolt M8", "Spare Part", "EA", 0.249, "Schmidt GmbH", 5)
    add_product("Pallet Wrap Film 500mm", "Packaging", "BOX", 18.90, "Verpackung Nord GmbH", 7)
    add_product("Steel Sheet 2mm", "Raw Material", "KG", 1.35, "Schmidt GmbH", 14)


def test_tests_use_temporary_database(test_db):
    assert database.DB_PATH.name == "test_warehouse.db"


def test_new_database_is_empty(test_db):
    assert list_products() == []


def test_added_products_are_listed_in_order(test_db):
    add_sample_products()
    products = list_products()
    assert [p["product_id"] for p in products] == [1, 2, 3]
    assert products[0]["unit_cost"] == 0.25  # rounded from 0.249


def test_duplicate_name_is_rejected(test_db):
    add_sample_products()
    with pytest.raises(ValueError, match="already exists"):
        add_product("HEX BOLT m8", "Spare Part", "EA", 1.00, "Other GmbH", 3)
    assert len(list_products()) == 3


def test_search_by_name_ignores_capitals(test_db):
    add_sample_products()
    results = list_products("pallet")
    assert [p["name"] for p in results] == ["Pallet Wrap Film 500mm"]


def test_search_by_supplier(test_db):
    add_sample_products()
    assert len(list_products("schmidt")) == 2


def test_search_by_product_id(test_db):
    add_sample_products()
    results = list_products("MAT-00003")
    assert [p["name"] for p in results] == ["Steel Sheet 2mm"]


def test_search_with_no_match_returns_empty_list(test_db):
    add_sample_products()
    assert list_products("forklift") == []


def test_blank_search_returns_everything(test_db):
    add_sample_products()
    assert len(list_products("   ")) == 3

    # ---- Editing products ----

def test_get_product_returns_one_product(test_db):
    add_sample_products()
    product = get_product(2)
    assert product["name"] == "Pallet Wrap Film 500mm"
    assert product["updated_at"] is None  # never edited yet


def test_get_product_missing_returns_none(test_db):
    assert get_product(999) is None


def test_update_changes_fields_and_records_time(test_db):
    add_sample_products()
    update_product(1, "Hex Bolt M8 Zinc", "Spare Part", "EA", 0.30, "Schmidt GmbH", 6)
    product = get_product(1)
    assert product["name"] == "Hex Bolt M8 Zinc"
    assert product["unit_cost"] == 0.30
    assert product["lead_time_days"] == 6
    assert product["updated_at"] is not None


def test_update_does_not_touch_other_products(test_db):
    add_sample_products()
    update_product(1, "Hex Bolt M8 Zinc", "Spare Part", "EA", 0.30, "Schmidt GmbH", 6)
    assert get_product(2)["name"] == "Pallet Wrap Film 500mm"
    assert get_product(2)["updated_at"] is None


def test_invalid_update_is_rejected_and_nothing_changes(test_db):
    add_sample_products()
    with pytest.raises(ValueError, match="Unit cost cannot be negative"):
        update_product(1, "Hex Bolt M8", "Spare Part", "EA", -1, "Schmidt GmbH", 5)
    assert get_product(1)["unit_cost"] == 0.25


def test_update_to_another_products_name_is_rejected(test_db):
    add_sample_products()
    with pytest.raises(ValueError, match="already exists"):
        update_product(1, "steel sheet 2MM", "Spare Part", "EA", 0.25, "Schmidt GmbH", 5)
    assert get_product(1)["name"] == "Hex Bolt M8"


def test_product_can_keep_its_own_name(test_db):
    add_sample_products()
    update_product(1, "HEX BOLT M8", "Spare Part", "EA", 0.25, "Schmidt GmbH", 5)
    assert get_product(1)["name"] == "HEX BOLT M8"


def test_update_missing_product_is_rejected(test_db):
    with pytest.raises(ValueError, match="MAT-00999 does not exist"):
        update_product(999, "Ghost Part", "Spare Part", "EA", 1.0, "Nobody GmbH", 1)