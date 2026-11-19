from datetime import date, timedelta

import pandas as pd
import streamlit as st

from warehouse.labels import product_labels
from warehouse.orders import (
    PRIORITIES,
    cancel_order,
    check_order,
    create_order,
    format_order_id,
    get_order,
    list_orders,
    release_order,
)
from warehouse.products import format_product_id

current_user = st.session_state.current_user

st.header("Customer orders")
st.caption(
    "Orders reserve stock only when released. Release checks availability to "
    "promise: unrestricted stock minus what released orders already reserved."
)

products = product_labels()
if not products:
    st.info("No products yet.")
    st.stop()
label_to_id = {label: pid for pid, label in products.items()}

if "order_message" in st.session_state:
    kind, text = st.session_state.pop("order_message")
    (st.success if kind == "success" else st.error)(text)

create_tab, manage_tab = st.tabs(["Create an order", "Order list and release"])

# ---- Create ----
with create_tab:
    with st.form("order_form", clear_on_submit=True):
        customer = st.text_input("Customer", key="so_customer")
        info_col, prio_col = st.columns(2)
        requested = info_col.date_input(
            "Requested delivery date", value=date.today() + timedelta(days=7),
            min_value=date.today(), key="so_date")
        priority = prio_col.segmented_control(
            "Priority", PRIORITIES, default="Normal", key="so_priority")
        st.markdown("**Order lines**")
        lines = st.data_editor(
            pd.DataFrame({"Product": pd.Series([None] * 3, dtype="object"),
                          "Quantity": [None] * 3}),
            column_config={
                "Product": st.column_config.SelectboxColumn(
                    "Product", options=list(label_to_id), width="large"),
                "Quantity": st.column_config.NumberColumn(
                    "Quantity", min_value=0.0, step=1.0, format="%.3f"),
            },
            num_rows="dynamic", hide_index=True, key="so_lines")
        created = st.form_submit_button("Create order", key="submit_so")
    if created:
        order_lines = [
            (label_to_id.get(row["Product"]),
             None if pd.isna(row["Quantity"]) else float(row["Quantity"]))
            for _, row in lines.iterrows()
            if isinstance(row["Product"], str) and row["Product"]
        ]
        try:
            order_id = create_order(customer, requested, priority, order_lines, current_user)
            st.session_state.order_message = (
                "success", f"Order {format_order_id(order_id)} created. Release it "
                           "on the second tab to reserve stock.")
            st.rerun()
        except ValueError as error:
            st.error(str(error))

# ---- List, check and release ----
with manage_tab:
    status_filter = st.segmented_control(
        "Status", ["Open", "Released", "Picked", "Shipped", "Cancelled"],
        default="Open", key="so_filter")
    orders = list_orders(status=status_filter)
    if not orders:
        st.info(f"No {status_filter.lower() if status_filter else ''} orders.")
    else:
        table = pd.DataFrame(orders)
        table["order_id"] = table["order_id"].apply(format_order_id)
        st.dataframe(
            table[["order_id", "customer_name", "requested_date", "priority", "status",
                   "lines", "created_by", "released_by"]].rename(columns={
                "order_id": "Order", "customer_name": "Customer",
                "requested_date": "Requested", "priority": "Priority",
                "status": "Status", "lines": "Lines", "created_by": "Created by",
                "released_by": "Released by"}),
            hide_index=True)

        labels = {
            o["order_id"]: f"{format_order_id(o['order_id'])} | {o['customer_name']} | "
                           f"{o['requested_date']} | {o['priority']}"
            for o in orders
        }
        chosen = st.selectbox("Order", list(labels), format_func=labels.get, key="so_chosen")
        order = get_order(chosen)

        st.markdown(f"**Availability check for {format_order_id(chosen)}**")
        check = pd.DataFrame(check_order(chosen))
        check["product_id"] = check["product_id"].apply(format_product_id)
        st.dataframe(
            check[["product_id", "product_name", "unit_of_measure", "quantity",
                   "available_to_promise", "shortage"]].rename(columns={
                "product_id": "Product ID", "product_name": "Product",
                "unit_of_measure": "UoM", "quantity": "Ordered",
                "available_to_promise": "Available to promise", "shortage": "Shortage"}),
            hide_index=True)

        if order["status"] in ("Open", "Released"):
            release_col, cancel_col = st.columns(2, vertical_alignment="bottom")
            if order["status"] == "Open":
                if release_col.button("Release for picking", type="primary", key="so_release"):
                    try:
                        release_order(chosen, current_user)
                        st.session_state.order_message = (
                            "success", f"{format_order_id(chosen)} released. Stock is reserved.")
                        st.rerun()
                    except ValueError as error:
                        st.error(str(error))
            reason = cancel_col.text_input("Cancellation reason", key="so_cancel_reason")
            if cancel_col.button("Cancel order", key="so_cancel"):
                try:
                    cancel_order(chosen, current_user, reason)
                    st.session_state.order_message = (
                        "success", f"{format_order_id(chosen)} cancelled.")
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))
