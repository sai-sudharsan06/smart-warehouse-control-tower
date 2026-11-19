import streamlit as st

from warehouse.database import create_tables

st.set_page_config(page_title="Smart Warehouse Control Tower", layout="wide")
create_tables()

page = st.navigation([
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
])

st.sidebar.text_input(
    "Current user (simulated)", value="demo.user", key="current_user"
)
st.sidebar.caption("No real login yet. This name is recorded in the change history.")

st.title("Smart warehouse control tower")
st.caption("Prototype with synthetic data only. Not a production WMS.")

page.run()