import streamlit as st

from warehouse.database import create_tables

st.set_page_config(page_title="Smart Warehouse Control Tower", layout="wide")
create_tables()

page = st.navigation({
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
    ],
})

st.sidebar.text_input(
    "Current user (simulated)", value="demo.user", key="current_user"
)
st.sidebar.caption("No real login yet. This name is recorded in the change history.")

st.title("Smart warehouse control tower")
st.caption("Prototype with synthetic data only. Not a production WMS.")

page.run()