import random
from datetime import date

import pytest

from helpers import build_small_warehouse
from warehouse.inventory import (
    available_quantity,
    check_stock_against_ledger,
    list_movements,
    list_stock,
    transfer_stock,
)
from warehouse.locations import add_bins_bulk, add_zone, find_bin, list_zones
from warehouse.orders import (
    available_to_promise,
    cancel_order,
    create_order,
    get_order,
    get_order_lines,
    release_order,
)
from warehouse.picking import (
    brute_force_sequence,
    confirm_picking,
    create_pick_list,
    get_pick_list,
    optimised_sequence,
    route_length,
    route_statistics,
    ship_order,
    walking_distance,
)
from warehouse.receiving import receive_goods

TODAY = date(2026, 11, 19)


# ---- Distance model ----

def test_walking_distance_same_aisle_and_other_aisle():
    assert walking_distance((6.0, 5.0), (6.0, 12.5)) == 7.5
    # front cross-aisle only: out of aisle 1 (5 m), along (6 m), into aisle 2 (10 m)
    assert walking_distance((6.0, 5.0), (12.0, 10.0)) == 21.0


def test_rear_cross_aisle_is_used_when_shorter():
    # aisles 27.5 m long; both points deep in their aisles: via the rear
    # (27.5-25) + (27.5-22.5) = 7.5 m plus 6 m along the cross-aisle
    assert walking_distance((6.0, 25.0), (12.0, 22.5), length=27.5) == 13.5
    # near the front, the front is still shorter
    assert walking_distance((6.0, 5.0), (12.0, 10.0), length=27.5) == 21.0


def test_route_length_is_a_round_trip_from_the_depot():
    assert route_length([(6.0, 5.0)]) == 22.0  # 11 m there, 11 m back


def test_bin_code_order_loses_when_entering_an_aisle_from_the_rear():
    # Stops A-09, B-02, B-09, C-02 (aisles at 6, 12, 18 m; racks 2.5 m; length 27.5 m)
    a09, b02, b09, c02 = (6.0, 22.5), (12.0, 5.0), (12.0, 22.5), (18.0, 5.0)
    # Bin-code order: 28.5 + 33.5 + 17.5 + 33.5 + 23 = 136 m
    assert route_length([a09, b02, b09, c02], 27.5) == 136.0
    # Better: A-09, rear to B-09, down to B-02, front to C-02:
    # 28.5 + 16 + 17.5 + 16 + 23 = 101 m
    assert route_length([a09, b09, b02, c02], 27.5) == 101.0
    points = [a09, b02, b09, c02]
    assert route_length([points[i] for i in optimised_sequence(points, 27.5)], 27.5) == 101.0


@pytest.mark.parametrize("seed", range(5))
def test_or_tools_finds_the_shortest_route_on_small_cases(seed):
    rng = random.Random(seed)
    points = [(rng.choice([6.0, 12.0, 18.0]), rng.randint(1, 10) * 2.5) for _ in range(6)]
    best = route_length([points[i] for i in brute_force_sequence(points, 27.5)], 27.5)
    found = route_length([points[i] for i in optimised_sequence(points, 27.5)], 27.5)
    assert found == best


# ---- Pick list, picking and shipping ----

@pytest.fixture
def wh(test_db):
    """Three storage aisles (A, B, C) with racks 1-10, a shipping bin and 4 products."""
    ids = build_small_warehouse()
    for code in ["B", "C"]:
        add_bins_bulk(add_zone(code, f"Aisle {code}", "Storage"), 1, 10, 1, 1)
    zone_a = next(z["zone_id"] for z in list_zones() if z["zone_code"] == "A")
    add_bins_bulk(zone_a, 2, 10, 1, 1)  # racks 2-10 next to the helper's A-01-xx
    from warehouse.products import add_product
    ids["gear"] = add_product("Spur Gear Z32", "Semi-Finished Good", "EA", 4.10, "Gear AG", 10)
    ids["shaft"] = add_product("Drive Shaft 12mm", "Semi-Finished Good", "EA", 2.80, "Gear AG", 10)
    stock = [("bolt", "C-09-01", 50), ("film", "A-02-01", 10),
             ("gear", "B-10-01", 20), ("shaft", "A-09-01", 30), ("bolt", "A-01-01", 5)]
    for product, bin_code, qty in stock:
        receive_goods(ids[product], qty, "DN", ids["R-01-01"], "anna")
        transfer_stock(ids[product], ids["R-01-01"], find_bin(bin_code)["bin_id"],
                       qty, "anna", "PUTAWAY")
    return ids


