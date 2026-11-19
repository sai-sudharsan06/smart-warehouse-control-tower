"""Warehouse KPIs, alerts and trend data for the control tower, plus the CSV
export used by the Power BI report.

KPI definitions (also listed in docs/POWER_BI_GUIDE.md):
- On-time shipping: shipped orders whose shipping date is on or before the
  requested date / all shipped orders.
- Order cycle time: days from order creation to shipping.
- Inventory accuracy: counts within tolerance / all counts (see counts.py).
- Route saving: 1 - optimised distance / bin-code-order distance.
"""
import csv
from datetime import date, datetime
from pathlib import Path
from statistics import mean

from warehouse.counts import format_count_id, inventory_accuracy, list_counts
from warehouse.database import get_connection
from warehouse.inventory import MOVEMENT_TYPES, check_stock_against_ledger, list_stock
from warehouse.orders import format_order_id, list_orders
from warehouse.picking import route_statistics
from warehouse.planning import inventory_plan
from warehouse.products import format_product_id


def _day(timestamp):
    return datetime.fromisoformat(timestamp).date() if timestamp else None


# ---- KPIs ----

def order_kpis(today=None):
    today = today or date.today()
    orders = list_orders()
    shipped = [o for o in orders if o["status"] == "Shipped"]
    on_time = [o for o in shipped
               if _day(o["closed_at"]) <= date.fromisoformat(o["requested_date"])]
    cycle = [(_day(o["closed_at"]) - _day(o["created_at"])).days for o in shipped]
    open_late = [o for o in orders if o["status"] in ("Open", "Released", "Picked")
                 and date.fromisoformat(o["requested_date"]) < today]
    return {
        "orders": len(orders),
        "shipped": len(shipped),
        "open": sum(o["status"] in ("Open", "Released", "Picked") for o in orders),
        "cancelled": sum(o["status"] == "Cancelled" for o in orders),
        "on_time_pct": round(len(on_time) / len(shipped) * 100, 1) if shipped else None,
        "avg_cycle_days": round(mean(cycle), 1) if cycle else None,
        "overdue_open": len(open_late),
    }


def stock_kpis():
    rows = list_stock()
    value_by_status = {}
    for row in rows:
        value_by_status[row["status"]] = round(
            value_by_status.get(row["status"], 0) + row["stock_value"], 2)
    return {
        "stock_value": round(sum(r["stock_value"] for r in rows), 2),
        "value_by_status": value_by_status,
        "bins_in_use": len({r["bin_id"] for r in rows}),
    }


def control_tower_kpis(today=None):
    """Everything the control tower header needs, in one dict."""
    accuracy, counts = inventory_accuracy()
    routes = route_statistics()
    saving = (round((1 - routes["distance_m"] / routes["naive_distance_m"]) * 100, 1)
              if routes["naive_distance_m"] else None)
    plan = inventory_plan(today)
    return {
        **order_kpis(today),
        **stock_kpis(),
        "inventory_accuracy_pct": accuracy,
        "counts": counts,
        "pending_approvals": len(list_counts(status="Pending approval")),
        "route_saving_pct": saving,
        "pick_lists": routes["pick_lists"],
        "products_to_reorder": sum(r["reorder_now"] for r in plan),
        "ledger_differences": len(check_stock_against_ledger()),
    }


def alerts(today=None):
    """Things a supervisor should act on, most important first.

    Each alert is (severity, area, message). Severity: "error", "warning", "info".
    Messages describe stock, bins and orders, never individual employees.
    """
    today = today or date.today()
    found = []
    differences = check_stock_against_ledger()
    if differences:
        found.append(("error", "Inventory",
                      f"{len(differences)} stock record(s) differ from the movement ledger."))
    for order in list_orders():
        if (order["status"] in ("Open", "Released", "Picked")
                and date.fromisoformat(order["requested_date"]) < today):
            found.append(("warning", "Orders",
                          f"{format_order_id(order['order_id'])} for {order['customer_name']} "
                          f"was requested for {order['requested_date']} and is still "
                          f"{order['status']}."))
    pending = list_counts(status="Pending approval")
    if pending:
        found.append(("warning", "Counts",
                      f"{len(pending)} count difference(s) waiting for approval."))
    for row in inventory_plan(today):
        if row["reorder_now"]:
            found.append(("warning", "Planning",
                          f"{format_product_id(row['product_id'])} {row['product_name']} is at "
                          f"or below its reorder point ({row['inventory_position']:g} vs "
                          f"{row['reorder_point']:g}). Proposed order: "
                          f"{row['proposed_quantity']:g}."))
    for row in list_stock():
        if row["status"] in ("Quality inspection", "Blocked"):
            found.append(("info", "Quality",
                          f"{row['quantity']:g} {row['unit_of_measure']} of "
                          f"{row['product_name']} in {row['bin_code']} ({row['status']}, "
                          f"{row['stock_value']:.2f} EUR)."))
    order = {"error": 0, "warning": 1, "info": 2}
    return sorted(found, key=lambda a: order[a[0]])


