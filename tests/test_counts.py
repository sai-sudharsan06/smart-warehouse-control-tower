import pytest

from helpers import build_small_warehouse
from warehouse.counts import (
    decide_count,
    inventory_accuracy,
    investigation_hints,
    list_counts,
    needs_approval,
    record_count,
)
from warehouse.inventory import check_stock_against_ledger, list_movements, list_stock
from warehouse.receiving import receive_goods


@pytest.fixture
def wh(test_db):
    """Warehouse with 1000 bolts (0.25 EUR each) and 10 boxes of film (18.90) in storage."""
    ids = build_small_warehouse()
    receive_goods(ids["bolt"], 1000, "DN-1", ids["R-01-01"], "anna")
    receive_goods(ids["film"], 10, "DN-2", ids["R-01-01"], "anna")
    from warehouse.inventory import transfer_stock
    transfer_stock(ids["bolt"], ids["R-01-01"], ids["A-01-01"], 1000, "anna", "PUTAWAY")
    transfer_stock(ids["film"], ids["R-01-01"], ids["A-01-02"], 10, "anna", "PUTAWAY")
    return ids


def quantity(wh, product, bin_code):
    rows = list_stock(product_id=wh[product], bin_id=wh[bin_code])
    return rows[0]["quantity"] if rows else 0


# ---- Tolerance rule ----

@pytest.mark.parametrize("system, diff, value, expected", [
    (100, 0, 0, False),          # exact match
    (100, -5, -1.25, False),     # 5 % and small value: inside both limits
    (100, -6, -1.50, True),      # 6 %: outside the percent limit
    (1000, -40, -50.0, False),   # 4 %, exactly 50 EUR: inside
    (1000, -40, -50.01, True),   # over 50 EUR
    (0, 3, 0.75, True),          # stock found where the system had none
])
def test_needs_approval(system, diff, value, expected):
    assert needs_approval(system, diff, value) is expected


# ---- Recording counts ----

def test_exact_count_is_matched_and_changes_nothing(wh):
    count_id, status = record_count(wh["bolt"], wh["A-01-01"], 1000, "carl")
    assert status == "Matched"
    assert quantity(wh, "bolt", "A-01-01") == 1000
    assert list_counts()[0]["difference"] == 0


def test_small_difference_is_adjusted_automatically(wh):
    count_id, status = record_count(
        wh["bolt"], wh["A-01-01"], 990, "carl", "Counting error suspected")
    assert status == "Adjusted"
    assert quantity(wh, "bolt", "A-01-01") == 990
    movement = list_movements()[0]
    assert movement["movement_type"] == "ADJ_OUT"
    assert movement["quantity"] == 10
    assert movement["reference"] == "CNT-00001"
    assert movement["reason"] == "Counting error suspected"
    count = list_counts()[0]
    assert count["system_quantity"] == 1000 and count["counted_quantity"] == 990
    assert count["difference_value"] == -2.5
    assert check_stock_against_ledger() == []


def test_difference_needs_a_reason(wh):
    with pytest.raises(ValueError, match="Choose a reason"):
        record_count(wh["bolt"], wh["A-01-01"], 990, "carl")
    assert list_counts() == []


def test_large_difference_waits_for_approval(wh):
    count_id, status = record_count(
        wh["film"], wh["A-01-02"], 7, "carl", "Stock in wrong bin")
    assert status == "Pending approval"
    assert quantity(wh, "film", "A-01-02") == 10  # stock unchanged until approved
    assert list_counts()[0]["difference_value"] == -56.7


def test_found_stock_in_empty_bin_needs_approval(wh):
    _, status = record_count(wh["bolt"], wh["P-01-01"], 4, "carl", "Movement not posted")
    assert status == "Pending approval"


def test_negative_count_is_rejected(wh):
    with pytest.raises(ValueError, match="cannot be negative"):
        record_count(wh["bolt"], wh["A-01-01"], -1, "carl")


# ---- Approval (four-eyes principle) ----

def test_approval_posts_the_adjustment(wh):
    count_id, _ = record_count(wh["film"], wh["A-01-02"], 7, "carl", "Stock in wrong bin")
    decide_count(count_id, True, "dana.lead", "Recounted together, 7 confirmed")
    assert quantity(wh, "film", "A-01-02") == 7
    count = list_counts()[0]
    assert count["status"] == "Adjusted"
    assert count["decided_by"] == "dana.lead"
    assert check_stock_against_ledger() == []


def test_counter_cannot_approve_own_count(wh):
    count_id, _ = record_count(wh["film"], wh["A-01-02"], 7, "carl", "Stock in wrong bin")
    with pytest.raises(ValueError, match="four-eyes"):
        decide_count(count_id, True, "Carl", "looks fine")
    assert quantity(wh, "film", "A-01-02") == 10


def test_rejection_changes_no_stock(wh):
    count_id, _ = record_count(wh["film"], wh["A-01-02"], 7, "carl", "Stock in wrong bin")
    decide_count(count_id, False, "dana.lead", "Found 3 boxes in A-01-01, recount")
    assert quantity(wh, "film", "A-01-02") == 10
    assert list_counts()[0]["status"] == "Rejected"


def test_decision_needs_a_note(wh):
    count_id, _ = record_count(wh["film"], wh["A-01-02"], 7, "carl", "Stock in wrong bin")
    with pytest.raises(ValueError, match="note"):
        decide_count(count_id, True, "dana.lead", " ")


def test_count_cannot_be_decided_twice(wh):
    count_id, _ = record_count(wh["film"], wh["A-01-02"], 7, "carl", "Stock in wrong bin")
    decide_count(count_id, False, "dana.lead", "Recount")
    with pytest.raises(ValueError, match="not pending"):
        decide_count(count_id, True, "dana.lead", "Changed my mind")


def test_approval_refused_if_stock_moved_since_count(wh):
    from warehouse.inventory import transfer_stock
    count_id, _ = record_count(wh["film"], wh["A-01-02"], 7, "carl", "Stock in wrong bin")
    transfer_stock(wh["film"], wh["A-01-02"], wh["A-01-01"], 1, "ben")
    with pytest.raises(ValueError, match="changed since the count"):
        decide_count(count_id, True, "dana.lead", "ok")
    assert quantity(wh, "film", "A-01-02") == 9


# ---- Accuracy and investigation ----

def test_inventory_accuracy(wh):
    assert inventory_accuracy() == (None, 0)
    record_count(wh["bolt"], wh["A-01-01"], 1000, "carl")                       # matched
    record_count(wh["bolt"], wh["A-01-01"], 995, "carl", "Counting error suspected")  # in tolerance
    record_count(wh["film"], wh["A-01-02"], 7, "carl", "Stock in wrong bin")    # outside
    record_count(wh["film"], wh["A-01-02"], 10, "carl")                         # matched
    assert inventory_accuracy() == (75.0, 4)


def test_hints_point_to_other_bins_and_never_to_people(wh):
    from warehouse.inventory import transfer_stock
    transfer_stock(wh["film"], wh["A-01-02"], wh["A-01-01"], 3, "ben")
    count_id, _ = record_count(wh["film"], wh["A-01-02"], 4, "carl", "Stock in wrong bin")
    hints = " ".join(investigation_hints(count_id))
    assert "A-01-01 (3)" in hints
    for name in ["anna", "ben", "carl"]:
        assert name not in hints
