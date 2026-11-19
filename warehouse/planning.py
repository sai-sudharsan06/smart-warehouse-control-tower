"""Inventory optimisation: demand history, forecasts, ABC, safety stock,
reorder point, EOQ and replenishment proposals.

Demand = goods issues (GI movements) per week. All formulas are textbook
versions with their assumptions stated here:
- weekly demand is roughly normally distributed and independent week to week;
- the supplier lead time (product master) is fixed, with no variation;
- ordering cost and holding cost rate are assumptions, not company data.
"""
from collections import defaultdict
from datetime import date, datetime
from math import ceil, sqrt
from statistics import NormalDist, mean, pstdev

from warehouse.database import get_connection
from warehouse.inventory import QUANTITY_DECIMALS, stock_summary
from warehouse.orders import reserved_quantity

HISTORY_WEEKS = 26
ORDER_COST_EUR = 50.0        # assumed cost to place and receive one order
HOLDING_RATE_PER_YEAR = 0.25  # assumed holding cost as share of unit cost
SERVICE_LEVEL_BY_CLASS = {"A": 0.98, "B": 0.95, "C": 0.90}
ABC_LIMITS = (0.80, 0.95)    # cumulative value share: A up to 80 %, B up to 95 %


# ---- Demand history ----

def weekly_demand(today=None, weeks=HISTORY_WEEKS):
    """{product_id: [demand in week -weeks ... week -1]}, oldest week first.

    Week -1 is the 7 days before `today`. Weeks without issues count as 0.
    """
    today = today or date.today()
    connection = get_connection()
    try:
        rows = connection.execute(
            "SELECT product_id, quantity, created_at FROM stock_movements "
            "WHERE movement_type = 'GI'"
        ).fetchall()
        product_ids = [r["product_id"] for r in connection.execute(
            "SELECT product_id FROM products ORDER BY product_id")]
    finally:
        connection.close()
    history = {pid: [0.0] * weeks for pid in product_ids}
    for row in rows:
        issued = datetime.fromisoformat(row["created_at"]).date()
        weeks_ago = (today - issued).days // 7  # 0 = within the last 7 days
        if 0 <= weeks_ago < weeks:
            series = history.setdefault(row["product_id"], [0.0] * weeks)
            series[weeks - 1 - weeks_ago] += row["quantity"]
    return {pid: [round(v, QUANTITY_DECIMALS) for v in s] for pid, s in history.items()}


# ---- Forecasting ----

def moving_average_forecast(series, n=4):
    """One-step-ahead forecasts: forecast[t] = mean of the n values before t.

    Return (fitted, next_forecast). fitted[t] is None where there is not enough history.
    """
    fitted = [None if t < n else mean(series[t - n:t]) for t in range(len(series))]
    nxt = mean(series[-n:]) if len(series) >= n else None
    return fitted, nxt


def exponential_smoothing_forecast(series, alpha=0.3):
    """Simple exponential smoothing. The first forecast is the first value.

    Return (fitted, next_forecast).
    """
    if not series:
        return [], None
    level = series[0]
    fitted = [None]
    for value in series[:-1]:
        level = alpha * value + (1 - alpha) * level
        fitted.append(level)
    nxt = alpha * series[-1] + (1 - alpha) * level
    return fitted, nxt


def mean_absolute_error(series, fitted):
    """MAE over the periods that have a forecast."""
    pairs = [(a, f) for a, f in zip(series, fitted) if f is not None]
    if not pairs:
        return None
    return round(mean(abs(a - f) for a, f in pairs), 3)


def best_forecast(series):
    """Compare methods by MAE on the history and return the better one."""
    candidates = {
        "Moving average (4 weeks)": moving_average_forecast(series, 4),
        "Exponential smoothing (alpha 0.3)": exponential_smoothing_forecast(series, 0.3),
    }
    results = []
    for name, (fitted, nxt) in candidates.items():
        error = mean_absolute_error(series, fitted)
        if nxt is not None and error is not None:
            results.append({"method": name, "forecast": round(nxt, 1), "mae": error,
                            "fitted": fitted})
    if not results:
        return None
    return min(results, key=lambda r: r["mae"])


# ---- ABC and stock parameters ----

def abc_classes(annual_values):
    """{key: "A"/"B"/"C"} from {key: annual consumption value}.

    Items are sorted by value; A covers the first 80 % of total value, B the
    next 15 %, C the rest. Items with zero value are C.
    """
    total = sum(annual_values.values())
    classes, cumulative = {}, 0.0
    for key, value in sorted(annual_values.items(), key=lambda kv: (-kv[1], kv[0])):
        if total <= 0 or value <= 0:
            classes[key] = "C"
            continue
        share_before = cumulative / total
        cumulative += value
        if share_before < ABC_LIMITS[0]:
            classes[key] = "A"
        elif share_before < ABC_LIMITS[1]:
            classes[key] = "B"
        else:
            classes[key] = "C"
    return classes


