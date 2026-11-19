import pandas as pd
import streamlit as st

from warehouse.database import create_tables
from warehouse.products import (
    CATEGORIES,
    MAX_LEAD_TIME_DAYS,
    UNITS_OF_MEASURE,
    add_product,
    format_product_id,
    get_product,
    list_products,
    update_product,
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

# ---- Edit an existing product ----
st.subheader("Edit a product")
all_products = list_products()

if all_products:
    labels = {
        p["product_id"]: f"{format_product_id(p['product_id'])} | {p['name']}"
        for p in all_products
    }
    selected_id = st.selectbox(
        "Product to edit", list(labels), format_func=labels.get, key="edit_select"
    )
    product = get_product(selected_id)

    with st.form("edit_product_form"):
        edit_name = st.text_input(
            "Product name", value=product["name"], key=f"edit_name_{selected_id}"
        )
        edit_category = st.selectbox(
            "Category", CATEGORIES,
            index=CATEGORIES.index(product["category"]),
            key=f"edit_category_{selected_id}",
        )
        edit_uom = st.selectbox(
            "Unit of measure", UNITS_OF_MEASURE,
            index=UNITS_OF_MEASURE.index(product["unit_of_measure"]),
            key=f"edit_uom_{selected_id}",
        )
        edit_cost = st.number_input(
            "Unit cost (EUR)", min_value=0.0, step=0.01, format="%.2f",
            value=product["unit_cost"], key=f"edit_cost_{selected_id}",
        )
        edit_supplier = st.text_input(
            "Supplier name", value=product["supplier_name"],
            key=f"edit_supplier_{selected_id}",
        )
        edit_lead_time = st.number_input(
            "Lead time (days)", min_value=0, max_value=MAX_LEAD_TIME_DAYS, step=1,
            value=product["lead_time_days"], key=f"edit_lead_time_{selected_id}",
        )
        saved = st.form_submit_button("Save changes", key="save_edit")

    if saved:
        try:
            update_product(
                selected_id, edit_name, edit_category, edit_uom,
                edit_cost, edit_supplier, edit_lead_time,
            )
            st.success(f"Product {format_product_id(selected_id)} updated.")
        except ValueError as error:
            st.error(str(error))
else:
    st.info("Register a product first, then you can edit it here.")

# ---- List all products ----
st.subheader("Registered products")
search_text = st.text_input(
    "Search", placeholder="Product ID, name, category or supplier", key="search"
)
products = list_products(search_text)

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
        "updated_at": "Last updated (UTC)",
    })
    st.dataframe(table, hide_index=True)
elif search_text.strip():
    st.info(f"No products match '{search_text.strip()}'.")
else:
    st.info("No products registered yet.")