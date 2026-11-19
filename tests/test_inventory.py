import sqlite3

import pytest

from helpers import build_small_warehouse
from warehouse import database
from warehouse.inventory import (
    available_quantity,
    check_stock_against_ledger,
    list_movements,
    list_stock,
    stock_summary,
    transfer_stock,
)
from warehouse.receiving import (
    format_receipt_id,
    list_receipts,
    receive_goods,
    stock_waiting_for_putaway,
    suggest_putaway_bin,
)


@pytest.fixture
def wh(test_db):
    return build_small_warehouse()


def quantity_in(bin_id, product_id):
    rows = list_stock(product_id=product_id, bin_id=bin_id)
    return rows[0]["quantity"] if rows else 0


def block_bin(bin_id):
    connection = database.get_connection()
    with connection:
        connection.execute("UPDATE storage_bins SET is_blocked = 1 WHERE bin_id = ?", (bin_id,))
    connection.close()


# ---- Goods receipt ----

def test_receipt_books_stock_into_receiving_bin(wh):
    receipt_id = receive_goods(wh["bolt"], 500, "DN-1001", wh["R-01-01"], "anna.meier")
    assert format_receipt_id(receipt_id) == "GR-00001"
    assert quantity_in(wh["R-01-01"], wh["bolt"]) == 500
    movement = list_movements()[0]
    assert movement["movement_type"] == "GR"
    assert movement["reference"] == "GR-00001"
    assert movement["to_bin"] == "R-01-01" and movement["from_bin"] is None
    assert movement["created_by"] == "anna.meier"
    assert list_receipts()[0]["delivery_note"] == "DN-1001"


def test_receipt_into_storage_bin_is_rejected(wh):
    with pytest.raises(ValueError, match="only be received into"):
        receive_goods(wh["bolt"], 10, "DN-1", wh["A-01-01"], "anna.meier")
    assert list_stock() == [] and list_receipts() == [] and list_movements() == []


def test_damaged_delivery_can_go_straight_to_damaged_zone(wh):
    receive_goods(wh["film"], 3, "DN-2", wh["D-01-01"], "anna.meier")
    assert list_stock()[0]["status"] == "Blocked"
    assert available_quantity(wh["film"]) == 0


@pytest.mark.parametrize("quantity, note, user, message", [
    (0, "DN-1", "anna", "greater than zero"),
    (-5, "DN-1", "anna", "greater than zero"),
    (5, "  ", "anna", "Delivery note number is required"),
    (5, "DN-1", " ", "User name is required"),
])
def test_invalid_receipt_is_rejected(wh, quantity, note, user, message):
    with pytest.raises(ValueError, match=message):
        receive_goods(wh["bolt"], quantity, note, wh["R-01-01"], user)
    assert list_movements() == []


def test_receipt_for_unknown_product_is_rejected(wh):
    with pytest.raises(ValueError, match="product does not exist"):
        receive_goods(999, 5, "DN-1", wh["R-01-01"], "anna")
    assert list_receipts() == []


# ---- Transfers and putaway ----

def test_putaway_moves_stock_and_records_both_bins(wh):
    receive_goods(wh["bolt"], 500, "DN-1", wh["R-01-01"], "anna")
    transfer_stock(wh["bolt"], wh["R-01-01"], wh["A-01-01"], 200, "ben", "PUTAWAY")
    assert quantity_in(wh["R-01-01"], wh["bolt"]) == 300
    assert quantity_in(wh["A-01-01"], wh["bolt"]) == 200
    movement = list_movements()[0]
    assert (movement["from_bin"], movement["to_bin"]) == ("R-01-01", "A-01-01")


def test_moving_everything_leaves_no_empty_stock_row(wh):
    receive_goods(wh["bolt"], 50, "DN-1", wh["R-01-01"], "anna")
    transfer_stock(wh["bolt"], wh["R-01-01"], wh["A-01-01"], 50, "ben", "PUTAWAY")
    assert [r["bin_code"] for r in list_stock()] == ["A-01-01"]


def test_cannot_move_more_than_is_in_the_bin(wh):
    receive_goods(wh["bolt"], 50, "DN-1", wh["R-01-01"], "anna")
    with pytest.raises(ValueError, match="Only 50 in bin R-01-01; cannot move 51"):
        transfer_stock(wh["bolt"], wh["R-01-01"], wh["A-01-01"], 51, "ben")
    assert quantity_in(wh["R-01-01"], wh["bolt"]) == 50
    assert len(list_movements()) == 1  # only the receipt


def test_same_source_and_destination_is_rejected(wh):
    receive_goods(wh["bolt"], 50, "DN-1", wh["R-01-01"], "anna")
    with pytest.raises(ValueError, match="must be different"):
        transfer_stock(wh["bolt"], wh["R-01-01"], wh["R-01-01"], 5, "ben")