def z_value(service_level):
    """Safety factor for a cycle service level, e.g. 0.95 -> 1.645."""
    return NormalDist().inv_cdf(service_level)


def safety_stock(service_level, weekly_std, lead_time_days):
    """SS = z x sigma(weekly demand) x sqrt(lead time in weeks)."""
    return round(z_value(service_level) * weekly_std * sqrt(lead_time_days / 7), 1)


def reorder_point(weekly_mean, lead_time_days, safety):
    """ROP = expected demand during the lead time + safety stock."""
    return round(weekly_mean * lead_time_days / 7 + safety, 1)


def economic_order_quantity(annual_demand, unit_cost,
                            order_cost=ORDER_COST_EUR, holding_rate=HOLDING_RATE_PER_YEAR):
    """EOQ = sqrt(2 x D x S / H), with H = holding rate x unit cost."""
    holding = holding_rate * unit_cost
    if annual_demand <= 0 or holding <= 0:
        return 0.0
    return round(sqrt(2 * annual_demand * order_cost / holding), 1)


# ---- Proposals for every product ----

def inventory_plan(today=None):
    """One row per product: demand, forecast, ABC class, SS, ROP, EOQ and
    whether to reorder now.

    Inventory position = unrestricted + in receiving - reserved by released
    orders. (Open purchase orders are not modelled.)
    """
    connection = get_connection()
    try:
        products = [dict(r) for r in connection.execute(
            "SELECT product_id, name, unit_of_measure, unit_cost, lead_time_days "
            "FROM products ORDER BY product_id")]
    finally:
        connection.close()
    history = weekly_demand(today)
    stock = {row["product_id"]: row for row in stock_summary()}

    annual_value = {}
    for p in products:
        series = history.get(p["product_id"], [])
        annual_value[p["product_id"]] = (mean(series) * 52 if series else 0) * p["unit_cost"]
    classes = abc_classes(annual_value)

    plan = []
    for p in products:
        pid = p["product_id"]
        series = history.get(pid, [])
        weekly_mean = mean(series) if series else 0.0
        weekly_std = pstdev(series) if len(series) > 1 else 0.0
        forecast = best_forecast(series) if series else None
        abc = classes[pid]
        level = SERVICE_LEVEL_BY_CLASS[abc]
        ss = safety_stock(level, weekly_std, p["lead_time_days"])
        rop = reorder_point(weekly_mean, p["lead_time_days"], ss)
        eoq = economic_order_quantity(weekly_mean * 52, p["unit_cost"])
        on_hand = stock.get(pid, {})
        position = round(on_hand.get("Unrestricted", 0) + on_hand.get("In receiving", 0)
                         - reserved_quantity(pid), QUANTITY_DECIMALS)
        reorder = weekly_mean > 0 and position <= rop
        plan.append({
            "product_id": pid, "product_name": p["name"], "unit_of_measure": p["unit_of_measure"],
            "abc_class": abc, "annual_value_eur": round(annual_value[pid], 2),
            "weekly_mean": round(weekly_mean, 2), "weekly_std": round(weekly_std, 2),
            "forecast_next_week": forecast["forecast"] if forecast else None,
            "forecast_method": forecast["method"] if forecast else None,
            "forecast_mae": forecast["mae"] if forecast else None,
            "service_level": level, "lead_time_days": p["lead_time_days"],
            "safety_stock": ss, "reorder_point": rop, "eoq": eoq,
            "inventory_position": position, "reorder_now": reorder,
            "proposed_quantity": max(ceil(eoq), ceil(rop - position + 1)) if reorder else 0,
        })
    return plan


def abc_summary(plan):
    """Count and value share per ABC class."""
    total = sum(r["annual_value_eur"] for r in plan) or 1
    groups = defaultdict(lambda: {"products": 0, "value": 0.0})
    for row in plan:
        groups[row["abc_class"]]["products"] += 1
        groups[row["abc_class"]]["value"] += row["annual_value_eur"]
    return [{"abc_class": c, "products": groups[c]["products"],
             "annual_value_eur": round(groups[c]["value"], 2),
             "value_share_pct": round(groups[c]["value"] / total * 100, 1)}
            for c in ("A", "B", "C") if c in groups]
