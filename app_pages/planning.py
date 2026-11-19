from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from warehouse.planning import (
    HISTORY_WEEKS,
    HOLDING_RATE_PER_YEAR,
    ORDER_COST_EUR,
    SERVICE_LEVEL_BY_CLASS,
    abc_summary,
    best_forecast,
    inventory_plan,
    weekly_demand,
)
from warehouse.products import format_product_id

st.header("Inventory planning")
st.caption(
    f"Demand = goods issues per week over the last {HISTORY_WEEKS} weeks. ABC by annual "
    "consumption value, safety stock and reorder point from demand variation and "
    "supplier lead time, order quantity by EOQ."
)

with st.expander("Assumptions behind the numbers"):
    st.markdown(
        f"""
- Weekly demand is treated as normally distributed and independent from week to week.
- Supplier lead time is fixed (from the product master); its variation is not modelled.
- Service level by ABC class: A {SERVICE_LEVEL_BY_CLASS['A']:.0%}, B
  {SERVICE_LEVEL_BY_CLASS['B']:.0%}, C {SERVICE_LEVEL_BY_CLASS['C']:.0%} (cycle service level).
- Ordering cost {ORDER_COST_EUR:.0f} EUR per order and holding cost
  {HOLDING_RATE_PER_YEAR:.0%} of unit cost per year are assumptions, not company data.
- Inventory position = unrestricted + in receiving - reserved by released orders.
  Open purchase orders are not modelled.
- Safety stock: SS = z x sigma(weekly demand) x sqrt(lead time in weeks).
  Reorder point: ROP = mean weekly demand x lead time in weeks + SS.
  EOQ = sqrt(2 x annual demand x ordering cost / holding cost per unit).
"""
    )

plan = inventory_plan()
if not plan:
    st.info("No products yet.")
    st.stop()

to_reorder = [r for r in plan if r["reorder_now"]]
with_demand = [r for r in plan if r["weekly_mean"] > 0]
row = st.container(horizontal=True)
row.metric("Products with demand", len(with_demand), border=True)
row.metric("To reorder now", len(to_reorder), border=True)
row.metric("Annual consumption value (EUR)",
           f"{sum(r['annual_value_eur'] for r in plan):,.0f}", border=True)

if not with_demand:
    st.info("No goods issues recorded yet, so there is no demand history. Ship some "
            "orders, or open the demo database (see the README).")
    st.stop()

proposal_tab, abc_tab, product_tab = st.tabs(
    ["Replenishment proposals", "ABC analysis", "Demand and forecast per product"])

with proposal_tab:
    table = pd.DataFrame(plan)
    table["product_id"] = table["product_id"].apply(format_product_id)
    table = table.sort_values(["reorder_now", "abc_class"], ascending=[False, True])
    st.dataframe(
        table[["product_id", "product_name", "abc_class", "weekly_mean", "forecast_next_week",
               "lead_time_days", "safety_stock", "reorder_point", "inventory_position",
               "reorder_now", "proposed_quantity", "eoq"]],
        column_config={
            "product_id": "Product ID", "product_name": "Product", "abc_class": "ABC",
            "weekly_mean": st.column_config.NumberColumn("Demand per week", format="%.1f"),
            "forecast_next_week": st.column_config.NumberColumn("Forecast next week",
                                                                format="%.1f"),
            "lead_time_days": "Lead time (days)",
            "safety_stock": st.column_config.NumberColumn("Safety stock", format="%.1f"),
            "reorder_point": st.column_config.NumberColumn("Reorder point", format="%.1f"),
            "inventory_position": st.column_config.NumberColumn("Position", format="%.0f"),
            "reorder_now": st.column_config.CheckboxColumn("Reorder now"),
            "proposed_quantity": st.column_config.NumberColumn("Proposed qty", format="%.0f"),
            "eoq": st.column_config.NumberColumn("EOQ", format="%.0f"),
        },
        hide_index=True,
    )
    st.caption("Proposed quantity = EOQ, or more if needed to get back above the reorder "
               "point. Proposals are suggestions for a planner, not automatic orders.")

with abc_tab:
    summary = pd.DataFrame(abc_summary(plan))
    left, right = st.columns([1, 2])
    left.dataframe(summary, column_config={
        "abc_class": "Class", "products": "Products",
        "annual_value_eur": st.column_config.NumberColumn("Annual value (EUR)", format="%.0f"),
        "value_share_pct": st.column_config.NumberColumn("Value share", format="%.1f %%"),
    }, hide_index=True)
    pareto = pd.DataFrame(plan).sort_values("annual_value_eur", ascending=False)
    pareto["cumulative_pct"] = (pareto["annual_value_eur"].cumsum()
                                / pareto["annual_value_eur"].sum() * 100)
    bars = alt.Chart(pareto).mark_bar().encode(
        x=alt.X("product_name:N", sort=None, title=None),
        y=alt.Y("annual_value_eur:Q", title="Annual value (EUR)"),
        color=alt.Color("abc_class:N", title="Class"),
        tooltip=["product_name", "abc_class",
                 alt.Tooltip("annual_value_eur:Q", format=",.0f")])
    line = alt.Chart(pareto).mark_line(point=True, color="gray").encode(
        x=alt.X("product_name:N", sort=None),
        y=alt.Y("cumulative_pct:Q", title="Cumulative share (%)"))
    right.altair_chart(alt.layer(bars, line).resolve_scale(y="independent"),
                       alt="ABC Pareto chart of annual consumption value")

with product_tab:
    labels = {r["product_id"]: f"{format_product_id(r['product_id'])} | {r['product_name']}"
              for r in with_demand}
    chosen = st.selectbox("Product", list(labels), format_func=labels.get, key="pl_product")
    series = weekly_demand()[chosen]
    forecast = best_forecast(series)
    today = date.today()
    weeks = [today - timedelta(weeks=HISTORY_WEEKS - i) for i in range(HISTORY_WEEKS)]
    history = pd.DataFrame({"week": weeks, "Actual demand": series,
                            "Forecast": forecast["fitted"]})
    long = history.melt("week", var_name="series", value_name="quantity").dropna()
    st.altair_chart(
        alt.Chart(long).mark_line(point=True).encode(
            x=alt.X("week:T", title="Week starting"),
            y=alt.Y("quantity:Q", title="Quantity"),
            color=alt.Color("series:N", title=None)),
        alt="Weekly demand and one-step-ahead forecast")
    row = next(r for r in plan if r["product_id"] == chosen)
    st.caption(
        f"Best method on this history: {forecast['method']} (mean absolute error "
        f"{forecast['mae']:g} per week). Forecast for next week: {forecast['forecast']:g}. "
        f"Class {row['abc_class']}, service level {row['service_level']:.0%}, "
        f"safety stock {row['safety_stock']:g}, reorder point {row['reorder_point']:g}.")
