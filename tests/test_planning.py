from datetime import date

import pytest

from helpers import build_small_warehouse
from warehouse import database
from warehouse.inventory import post_movement, transfer_stock
from warehouse.planning import (
    abc_classes,
    best_forecast,
    economic_order_quantity,
    exponential_smoothing_forecast,
    inventory_plan,
    mean_absolute_error,
    moving_average_forecast,
    reorder_point,
    safety_stock,
    weekly_demand,
    z_value,
)
from warehouse.receiving import receive_goods

# ---- Formulas, checked against hand calculations ----


def test_moving_average():
    fitted, nxt = moving_average_forecast([10, 20, 30, 40, 50], n=2)
    assert fitted == [None, None, 15, 25, 35]
    assert nxt == 45


def test_exponential_smoothing():
    fitted, nxt = exponential_smoothing_forecast([10, 20, 30], alpha=0.5)
    # level: 10 -> 0.5*10+0.5*10 = 10 -> 0.5*20+0.5*10 = 15 -> 0.5*30+0.5*15 = 22.5
    assert fitted == [None, 10, 15]
    assert nxt == 22.5


def test_mae_ignores_periods_without_forecast():
    assert mean_absolute_error([10, 20, 30], [None, 18, 33]) == 2.5


def test_best_forecast_picks_lower_error():
    steady_trend = [10, 12, 14, 16, 18, 20, 22, 24]
    result = best_forecast(steady_trend)
    assert result["mae"] == min(
        mean_absolute_error(steady_trend, moving_average_forecast(steady_trend, 4)[0]),
        mean_absolute_error(steady_trend, exponential_smoothing_forecast(steady_trend, 0.3)[0]))


def test_z_values():
    assert round(z_value(0.95), 3) == 1.645
    assert round(z_value(0.98), 3) == 2.054


def test_safety_stock_and_reorder_point():
    # z(95 %) = 1.645, sigma 20 per week, lead time 14 days = 2 weeks
    ss = safety_stock(0.95, 20, 14)
    assert ss == round(1.645 * 20 * 2 ** 0.5, 1) == 46.5
    assert reorder_point(100, 14, ss) == 246.5


def test_eoq():
    # sqrt(2 x 5200 x 50 / (0.25 x 4)) = sqrt(520000) = 721.1
    assert economic_order_quantity(5200, 4.0) == 721.1
    assert economic_order_quantity(0, 4.0) == 0


def test_abc_classes():
    values = {"a": 700, "b": 150, "c": 90, "d": 40, "e": 20, "f": 0}
    # cumulative before: a 0 %, b 70 %, c 85 %, d 94 %, e 98 %
    assert abc_classes(values) == {"a": "A", "b": "A", "c": "B", "d": "B", "e": "C", "f": "C"}


# ---- Demand history from goods issues ----

@pytest.fixture
def wh(test_db):
    ids = build_small_warehouse()
    receive_goods(ids["bolt"], 1000, "DN", ids["R-01-01"], "anna")
    transfer_stock(ids["bolt"], ids["R-01-01"], ids["A-01-01"], 1000, "anna", "PUTAWAY")
    return ids


def issue(wh, quantity, when):
    connection = database.get_connection()
    with connection:
        movement_id = post_movement(connection, "GI", wh["bolt"], quantity, "otto",
                                    from_bin_id=wh["A-01-01"])
        connection.execute("UPDATE stock_movements SET created_at = ? WHERE movement_id = ?",
                           (when, movement_id))
    connection.close()


def test_weekly_demand_buckets_issues_by_week(wh):
    today = date(2026, 11, 19)
    issue(wh, 10, "2026-11-18 09:00:00")  # 1 day ago   -> last week
    issue(wh, 5, "2026-11-13 09:00:00")   # 6 days ago  -> last week
    issue(wh, 7, "2026-11-11 09:00:00")   # 8 days ago  -> week before
    issue(wh, 99, "2025-01-01 09:00:00")  # too old, ignored
    series = weekly_demand(today, weeks=4)[wh["bolt"]]
    assert series == [0, 0, 7, 15]
    assert weekly_demand(today, weeks=4)[wh["film"]] == [0, 0, 0, 0]


def test_inventory_plan_proposes_reorder_below_reorder_point(wh):
    today = date(2026, 11, 19)
    for weeks_ago in range(1, 27):
        day = date.fromordinal(today.toordinal() - 7 * weeks_ago + 1)
        issue(wh, 30, f"{day.isoformat()} 10:00:00")
    plan = {row["product_id"]: row for row in inventory_plan(today)}
    bolt = plan[wh["bolt"]]
    # 26 weeks x 30 issued from 1000 -> 220 left; demand 30/week, no variation
    assert bolt["weekly_mean"] == 30 and bolt["weekly_std"] == 0
    assert bolt["safety_stock"] == 0
    assert bolt["reorder_point"] == round(30 * 5 / 7, 1)
    assert bolt["inventory_position"] == 220
    assert bolt["reorder_now"] is False
    assert plan[wh["film"]]["reorder_now"] is False  # no demand, no proposal


def test_reorder_proposal_when_position_is_at_or_below_reorder_point(wh):
    today = date(2026, 11, 19)
    for weeks_ago in range(1, 27):
        day = date.fromordinal(today.toordinal() - 7 * weeks_ago + 1)
        issue(wh, 38, f"{day.isoformat()} 10:00:00")  # 988 issued, 12 left
    bolt = {r["product_id"]: r for r in inventory_plan(today)}[wh["bolt"]]
    assert bolt["inventory_position"] == 12
    assert bolt["reorder_point"] == round(38 * 5 / 7, 1)  # 27.1
    assert bolt["reorder_now"] is True
    # EOQ = sqrt(2 x 1976 x 50 / (0.25 x 0.25)) = sqrt(3161600) = 1778.09
    assert bolt["eoq"] == 1778.1
    assert bolt["proposed_quantity"] == 1779  # rounded up to whole units
