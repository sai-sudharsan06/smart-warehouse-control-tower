import pandas as pd
import streamlit as st

from warehouse.locations import (
    MAX_LEVEL,
    MAX_RACK,
    ZONE_TYPES,
    add_bin,
    add_bins_bulk,
    add_zone,
    list_bins,
    list_zones,
)

st.header("Warehouse structure")
st.caption(
    "Zones are areas with one purpose. Bins are exact rack positions, coded "
    "zone-rack-level (A-01-02 = zone A, rack 1, level 2)."
)

zones_column, bins_column = st.columns(2, gap="large")

# ---- Zones ----
with zones_column:
    st.subheader("Create a zone")
    with st.form("add_zone_form", clear_on_submit=True):
        zone_code = st.text_input("Zone code (1-3 letters)", max_chars=3, key="zone_code")
        zone_name = st.text_input("Zone name", key="zone_name")
        zone_type = st.selectbox("Zone type", ZONE_TYPES, key="zone_type")
        zone_submitted = st.form_submit_button("Create zone", key="submit_zone")

    if zone_submitted:
        try:
            add_zone(zone_code, zone_name, zone_type)
            st.success(f"Zone {zone_code.strip().upper()} created.")
        except ValueError as error:
            st.error(str(error))

    st.caption("Stock in Quarantine and Damaged zones is never counted as available.")

zones = list_zones()

# ---- Bins ----
with bins_column:
    st.subheader("Create storage bins")
    if not zones:
        st.info("Create a zone first. Every bin belongs to a zone.")
    else:
        zone_labels = {
            z["zone_id"]: f"{z['zone_code']} | {z['name']} ({z['zone_type']})"
            for z in zones
        }
        mode = st.segmented_control(
            "Create", ["One bin", "A range of bins"], default="One bin", key="bin_mode"
        )
        with st.form("add_bin_form"):
            bin_zone_id = st.selectbox(
                "Zone", list(zone_labels), format_func=zone_labels.get, key="bin_zone"
            )
            if mode == "A range of bins":
                rack_col, level_col = st.columns(2)
                rack_from = rack_col.number_input(
                    "Rack from", 1, MAX_RACK, 1, key="rack_from")
                rack_to = rack_col.number_input(
                    "Rack to", 1, MAX_RACK, 1, key="rack_to")
                level_from = level_col.number_input(
                    "Level from", 1, MAX_LEVEL, 1, key="level_from")
                level_to = level_col.number_input(
                    "Level to", 1, MAX_LEVEL, 1, key="level_to")
            else:
                rack = st.number_input("Rack", 1, MAX_RACK, 1, key="rack")
                level = st.number_input("Level", 1, MAX_LEVEL, 1, key="level")
            bin_submitted = st.form_submit_button("Create bins", key="submit_bin")

        if bin_submitted:
            try:
                if mode == "A range of bins":
                    codes = add_bins_bulk(
                        bin_zone_id, rack_from, rack_to, level_from, level_to
                    )
                    st.success(f"{len(codes)} bins created: {codes[0]} to {codes[-1]}.")
                else:
                    st.success(f"Bin {add_bin(bin_zone_id, rack, level)} created.")
            except ValueError as error:
                st.error(str(error))

# ---- Lists ----
st.subheader("Zones")
if zones:
    st.dataframe(
        pd.DataFrame(zones).drop(columns="zone_id").rename(columns={
            "zone_code": "Code", "name": "Name", "zone_type": "Type",
            "created_at": "Created (UTC)",
        }),
        hide_index=True,
    )
else:
    st.info("No zones yet.")

st.subheader("Storage bins")
bins = list_bins()
if bins:
    table = pd.DataFrame(bins).drop(columns="bin_id")
    table["is_blocked"] = table["is_blocked"].astype(bool)
    st.dataframe(
        table.rename(columns={
            "bin_code": "Bin", "zone_code": "Zone", "zone_type": "Zone type",
            "rack": "Rack", "level": "Level", "is_blocked": "Blocked",
            "created_at": "Created (UTC)",
        }),
        hide_index=True,
    )
    st.caption(f"{len(bins)} bins.")
else:
    st.info("No bins yet.")