def test_blocked_bin_cannot_receive_stock(wh):
    receive_goods(wh["bolt"], 50, "DN-1", wh["R-01-01"], "anna")
    block_bin(wh["A-01-01"])
    with pytest.raises(ValueError, match="A-01-01 is blocked"):
        transfer_stock(wh["bolt"], wh["R-01-01"], wh["A-01-01"], 5, "ben")
    assert quantity_in(wh["R-01-01"], wh["bolt"]) == 50


def test_decimal_quantities_are_kept_exactly_to_3_places(wh):
    receive_goods(wh["film"], 0.1, "DN-1", wh["R-01-01"], "anna")
    receive_goods(wh["film"], 0.2, "DN-2", wh["R-01-01"], "anna")
    assert quantity_in(wh["R-01-01"], wh["film"]) == 0.3


# ---- Stock status and availability ----

def test_only_unrestricted_stock_is_available(wh):
    receive_goods(wh["bolt"], 100, "DN-1", wh["R-01-01"], "anna")
    transfer_stock(wh["bolt"], wh["R-01-01"], wh["A-01-01"], 60, "ben", "PUTAWAY")
    transfer_stock(wh["bolt"], wh["R-01-01"], wh["P-01-01"], 20, "ben", "PUTAWAY")
    transfer_stock(wh["bolt"], wh["R-01-01"], wh["Q-01-01"], 15, "ben")
    # 5 stay in receiving
    assert available_quantity(wh["bolt"]) == 80
    summary = stock_summary()[0]
    assert summary["Unrestricted"] == 80
    assert summary["Quality inspection"] == 15
    assert summary["In receiving"] == 5
    assert summary["total"] == 100
    assert summary["stock_value"] == 25.0


# ---- Ledger integrity ----

def test_stock_matches_ledger_after_many_movements(wh):
    receive_goods(wh["bolt"], 100, "DN-1", wh["R-01-01"], "anna")
    receive_goods(wh["film"], 7.5, "DN-2", wh["R-01-01"], "anna")
    transfer_stock(wh["bolt"], wh["R-01-01"], wh["A-01-01"], 100, "ben", "PUTAWAY")
    transfer_stock(wh["film"], wh["R-01-01"], wh["A-01-02"], 2.5, "ben", "PUTAWAY")
    transfer_stock(wh["bolt"], wh["A-01-01"], wh["P-01-01"], 30, "ben")
    assert check_stock_against_ledger() == []


def test_ledger_check_detects_stock_changed_outside_a_movement(wh):
    receive_goods(wh["bolt"], 100, "DN-1", wh["R-01-01"], "anna")
    connection = database.get_connection()
    with connection:  # simulate someone editing the stock table directly
        connection.execute("UPDATE stock SET quantity = 90")
    connection.close()
    mismatches = check_stock_against_ledger()
    assert len(mismatches) == 1
    assert mismatches[0]["ledger_quantity"] == 100
    assert mismatches[0]["stock_quantity"] == 90


def test_database_refuses_zero_or_negative_stock(wh):
    connection = database.get_connection()
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        with connection:
            connection.execute(
                "INSERT INTO stock (product_id, bin_id, quantity) VALUES (?, ?, -1)",
                (wh["bolt"], wh["A-01-01"]),
            )
    connection.close()


# ---- Putaway suggestion ----

def test_putaway_suggests_bin_that_already_holds_the_product(wh):
    receive_goods(wh["bolt"], 100, "DN-1", wh["R-01-01"], "anna")
    transfer_stock(wh["bolt"], wh["R-01-01"], wh["A-01-02"], 10, "ben", "PUTAWAY")
    suggestion = suggest_putaway_bin(wh["bolt"])
    assert suggestion["bin_code"] == "A-01-02"
    assert suggestion["rule"] == "Bin already holds this product"


def test_putaway_suggests_first_empty_storage_bin(wh):
    receive_goods(wh["bolt"], 100, "DN-1", wh["R-01-01"], "anna")
    transfer_stock(wh["bolt"], wh["R-01-01"], wh["A-01-01"], 10, "ben", "PUTAWAY")
    suggestion = suggest_putaway_bin(wh["film"])
    assert suggestion["bin_code"] == "A-01-02"
    assert suggestion["rule"] == "First empty storage bin"


def test_putaway_skips_blocked_bins_and_returns_none_when_full(wh):
    for code in ["A-01-01", "A-01-02", "P-01-01"]:
        block_bin(wh[code])
    assert suggest_putaway_bin(wh["bolt"]) is None


def test_waiting_for_putaway_lists_only_receiving_stock(wh):
    receive_goods(wh["bolt"], 100, "DN-1", wh["R-01-01"], "anna")
    receive_goods(wh["film"], 1, "DN-2", wh["Q-01-01"], "anna")
    assert [r["bin_code"] for r in stock_waiting_for_putaway()] == ["R-01-01"]
