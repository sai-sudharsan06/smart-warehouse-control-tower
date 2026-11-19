import csv
from datetime import date

import pytest

from helpers import build_small_warehouse
from warehouse import database
from warehouse.analytics import (
    alerts,
    control_tower_kpis,
    export_for_power_bi,
    order_kpis,
    weekly_trends,
)
from warehouse.counts import record_count
from warehouse.inventory import transfer_stock
from warehouse.orders import create_order, release_order
from warehouse.picking import confirm_picking, create_pick_list, ship_order
from warehouse.receiving import receive_goods

TODAY = date(2026, 11, 19)


@pytest.fixture
def wh(test_db):
    ids = build_small_warehouse()
    receive_goods(ids["bolt"], 100, "DN-1", ids["R-01-01"], "anna")
    transfer_stock(ids["bolt"], ids["R-01-01"], ids["A-01-01"], 90, "anna", "PUTAWAY")
    transfer_stock(ids["bolt"], ids["R-01-01"], ids["Q-01-01"], 10, "anna")
    return ids


def set_dates(order_id, created, closed):
    connection = database.get_connection()
    with connection:
        connection.execute(
            "UPDATE sales_orders SET created_at = ?, closed_at = ? WHERE order_id = ?",
            (created, closed, order_id))
    connection.close()


def shipped_order(wh, quantity, requested):
    order_id = create_order("Velo Werke GmbH", requested, "Normal", [(wh["bolt"], quantity)],
                            "sam", today=date(2026, 11, 1))
    release_order(order_id, "lisa")
    create_pick_list(order_id, "pia")
    confirm_picking(order_id, wh["S-01-01"], "pia")
    ship_order(order_id, "otto")
    return order_id


def test_on_time_and_cycle_time(wh):
    early = shipped_order(wh, 5, date(2026, 11, 10))
    late = shipped_order(wh, 5, date(2026, 11, 10))
    set_dates(early, "2026-11-05 08:00:00", "2026-11-09 10:00:00")  # 4 days, on time
    set_dates(late, "2026-11-05 08:00:00", "2026-11-11 10:00:00")   # 6 days, 1 day late
    kpis = order_kpis(TODAY)
    assert kpis["shipped"] == 2
    assert kpis["on_time_pct"] == 50.0
    assert kpis["avg_cycle_days"] == 5.0


def test_kpis_without_any_orders(wh):
    kpis = order_kpis(TODAY)
    assert kpis["on_time_pct"] is None and kpis["avg_cycle_days"] is None


def test_control_tower_kpis(wh):
    kpis = control_tower_kpis(TODAY)
    assert kpis["stock_value"] == 25.0   # 100 x 0.25
    assert kpis["value_by_status"] == {"Unrestricted": 22.5, "Quality inspection": 2.5}
    assert kpis["ledger_differences"] == 0
    assert kpis["inventory_accuracy_pct"] is None


def test_alerts_cover_overdue_orders_pending_counts_and_quarantine(wh):
    order_id = create_order("Rad AG", date(2026, 11, 18), "Urgent", [(wh["bolt"], 5)],
                            "sam", today=date(2026, 11, 10))
    record_count(wh["bolt"], wh["A-01-01"], 60, "carl", "Stock in wrong bin")  # pending
    found = alerts(TODAY)
    areas = [a[1] for a in found]
    assert "Orders" in areas and "Counts" in areas and "Quality" in areas
    severities = [a[0] for a in found]
    assert severities == sorted(severities, key=["error", "warning", "info"].index)
    assert any("SO-00001" in a[2] and "still Open" in a[2] for a in found)
    for name in ["carl", "anna", "sam"]:  # alerts never name employees
        assert all(name not in a[2] for a in found)
    assert order_id


def test_ledger_difference_is_the_first_alert(wh):
    connection = database.get_connection()
    with connection:
        connection.execute("UPDATE stock SET quantity = 1 WHERE bin_id = ?", (wh["A-01-01"],))
    connection.close()
    first = alerts(TODAY)[0]
    assert first[0] == "error" and first[1] == "Inventory"


def test_weekly_trends_group_by_monday(wh):
    order_id = shipped_order(wh, 5, date(2026, 11, 20))
    set_dates(order_id, "2026-11-17 08:00:00", "2026-11-18 10:00:00")  # Wednesday
    weeks = [w for w in weekly_trends() if w["orders_shipped"]]
    assert weeks[0]["week"] == date(2026, 11, 16)
    assert weeks[0]["orders_shipped"] == 1


def test_export_writes_all_tables_with_headers(wh, tmp_path):
    shipped_order(wh, 5, date(2026, 11, 30))
    paths = export_for_power_bi(tmp_path, TODAY)
    names = sorted(p.name for p in paths)
    assert names == sorted([
        "dim_product.csv", "dim_bin.csv", "fact_movements.csv", "fact_orders.csv",
        "fact_order_lines.csv", "fact_counts.csv", "fact_pick_routes.csv",
        "snapshot_stock.csv", "snapshot_planning.csv"])
    with open(tmp_path / "fact_counts.csv", encoding="utf-8") as handle:
        header = handle.readline().strip().split(",")
    assert "within_tolerance" in header  # header present although there are no counts
    with open(tmp_path / "fact_orders.csv", encoding="utf-8") as handle:
        order = next(csv.DictReader(handle))
    assert order["order_code"] == "SO-00001" and order["status"] == "Shipped"
    with open(tmp_path / "dim_product.csv", encoding="utf-8") as handle:
        products = list(csv.DictReader(handle))
    assert {p["product_code"] for p in products} == {"MAT-00001", "MAT-00002"}
