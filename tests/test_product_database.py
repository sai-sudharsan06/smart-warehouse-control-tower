import sqlite3

import pytest

from warehouse import database
from warehouse.products import (
    add_product,
    get_product,
    get_product_history,
    list_products,
    update_product,
)


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

def test_list_includes_last_changed_time(test_db):
    add_sample_products()
    assert "updated_at" in list_products()[0]


def test_get_product_returns_one_product(test_db):
    add_sample_products()
    product = get_product(2)
    assert product["name"] == "Pallet Wrap Film 500mm"
    assert product["updated_at"] is None  # never edited yet


def test_get_product_missing_returns_none(test_db):
    assert get_product(999) is None


def test_update_changes_fields_and_records_time(test_db):
    add_sample_products()
    changed = update_product(1, "Hex Bolt M8 Zinc", "Spare Part", "EA", 0.30,
                             "Schmidt GmbH", 6, "tester")
    product = get_product(1)
    assert changed == 3
    assert product["name"] == "Hex Bolt M8 Zinc"
    assert product["unit_cost"] == 0.30
    assert product["lead_time_days"] == 6
    assert product["updated_at"] is not None


def test_update_does_not_touch_other_products(test_db):
    add_sample_products()
    update_product(1, "Hex Bolt M8 Zinc", "Spare Part", "EA", 0.30,
                   "Schmidt GmbH", 6, "tester")
    assert get_product(2)["name"] == "Pallet Wrap Film 500mm"
    assert get_product(2)["updated_at"] is None


def test_invalid_update_is_rejected_and_nothing_changes(test_db):
    add_sample_products()
    with pytest.raises(ValueError, match="Unit cost cannot be negative"):
        update_product(1, "Hex Bolt M8", "Spare Part", "EA", -1,
                       "Schmidt GmbH", 5, "tester")
    assert get_product(1)["unit_cost"] == 0.25


def test_update_to_another_products_name_is_rejected(test_db):
    add_sample_products()
    with pytest.raises(ValueError, match="already exists"):
        update_product(1, "steel sheet 2MM", "Spare Part", "EA", 0.25,
                       "Schmidt GmbH", 5, "tester")
    assert get_product(1)["name"] == "Hex Bolt M8"


def test_product_can_keep_its_own_name(test_db):
    add_sample_products()
    update_product(1, "HEX BOLT M8", "Spare Part", "EA", 0.25,
                   "Schmidt GmbH", 5, "tester")
    assert get_product(1)["name"] == "HEX BOLT M8"


def test_update_missing_product_is_rejected(test_db):
    with pytest.raises(ValueError, match="MAT-00999 does not exist"):
        update_product(999, "Ghost Part", "Spare Part", "EA", 1.0,
                       "Nobody GmbH", 1, "tester")


# ---- Data cleaning ----

def test_repeated_spaces_are_removed(test_db):
    add_product("  Pallet   Wrap  Film ", "Packaging", "BOX", 1.0, " Nord  GmbH ", 1)
    product = get_product(1)
    assert product["name"] == "Pallet Wrap Film"
    assert product["supplier_name"] == "Nord GmbH"


def test_extra_spaces_do_not_bypass_duplicate_check(test_db):
    add_sample_products()
    with pytest.raises(ValueError, match="already exists"):
        add_product("Pallet  Wrap Film 500mm", "Packaging", "BOX", 1.0, "X GmbH", 1)


# ---- Change history ----

def test_each_changed_field_is_recorded(test_db):
    add_sample_products()
    update_product(2, "Pallet Wrap Film 500mm", "Packaging", "BOX", 19.50,
                   "Verpackung Nord GmbH", 10, "anna.meier")
    history = get_product_history(2)
    assert len(history) == 2
    changes = {h["field_name"]: (h["old_value"], h["new_value"]) for h in history}
    assert changes == {"unit_cost": ("18.9", "19.5"), "lead_time_days": ("7", "10")}
    assert all(h["changed_by"] == "anna.meier" for h in history)


def test_saving_without_changes_records_nothing(test_db):
    add_sample_products()
    changed = update_product(1, "Hex Bolt M8", "Spare Part", "EA", 0.25,
                             "Schmidt GmbH", 5, "tester")
    assert changed == 0
    assert get_product_history(1) == []
    assert get_product(1)["updated_at"] is None


def test_rejected_update_leaves_no_history(test_db):
    add_sample_products()
    with pytest.raises(ValueError):
        update_product(1, "Steel Sheet 2mm", "Spare Part", "EA", 0.99,
                       "Schmidt GmbH", 5, "tester")
    assert get_product_history(1) == []
    assert get_product(1)["unit_cost"] == 0.25


def test_user_is_required_for_changes(test_db):
    add_sample_products()
    with pytest.raises(ValueError, match="User name is required"):
        update_product(1, "Hex Bolt M8", "Spare Part", "EA", 0.30,
                       "Schmidt GmbH", 5, "   ")


def test_history_must_belong_to_a_real_product(test_db):
    connection = database.get_connection()
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        with connection:
            connection.execute(
                "INSERT INTO product_changes (product_id, field_name, changed_by) "
                "VALUES (999, 'name', 'tester')"
            )
    connection.close()