def weekly_trends():
    """Per ISO week: orders shipped, units issued, counts and counts within tolerance."""
    connection = get_connection()
    try:
        issues = connection.execute(
            "SELECT created_at, quantity FROM stock_movements WHERE movement_type = 'GI'"
        ).fetchall()
    finally:
        connection.close()
    weeks = {}

    def bucket(day):
        monday = date.fromordinal(day.toordinal() - day.weekday())
        return weeks.setdefault(monday, {"week": monday, "orders_shipped": 0,
                                         "units_issued": 0.0, "counts": 0,
                                         "counts_within_tolerance": 0})

    for order in list_orders(status="Shipped"):
        bucket(_day(order["closed_at"]))["orders_shipped"] += 1
    for issue in issues:
        bucket(_day(issue["created_at"]))["units_issued"] += issue["quantity"]
    for count in list_counts(limit=10**9):
        entry = bucket(_day(count["counted_at"]))
        entry["counts"] += 1
        if count["status"] in ("Matched",) or (
                count["status"] == "Adjusted" and count["decided_by"] == "system"):
            entry["counts_within_tolerance"] += 1
    return [weeks[k] for k in sorted(weeks)]


# ---- Export for Power BI ----

def _query(sql):
    """Return (column names, rows as dicts), so empty tables still have headers."""
    connection = get_connection()
    try:
        cursor = connection.execute(sql)
        columns = [d[0] for d in cursor.description]
        return columns, [dict(r) for r in cursor.fetchall()]
    finally:
        connection.close()


def power_bi_tables(today=None):
    """{file name: (columns, rows)} for a small star schema: dimensions + facts."""
    plan = {r["product_id"]: r for r in inventory_plan(today)}

    columns, products = _query("""
        SELECT product_id, name AS product_name, category, unit_of_measure, unit_cost,
               supplier_name, lead_time_days FROM products ORDER BY product_id""")
    for p in products:
        p["product_code"] = format_product_id(p["product_id"])
        p["abc_class"] = plan[p["product_id"]]["abc_class"]
    tables = {"dim_product.csv": (columns + ["product_code", "abc_class"], products)}

    tables["dim_bin.csv"] = _query("""
        SELECT b.bin_id, b.bin_code, z.zone_code, z.name AS zone_name, z.zone_type,
               b.rack, b.level, b.is_blocked FROM storage_bins AS b
        JOIN zones AS z ON z.zone_id = b.zone_id ORDER BY b.bin_code""")

    columns, movements = _query("""
        SELECT movement_id, DATE(created_at) AS movement_date, created_at, movement_type,
               product_id, from_bin_id, to_bin_id, quantity, reason, reference, created_by
        FROM stock_movements ORDER BY movement_id""")
    for m in movements:
        m["movement_name"] = MOVEMENT_TYPES[m["movement_type"]]
    tables["fact_movements.csv"] = (columns + ["movement_name"], movements)

    columns, orders = _query("""
        SELECT o.order_id, o.customer_name, o.requested_date, o.priority, o.status,
               DATE(o.created_at) AS created_date, DATE(o.closed_at) AS closed_date,
               COUNT(l.line_id) AS lines, SUM(l.quantity) AS units
        FROM sales_orders AS o LEFT JOIN sales_order_lines AS l ON l.order_id = o.order_id
        GROUP BY o.order_id ORDER BY o.order_id""")
    for o in orders:
        o["order_code"] = format_order_id(o["order_id"])
        shipped = o["status"] == "Shipped" and o["closed_date"]
        o["on_time"] = int(o["closed_date"] <= o["requested_date"]) if shipped else None
        o["cycle_days"] = ((date.fromisoformat(o["closed_date"])
                            - date.fromisoformat(o["created_date"])).days if shipped else None)
    tables["fact_orders.csv"] = (columns + ["order_code", "on_time", "cycle_days"], orders)

    tables["fact_order_lines.csv"] = _query("""
        SELECT line_id, order_id, product_id, quantity, picked_quantity
        FROM sales_order_lines ORDER BY line_id""")

    columns, counts = _query("""
        SELECT count_id, DATE(counted_at) AS count_date, product_id, bin_id,
               system_quantity, counted_quantity, difference, difference_value,
               reason, status, counted_by, decided_by FROM stock_counts ORDER BY count_id""")
    for c in counts:
        c["count_code"] = format_count_id(c["count_id"])
        c["within_tolerance"] = int(c["status"] == "Matched" or (
            c["status"] == "Adjusted" and c["decided_by"] == "system"))
    tables["fact_counts.csv"] = (columns + ["count_code", "within_tolerance"], counts)

    tables["fact_pick_routes.csv"] = _query("""
        SELECT r.order_id, DATE(o.closed_at) AS shipped_date, r.method, r.distance_m,
               r.naive_distance_m FROM pick_routes AS r
        JOIN sales_orders AS o ON o.order_id = r.order_id ORDER BY r.order_id""")

    stock_columns = ["product_id", "bin_id", "quantity", "stock_value", "status"]
    tables["snapshot_stock.csv"] = (
        stock_columns, [{k: r[k] for k in stock_columns} for r in list_stock()])

    plan_columns = ["product_id", "abc_class", "annual_value_eur", "weekly_mean",
                    "weekly_std", "forecast_next_week", "forecast_method", "forecast_mae",
                    "service_level", "safety_stock", "reorder_point", "eoq",
                    "inventory_position", "reorder_now", "proposed_quantity"]
    tables["snapshot_planning.csv"] = (
        plan_columns, [{k: r[k] for k in plan_columns} for r in plan.values()])
    return tables


def export_for_power_bi(folder, today=None):
    """Write every table as a UTF-8 CSV file into `folder`. Return the file paths."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for name, (columns, rows) in power_bi_tables(today).items():
        path = folder / name
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        written.append(path)
    return written
