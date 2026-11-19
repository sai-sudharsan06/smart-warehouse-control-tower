import pandas as pd
import streamlit as st

from warehouse.inventory import (
    MOVEMENT_TYPES,
    check_stock_against_ledger,
    list_movements,
    list_stock,
    stock_summary,
    transfer_stock,
)
from warehouse.labels import product_labels
from warehouse.locations import find_bin
from warehouse.products import format_product_id

current_user = st.session_state.current_user

st.header("Inventory")
st.caption(
    "Stock per product and bin. Stock status follows the zone: only "
    "Unrestricted stock (Storage and Picking zones) is available for orders."
)

products = product_labels()

overview_tab, transfer_tab, ledger_tab = st.tabs(
    ["Stock overview", "Move stock", "Movement ledger"])

# ---- Move stock (bin codes can be typed or scanned) ----
# This tab is filled first in the code, so a transfer is posted before the
# overview numbers are calculated. On screen the tabs keep their order.
with transfer_tab:
    st.caption(
        "Barcode scanners type the code they read, followed by Enter, so a scanned "
        "bin label works in these fields just like typing."
    )
    if not products:
        st.info("No products yet.")
    else:
        with st.form("transfer_form", clear_on_submit=True):
            product_id = st.selectbox(
                "Product", list(products), format_func=products.get, key="tr_product")
            from_code = st.text_input("From bin (scan or type)", key="tr_from")
            to_code = st.text_input("To bin (scan or type)", key="tr_to")
            quantity = st.number_input(
                "Quantity", min_value=0.0, step=1.0, format="%.3f", key="tr_qty")
            reason = st.text_input("Reason (optional)", key="tr_reason")
            moved = st.form_submit_button("Post transfer", key="submit_tr")
        if moved:
            source, destination = find_bin(from_code), find_bin(to_code)
            if source is None or destination is None:
                missing = from_code if source is None else to_code
                st.error(f"Bin '{missing.strip()}' does not exist.")
            else:
                try:
                    transfer_stock(product_id, source["bin_id"], destination["bin_id"],
                                   quantity, current_user, reason=reason)
                    st.success(
                        f"Moved {quantity:g} from {source['bin_code']} "
                        f"to {destination['bin_code']}.")
                except ValueError as error:
                    st.error(str(error))

# ---- Stock overview ----
with overview_tab:
    summary = stock_summary()
    if not summary:
        st.info("No stock yet. Stock enters the warehouse through Goods receiving.")
    else:
        total_value = sum(row["stock_value"] for row in summary)
        unrestricted = sum(row["Unrestricted"] for row in summary)
        blocked = sum(row["Quality inspection"] + row["Blocked"] for row in summary)
        metric_row = st.container(horizontal=True)
        metric_row.metric("Stock value (EUR)", f"{total_value:,.2f}", border=True)
        metric_row.metric("Products in stock", len(summary), border=True)
        metric_row.metric("Unrestricted quantity", f"{unrestricted:g}", border=True)
        metric_row.metric("Quarantined or blocked quantity", f"{blocked:g}", border=True)

        st.markdown("**Per product and status**")
        table = pd.DataFrame(summary)
        table["product_id"] = table["product_id"].apply(format_product_id)
        st.dataframe(
            table.rename(columns={
                "product_id": "Product ID", "product_name": "Product",
                "unit_of_measure": "UoM", "total": "Total",
                "stock_value": "Value (EUR)",
            }),
            hide_index=True,
        )

        st.markdown("**Per bin**")
        bins = pd.DataFrame(list_stock())
        bins["product_id"] = bins["product_id"].apply(format_product_id)
        st.dataframe(
            bins.drop(columns=["bin_id", "zone_code"]).rename(columns={
                "product_id": "Product ID", "product_name": "Product",
                "unit_of_measure": "UoM", "bin_code": "Bin", "zone_type": "Zone type",
                "quantity": "Quantity", "stock_value": "Value (EUR)", "status": "Status",
            }),
            hide_index=True,
        )

# ---- Movement ledger ----
with ledger_tab:
    filter_options = {None: "All products", **products}
    chosen = st.selectbox(
        "Product", list(filter_options), format_func=filter_options.get,
        key="ledger_product")
    movements = list_movements(product_id=chosen)
    if movements:
        table = pd.DataFrame(movements)
        table["product_id"] = table["product_id"].apply(format_product_id)
        table["movement_type"] = table["movement_type"].map(MOVEMENT_TYPES)
        st.dataframe(
            table.rename(columns={
                "movement_id": "No.", "created_at": "Time (UTC)",
                "movement_type": "Movement", "product_id": "Product ID",
                "product_name": "Product", "from_bin": "From", "to_bin": "To",
                "quantity": "Quantity", "reason": "Reason",
                "reference": "Reference", "created_by": "User",
            }),
            hide_index=True,
        )
    else:
        st.info("No movements recorded.")

    st.markdown("**Ledger check**")
    st.caption(
        "Rebuilds every stock quantity from the movement ledger and compares it "
        "with the stock table. A difference means stock was changed without a movement."
    )
    if st.button("Run ledger check", key="ledger_check"):
        mismatches = check_stock_against_ledger()
        if mismatches:
            st.error(f"{len(mismatches)} difference(s) found.")
            st.dataframe(pd.DataFrame(mismatches), hide_index=True)
        else:
            st.success("Stock and movement ledger agree.")
