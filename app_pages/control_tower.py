import io
import zipfile

import altair as alt
import pandas as pd
import streamlit as st

from warehouse.analytics import alerts, control_tower_kpis, power_bi_tables, weekly_trends
from warehouse.database import DB_PATH


def show(value, suffix="", digits=1):
    return "-" if value is None else f"{value:,.{digits}f}{suffix}"


st.header("Control tower")
st.caption(f"Live figures from {DB_PATH.name}. All data is synthetic.")

kpis = control_tower_kpis()

st.markdown("**Service**")
row = st.container(horizontal=True)
row.metric("On-time shipping", show(kpis["on_time_pct"], " %"), border=True,
           help="Shipped orders whose shipping date is on or before the requested date.")
row.metric("Order cycle time", show(kpis["avg_cycle_days"], " days"), border=True,
           help="Average days from order creation to shipping.")
row.metric("Open orders", kpis["open"], border=True)
row.metric("Overdue open orders", kpis["overdue_open"], border=True)

st.markdown("**Inventory**")
row = st.container(horizontal=True)
row.metric("Inventory accuracy", show(kpis["inventory_accuracy_pct"], " %"), border=True,
           help=f"Counts within tolerance, out of {kpis['counts']} counts.")
row.metric("Stock value (EUR)", show(kpis["stock_value"], digits=0), border=True)
blocked_value = (kpis["value_by_status"].get("Quality inspection", 0)
                 + kpis["value_by_status"].get("Blocked", 0))
row.metric("Quarantined or blocked (EUR)", show(blocked_value, digits=0), border=True)
row.metric("Products to reorder", kpis["products_to_reorder"], border=True)

st.markdown("**Process**")
row = st.container(horizontal=True)
row.metric("Pending count approvals", kpis["pending_approvals"], border=True)
row.metric("Route saving vs bin-code order", show(kpis["route_saving_pct"], " %"),
           border=True, help=f"Over {kpis['pick_lists']} pick lists, simulated layout.")
row.metric("Ledger differences", kpis["ledger_differences"], border=True,
           help="Stock records that do not match the movement ledger. Should be 0.")

alerts_col, trend_col = st.columns([2, 3], gap="large")

with alerts_col:
    st.subheader("Alerts")
    found = alerts()
    if not found:
        st.success("Nothing needs attention.")
    else:
        icons = {"error": ":material/error:", "warning": ":material/warning:",
                 "info": ":material/info:"}
        with st.container(height=420):
            for severity, area, message in found:
                st.markdown(f"{icons[severity]} **{area}**: {message}")
        st.caption(f"{len(found)} alerts. They describe stock, bins and orders, not people.")

with trend_col:
    st.subheader("Weekly trends")
    trends = pd.DataFrame(weekly_trends())
    if trends.empty:
        st.info("No activity yet.")
    else:
        trends["week"] = pd.to_datetime(trends["week"])
        st.altair_chart(
            alt.Chart(trends).mark_bar().encode(
                x=alt.X("week:T", title="Week starting"),
                y=alt.Y("orders_shipped:Q", title="Orders shipped")),
            alt="Orders shipped per week")
        counted = trends[trends["counts"] > 0].copy()
        if not counted.empty:
            counted["accuracy"] = counted["counts_within_tolerance"] / counted["counts"] * 100
            st.altair_chart(
                alt.Chart(counted).mark_line(point=True).encode(
                    x=alt.X("week:T", title="Week starting"),
                    y=alt.Y("accuracy:Q", title="Counts within tolerance (%)",
                            scale=alt.Scale(domain=[0, 100]))),
                alt="Inventory accuracy per week")

st.subheader("Export for Power BI")
st.caption("Nine CSV tables (products, bins, movements, orders, order lines, counts, "
           "routes, stock, planning). See docs/POWER_BI_GUIDE.md for building the report.")
if st.button("Prepare export", key="ct_export"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, (columns, rows) in power_bi_tables().items():
            archive.writestr(name, pd.DataFrame(rows, columns=columns).to_csv(index=False))
    st.download_button("Download CSV files (zip)", buffer.getvalue(),
                       file_name="warehouse_power_bi.zip", mime="application/zip",
                       key="ct_download", icon=":material/download:")
