from datetime import date

import pytest

from helpers import build_small_warehouse
from warehouse.inventory import transfer_stock
from warehouse.orders import (
    available_to_promise,
    cancel_order,
    check_order,
    create_order,
    format_order_id,
    get_order,
    get_order_lines,
    list_orders,
    release_order,
)
from warehouse.receiving import receive_goods

TODAY = date(2026, 11, 19)
NEXT_WEEK = date(2026, 11, 26)


@pytest.fixture
def wh(test_db):
    """100 bolts unrestricted in A-01-01, 30 more in quarantine, 5 films unrestricted."""
    ids = build_small_warehouse()
    receive_goods(ids["bolt"], 130, "DN-1", ids["R-01-01"], "anna")
    transfer_stock(ids["bolt"], ids["R-01-01"], ids["A-01-01"], 100, "anna", "PUTAWAY")
    transfer_stock(ids["bolt"], ids["R-01-01"], ids["Q-01-01"], 30, "anna")
    receive_goods(ids["film"], 5, "DN-2", ids["R-01-01"], "anna")
    transfer_stock(ids["film"], ids["R-01-01"], ids["A-01-02"], 5, "anna", "PUTAWAY")
    return ids


def new_order(wh, lines, priority="Normal", customer="Velo Werke GmbH", when=NEXT_WEEK):
    return create_order(customer, when, priority, lines, "sales.sam", today=TODAY)


# ---- Creating orders ----

def test_create_order_with_lines(wh):
    order_id = new_order(wh, [(wh["bolt"], 40), (wh["film"], 2)])
    assert format_order_id(order_id) == "SO-00001"
    assert get_order(order_id)["status"] == "Open"
    assert [(l["product_id"], l["quantity"]) for l in get_order_lines(order_id)] == [
        (wh["bolt"], 40), (wh["film"], 2)]


@pytest.mark.parametrize("customer, when, priority, lines, message", [
    ("", NEXT_WEEK, "Normal", [(1, 1)], "Customer name is required"),
    ("X GmbH", date(2026, 11, 18), "Normal", [(1, 1)], "cannot be in the past"),
    ("X GmbH", NEXT_WEEK, "Whenever", [(1, 1)], "Priority must be one of"),
    ("X GmbH", NEXT_WEEK, "Normal", [], "at least one line"),
    ("X GmbH", NEXT_WEEK, "Normal", [(1, 0)], "greater than zero"),
    ("X GmbH", NEXT_WEEK, "Normal", [(1, 1), (1, 2)], "only once per order"),
])
def test_invalid_orders_are_rejected(wh, customer, when, priority, lines, message):
    with pytest.raises(ValueError, match=message):
        create_order(customer, when, priority, lines, "sales.sam", today=TODAY)
    assert list_orders() == []


def test_order_for_unknown_product_saves_nothing(wh):
    with pytest.raises(ValueError, match="does not exist"):
        new_order(wh, [(wh["bolt"], 1), (999, 1)])
    assert list_orders() == []


def test_urgent_orders_are_listed_first(wh):
    new_order(wh, [(wh["bolt"], 1)], when=date(2026, 11, 20))
    urgent = new_order(wh, [(wh["bolt"], 1)], priority="Urgent", when=date(2026, 12, 15))
    assert list_orders()[0]["order_id"] == urgent


# ---- Availability to promise ----

def test_quarantined_stock_is_not_promised(wh):
    assert available_to_promise(wh["bolt"]) == 100  # not 130


def test_open_orders_do_not_reserve_but_released_ones_do(wh):
    first = new_order(wh, [(wh["bolt"], 70)])
    assert available_to_promise(wh["bolt"]) == 100
    release_order(first, "lead.lisa")
    assert available_to_promise(wh["bolt"]) == 30
    second = new_order(wh, [(wh["bolt"], 40)])
    assert check_order(second)[0]["shortage"] == 10


def test_release_reserves_stock_and_records_who(wh):
    order_id = new_order(wh, [(wh["bolt"], 100), (wh["film"], 5)])
    release_order(order_id, "lead.lisa")
    order = get_order(order_id)
    assert order["status"] == "Released"
    assert order["released_by"] == "lead.lisa"


def test_short_order_is_not_released_and_shortage_is_named(wh):
    order_id = new_order(wh, [(wh["bolt"], 10), (wh["film"], 8)])
    with pytest.raises(ValueError, match="Pallet Wrap Film: short 3 BOX"):
        release_order(order_id, "lead.lisa")
    assert get_order(order_id)["status"] == "Open"
    assert available_to_promise(wh["bolt"]) == 100  # bolt line was not reserved either


def test_released_order_cannot_be_released_again(wh):
    order_id = new_order(wh, [(wh["bolt"], 1)])
    release_order(order_id, "lead.lisa")
    with pytest.raises(ValueError, match="is Released, not Open"):
        release_order(order_id, "lead.lisa")


# ---- Cancelling ----

def test_cancelling_a_released_order_frees_its_stock(wh):
    order_id = new_order(wh, [(wh["bolt"], 60)])
    release_order(order_id, "lead.lisa")
    cancel_order(order_id, "lead.lisa", "Customer moved the order to next month")
    assert get_order(order_id)["status"] == "Cancelled"
    assert get_order(order_id)["cancel_reason"] == "Customer moved the order to next month"
    assert available_to_promise(wh["bolt"]) == 100


def test_cancel_needs_a_reason(wh):
    order_id = new_order(wh, [(wh["bolt"], 1)])
    with pytest.raises(ValueError, match="reason is required"):
        cancel_order(order_id, "lead.lisa", "  ")
    assert get_order(order_id)["status"] == "Open"


def test_cancelled_order_cannot_be_cancelled_again(wh):
    order_id = new_order(wh, [(wh["bolt"], 1)])
    cancel_order(order_id, "lead.lisa", "Duplicate order")
    with pytest.raises(ValueError, match="cannot be cancelled"):
        cancel_order(order_id, "lead.lisa", "again")
