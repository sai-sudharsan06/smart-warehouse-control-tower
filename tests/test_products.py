import pytest

from warehouse import database
from warehouse.products import add_product, list_products


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