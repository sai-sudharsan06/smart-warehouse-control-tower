import pandas as pd
import streamlit as st

from warehouse.database import create_tables
from warehouse.products import (
    CATEGORIES,
    MAX_LEAD_TIME_DAYS,
    UNITS_OF_MEASURE,
    add_product,
    format_product_id,
    list_products,
)

st.set_page_config(page_title="Smart Warehouse Control Tower", layout="wide")
create_tables()

st.title("Smart warehouse control tower")
st.caption("Prototype with synthetic data only. Not a production WMS.")

st.header("Product master data")

# ---- Register a new product ----
st.subheader("Register a product")
with st.form("add_product_form"):
    name = st.text_input("Product name", key="name")
    category = st.selectbox("Category", CATEGORIES, key="category")
    unit_of_measure = st.selectbox("Unit of measure", UNITS_OF_MEASURE, key="uom")
    unit_cost = st.number_input(
        "Unit cost (EUR)", min_value=0.0, step=0.01, format="%.2f", key="unit_cost"
    )
    supplier_name = st.text_input("Supplier name", key="supplier")
    lead_time_days = st.number_input(
        "Lead time (days)", min_value=0, max_value=MAX_LEAD_TIME_DAYS, step=1, key="lead_time"
    )
    submitted = st.form_submit_button("Register product", key="submit")

if submitted:
    try:
        new_id = add_product(
            name, category, unit_of_measure, unit_cost, supplier_name, lead_time_days
        )
        st.success(f"Product {format_product_id(new_id)} registered.")
    except ValueError as error:
        st.error(str(error))

# ---- List all products ----
st.subheader("Registered products")
products = list_products()

if products:
    table = pd.DataFrame(products)
    table["product_id"] = table["product_id"].apply(format_product_id)
    table = table.rename(columns={
        "product_id": "Product ID",
        "name": "Name",
        "category": "Category",
        "unit_of_measure": "UoM",
        "unit_cost": "Unit cost (EUR)",
        "supplier_name": "Supplier",
        "lead_time_days": "Lead time (days)",
        "created_at": "Created (UTC)",
    })
    st.dataframe(table, hide_index=True)
else:
    st.info("No products registered yet.")