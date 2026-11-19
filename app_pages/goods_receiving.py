import pandas as pd
import streamlit as st

from warehouse.inventory import transfer_stock
from warehouse.labels import bin_labels, product_labels
from warehouse.products import format_product_id
from warehouse.receiving import (
    PUTAWAY_ZONE_TYPES,
    RECEIVING_ZONE_TYPES,
    format_receipt_id,
    list_receipts,
    receive_goods,
    stock_waiting_for_putaway,
    suggest_putaway_bin,
)

current_user = st.session_state.current_user

st.header("Goods receiving")
st.caption(
    "Book incoming deliveries against the delivery note, then put the goods away "
    "into storage. Every step is a recorded stock movement."
)

products = product_labels()
receiving_bins = bin_labels(RECEIVING_ZONE_TYPES)

if not products or not receiving_bins:
    st.info(
        "You need at least one product and one bin in a Receiving, Quarantine or "
        "Damaged zone before you can receive goods."
    )
    st.stop()

receipt_column, putaway_column = st.columns(2, gap="large")

# ---- Goods receipt ----
with receipt_column:
    st.subheader("Receive a delivery")
    with st.form("receipt_form", clear_on_submit=True):
        product_id = st.selectbox(
            "Product", list(products), format_func=products.get, key="gr_product")
        quantity = st.number_input(
            "Quantity received", min_value=0.0, step=1.0, format="%.3f", key="gr_quantity")
        delivery_note = st.text_input(
            "Delivery note number", placeholder="e.g. DN-2026-0042", key="gr_note")
        to_bin_id = st.selectbox(
            "Receive into bin", list(receiving_bins), format_func=receiving_bins.get,
            key="gr_bin",
            help="Use a Quarantine or Damaged bin if the goods fail the check on arrival.",
        )
        received = st.form_submit_button("Post goods receipt", key="submit_gr")
    if received:
        try:
            receipt_id = receive_goods(
                product_id, quantity, delivery_note, to_bin_id, current_user)
            st.success(f"Goods receipt {format_receipt_id(receipt_id)} posted.")
        except ValueError as error:
            st.error(str(error))

# ---- Putaway ----
with putaway_column:
    st.subheader("Put away")
    if "putaway_message" in st.session_state:
        st.success(st.session_state.pop("putaway_message"))
    waiting = stock_waiting_for_putaway()
    if not waiting:
        st.info("Nothing is waiting in receiving.")
    else:
        waiting_labels = {
            i: f"{w['bin_code']} | {format_product_id(w['product_id'])} "
               f"{w['product_name']} | {w['quantity']:g} {w['unit_of_measure']}"
            for i, w in enumerate(waiting)
        }
        choice = st.selectbox(
            "Stock in receiving", list(waiting_labels),
            format_func=waiting_labels.get, key="pa_choice")
        item = waiting[choice]
        suggestion = suggest_putaway_bin(item["product_id"])
        storage_bins = bin_labels(PUTAWAY_ZONE_TYPES)
        if suggestion:
            st.caption(f"Suggested bin: **{suggestion['bin_code']}** ({suggestion['rule']}).")
        else:
            st.warning("No free storage bin found. Create bins or unblock one.")
        if storage_bins:
            bin_ids = list(storage_bins)
            default = bin_ids.index(suggestion["bin_id"]) if suggestion else 0
            with st.form("putaway_form"):
                target = st.selectbox(
                    "Destination bin", bin_ids, index=default,
                    format_func=storage_bins.get, key=f"pa_bin_{choice}")
                pa_quantity = st.number_input(
                    "Quantity", min_value=0.0, max_value=float(item["quantity"]),
                    value=float(item["quantity"]), format="%.3f", key=f"pa_qty_{choice}")
                put_away = st.form_submit_button("Confirm putaway", key="submit_pa")
            if put_away:
                try:
                    transfer_stock(item["product_id"], item["bin_id"], target,
                                   pa_quantity, current_user, "PUTAWAY")
                    # Rerun so the "waiting" list refreshes; show the message after it.
                    st.session_state.putaway_message = (
                        f"{pa_quantity:g} put away to {storage_bins[target]}.")
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))

# ---- Receipt history ----
st.subheader("Recent goods receipts")
receipts = list_receipts()
if receipts:
    table = pd.DataFrame(receipts)
    table["receipt_id"] = table["receipt_id"].apply(format_receipt_id)
    table["product_id"] = table["product_id"].apply(format_product_id)
    st.dataframe(
        table.rename(columns={
            "receipt_id": "Receipt", "received_at": "Received (UTC)",
            "product_id": "Product ID", "product_name": "Product",
            "quantity": "Quantity", "unit_of_measure": "UoM",
            "delivery_note": "Delivery note", "bin_code": "Bin",
            "received_by": "Received by",
        }),
        hide_index=True,
    )
else:
    st.info("No goods received yet.")
