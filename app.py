import streamlit as st

from warehouse.database import create_tables

st.set_page_config(page_title="Smart Warehouse Control Tower", layout="wide")
create_tables()

page = st.navigation({
    "Overview": [
        st.Page(
            "app_pages/control_tower.py",
            title="Control tower",
            icon=":material/dashboard:",
            default=True,
            help="KPIs, alerts and weekly trends across the warehouse, and the Power BI export.",
        ),
    ],
    "Master data": [
        st.Page(
            "app_pages/products.py",
            title="Product master data",
            icon=":material/inventory_2:",
            help="Register, search and edit products, with a full change history.",
        ),
        st.Page(
            "app_pages/warehouse_structure.py",
            title="Warehouse structure",
            icon=":material/warehouse:",
            help="Create storage zones and the bins inside them.",
        ),
    ],
    "Operations": [
        st.Page(
            "app_pages/goods_receiving.py",
            title="Goods receiving",
            icon=":material/local_shipping:",
            help="Post goods receipts against delivery notes and put goods away.",
        ),
        st.Page(
            "app_pages/inventory.py",
            title="Inventory",
            icon=":material/shelves:",
            help="Stock per bin and status, bin-to-bin transfers and the movement ledger.",
        ),
        st.Page(
            "app_pages/stock_counts.py",
            title="Stock counts",
            icon=":material/fact_check:",
            help="Blind stock counts, differences, approvals and inventory accuracy.",
        ),
    ],
    "Planning": [
        st.Page(
            "app_pages/planning.py",
            title="Inventory planning",
            icon=":material/insights:",
            help="ABC analysis, demand forecast, safety stock, reorder point and EOQ proposals.",
        ),
    ],
    "Outbound": [
        st.Page(
            "app_pages/orders.py",
            title="Customer orders",
            icon=":material/receipt_long:",
            help="Create customer orders, check availability and release them for picking.",
        ),
        st.Page(
            "app_pages/picking.py",
            title="Picking and shipping",
            icon=":material/route:",
            help="Pick lists with an optimised walking route, pick confirmation and goods issue.",
        ),
    ],
})

st.sidebar.text_input(
    "Current user (simulated)", value="demo.user", key="current_user"
)
st.sidebar.caption("No real login yet. This name is recorded in the change history.")

st.title("Smart warehouse control tower")
st.caption("Prototype with synthetic data only. Not a production WMS.")

page.run()