def released_order(wh, lines):
    order_id = create_order("Velo Werke GmbH", date(2026, 11, 26), "Normal", lines,
                            "sales.sam", today=TODAY)
    release_order(order_id, "lead.lisa")
    return order_id


def test_pick_list_uses_largest_bin_first_and_splits_when_needed(wh):
    order_id = released_order(wh, [(wh["bolt"], 52)])
    create_pick_list(order_id, "pia")
    tasks, _ = get_pick_list(order_id)
    assert sorted((t["bin_code"], t["quantity"]) for t in tasks) == [
        ("A-01-01", 2), ("C-09-01", 50)]


def test_optimised_route_is_never_longer_than_bin_code_order(wh):
    order_id = released_order(
        wh, [(wh["bolt"], 50), (wh["film"], 1), (wh["gear"], 1), (wh["shaft"], 1)])
    result = create_pick_list(order_id, "pia")
    assert result["method"] == "OR-Tools route"
    assert result["distance_m"] <= result["naive_distance_m"]
    tasks, route = get_pick_list(order_id)
    assert [t["sequence"] for t in tasks] == [1, 2, 3, 4]
    assert route["distance_m"] == result["distance_m"]


def test_only_released_orders_get_a_pick_list(wh):
    order_id = create_order("Rad AG", date(2026, 11, 26), "Normal", [(wh["bolt"], 1)],
                            "sales.sam", today=TODAY)
    with pytest.raises(ValueError, match="only released orders"):
        create_pick_list(order_id, "pia")


def test_two_pick_lists_do_not_claim_the_same_stock(wh):
    first = released_order(wh, [(wh["gear"], 15)])
    second = released_order(wh, [(wh["gear"], 5)])
    create_pick_list(first, "pia")
    create_pick_list(second, "pia")
    planned = sum(t["quantity"] for o in (first, second) for t in get_pick_list(o)[0])
    assert planned == 20


def test_confirm_picking_moves_stock_to_shipping(wh):
    order_id = released_order(wh, [(wh["gear"], 5), (wh["shaft"], 10)])
    create_pick_list(order_id, "pia")
    confirm_picking(order_id, wh["S-01-01"], "pia")
    assert get_order(order_id)["status"] == "Picked"
    shipping = {r["product_id"]: r["quantity"] for r in list_stock(bin_id=wh["S-01-01"])}
    assert shipping == {wh["gear"]: 5, wh["shaft"]: 10}
    assert all(l["picked_quantity"] == l["quantity"] for l in get_order_lines(order_id))
    # Picked stock is no longer unrestricted, and no longer reserved
    assert available_quantity(wh["gear"]) == 15
    assert available_to_promise(wh["gear"]) == 15
    assert check_stock_against_ledger() == []


def test_picking_into_a_storage_bin_is_refused(wh):
    order_id = released_order(wh, [(wh["gear"], 5)])
    create_pick_list(order_id, "pia")
    with pytest.raises(ValueError, match="Shipping zone"):
        confirm_picking(order_id, wh["A-01-02"], "pia")
    assert get_order(order_id)["status"] == "Released"


def test_shipping_posts_goods_issue_and_closes_order(wh):
    order_id = released_order(wh, [(wh["gear"], 5)])
    create_pick_list(order_id, "pia")
    confirm_picking(order_id, wh["S-01-01"], "pia")
    ship_order(order_id, "otto")
    assert get_order(order_id)["status"] == "Shipped"
    assert list_stock(bin_id=wh["S-01-01"]) == []
    issue = list_movements()[0]
    assert issue["movement_type"] == "GI"
    assert issue["from_bin"] == "S-01-01" and issue["to_bin"] is None
    assert check_stock_against_ledger() == []


def test_cannot_ship_before_picking(wh):
    order_id = released_order(wh, [(wh["gear"], 5)])
    with pytest.raises(ValueError, match="must be Picked"):
        ship_order(order_id, "otto")


def test_cancel_removes_open_pick_list(wh):
    order_id = released_order(wh, [(wh["gear"], 5)])
    create_pick_list(order_id, "pia")
    cancel_order(order_id, "lead.lisa", "Customer cancelled")
    assert get_pick_list(order_id) == ([], None)


def test_route_statistics_sum_all_pick_lists(wh):
    for product in ["gear", "shaft"]:
        create_pick_list(released_order(wh, [(wh[product], 1), (wh["bolt"], 1)]), "pia")
    stats = route_statistics()
    assert stats["pick_lists"] == 2
    assert stats["distance_m"] <= stats["naive_distance_m"]
