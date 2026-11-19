import pandas as pd
import streamlit as st

from warehouse.counts import (
    REASONS,
    TOLERANCE_PERCENT,
    TOLERANCE_VALUE_EUR,
    decide_count,
    format_count_id,
    inventory_accuracy,
    investigation_hints,
    list_counts,
    record_count,
)
from warehouse.inventory import list_movements, MOVEMENT_TYPES
from warehouse.labels import product_labels
from warehouse.locations import find_bin
from warehouse.products import format_product_id

current_user = st.session_state.current_user

st.header("Stock counts and discrepancies")
st.caption(
    "Physical counts are stored next to system stock. Differences within "
    f"{TOLERANCE_PERCENT:g} % and {TOLERANCE_VALUE_EUR:g} EUR are adjusted "
    "automatically; larger ones need approval by a second person."
)

products = product_labels()
if not products:
    st.info("No products yet.")
    st.stop()

count_tab, approval_tab, history_tab = st.tabs(
    ["Record a count", "Approvals and investigation", "Count history"])

# ---- Record a count (blind: the counter does not see the system quantity) ----
with count_tab:
    st.caption(
        "Blind count: the system quantity is not shown, so the count is not "
        "influenced by what the system expects.")
    with st.form("count_form", clear_on_submit=True):
        product_id = st.selectbox(
            "Product", list(products), format_func=products.get, key="cnt_product")
        bin_code = st.text_input("Bin (scan or type)", key="cnt_bin")
        counted = st.number_input(
            "Counted quantity", min_value=0.0, step=1.0, format="%.3f", key="cnt_qty")
        reason = st.selectbox(
            "Reason if the count differs", [""] + REASONS, key="cnt_reason",
            help="Only needed if there is a difference. You will be told if one is needed.")
        submitted = st.form_submit_button("Record count", key="submit_cnt")
    if submitted:
        found = find_bin(bin_code)
        if found is None:
            st.error(f"Bin '{bin_code.strip()}' does not exist.")
        else:
            try:
                count_id, status = record_count(
                    product_id, found["bin_id"], counted, current_user, reason)
                messages = {
                    "Matched": "Count matches system stock.",
                    "Adjusted": "Difference within tolerance. Stock adjusted.",
                    "Pending approval": "Difference outside tolerance. Sent for approval.",
                }
                show = st.warning if status == "Pending approval" else st.success
                show(f"{format_count_id(count_id)}: {messages[status]}")
            except ValueError as error:
                st.error(str(error))

# ---- Approvals ----
with approval_tab:
    pending = list_counts(status="Pending approval")
    if not pending:
        st.info("No counts waiting for approval.")
    else:
        labels = {
            c["count_id"]: f"{format_count_id(c['count_id'])} | {c['bin_code']} | "
                           f"{c['product_name']} | difference {c['difference']:+g} "
                           f"({c['difference_value']:+.2f} EUR)"
            for c in pending
        }
        chosen = st.selectbox(
            "Count to review", list(labels), format_func=labels.get, key="appr_count")
        count = next(c for c in pending if c["count_id"] == chosen)

        detail = st.container(horizontal=True)
        detail.metric("System quantity", f"{count['system_quantity']:g}", border=True)
        detail.metric("Counted quantity", f"{count['counted_quantity']:g}", border=True)
        detail.metric("Difference (EUR)", f"{count['difference_value']:+.2f}", border=True)
        st.caption(f"Counted by {count['counted_by']} at {count['counted_at']} UTC. "
                   f"Reason given: {count['reason']}.")

        st.markdown("**Where to look**")
        st.caption("Hints from the records. They point to processes to check, "
                   "not to people.")
        for hint in investigation_hints(chosen):
            st.markdown(f"- {hint}")

        recent = list_movements(product_id=count["product_id"], limit=10)
        if recent:
            st.markdown("**Recent movements of this product**")
            table = pd.DataFrame(recent)[
                ["created_at", "movement_type", "from_bin", "to_bin", "quantity", "reference"]]
            table["movement_type"] = table["movement_type"].map(MOVEMENT_TYPES)
            st.dataframe(table, hide_index=True)

        with st.form("decision_form", clear_on_submit=True):
            note = st.text_input("Decision note", key="appr_note",
                                 placeholder="e.g. Recounted with team lead, 7 confirmed")
            approve_col, reject_col = st.columns(2)
            approved = approve_col.form_submit_button(
                "Approve and adjust stock", type="primary", key="approve")
            rejected = reject_col.form_submit_button("Reject (recount)", key="reject")
        if approved or rejected:
            try:
                decide_count(chosen, approved, current_user, note)
                st.session_state.decision_message = (
                    f"{format_count_id(chosen)} {'approved' if approved else 'rejected'}.")
                st.rerun()
            except ValueError as error:
                st.error(str(error))
    if "decision_message" in st.session_state:
        st.success(st.session_state.pop("decision_message"))

# ---- History and accuracy ----
with history_tab:
    accuracy, number = inventory_accuracy()
    metrics = st.container(horizontal=True)
    metrics.metric(
        "Inventory accuracy", "-" if accuracy is None else f"{accuracy:g} %", border=True,
        help="Share of counts with a difference inside the tolerance.")
    metrics.metric("Counts recorded", number, border=True)
    counts = list_counts()
    if counts:
        table = pd.DataFrame(counts)
        table["count_id"] = table["count_id"].apply(format_count_id)
        table["product_id"] = table["product_id"].apply(format_product_id)
        st.dataframe(
            table.rename(columns={
                "count_id": "Count", "counted_at": "Counted (UTC)",
                "product_id": "Product ID", "product_name": "Product",
                "bin_code": "Bin", "system_quantity": "System qty",
                "counted_quantity": "Counted qty", "difference": "Difference",
                "difference_value": "Difference (EUR)", "reason": "Reason",
                "status": "Status", "counted_by": "Counted by",
                "decided_by": "Decided by", "decided_at": "Decided (UTC)",
                "decision_note": "Decision note",
            }),
            hide_index=True,
        )
    else:
        st.info("No counts recorded yet.")
