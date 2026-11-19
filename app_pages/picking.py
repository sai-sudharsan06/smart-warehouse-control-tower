import altair as alt
import pandas as pd
import streamlit as st

from warehouse.labels import bin_labels
from warehouse.orders import format_order_id, list_orders
from warehouse.picking import (
    AISLE_SPACING_M,
    RACK_WIDTH_M,
    confirm_picking,
    create_pick_list,
    get_pick_list,
    route_statistics,
    ship_order,
)
from warehouse.locations import find_bin, list_zones

current_user = st.session_state.current_user

st.header("Picking and shipping")
st.caption(
    "Pick lists for released orders, in an optimised walking sequence. Distances "
    "come from a simplified layout model (one aisle per storage zone, a front "
    "cross-aisle, 2.5 m per rack). They are simulated, not measured."
)

if "pick_message" in st.session_state:
    st.success(st.session_state.pop("pick_message"))

stats = route_statistics()
if stats["pick_lists"]:
    saved = stats["naive_distance_m"] - stats["distance_m"]
    share = saved / stats["naive_distance_m"] * 100 if stats["naive_distance_m"] else 0
    row = st.container(horizontal=True)
    row.metric("Pick lists", stats["pick_lists"], border=True)
    row.metric("Walking distance (m)", f"{stats['distance_m']:,.0f}", border=True)
    row.metric("Saved vs bin-code order (m)", f"{saved:,.0f}",
               delta=f"{share:.1f} % shorter", delta_color="normal", border=True)


def draw_route(tasks):
    """Plot the depot and the pick stops in walking order on the layout grid."""
    storage = sorted(
        (z for z in list_zones() if z["zone_type"] in ("Storage", "Picking")),
        key=lambda z: z["zone_code"])
    aisle_y = {z["zone_code"]: (i + 1) * AISLE_SPACING_M for i, z in enumerate(storage)}
    points = [{"step": 0, "label": "Depot", "x": 0.0, "y": 0.0}]
    for task in tasks:
        found = find_bin(task["bin_code"])
        rack = int(task["bin_code"].split("-")[1])
        points.append({"step": task["sequence"], "label": task["bin_code"],
                       "x": rack * RACK_WIDTH_M, "y": aisle_y[found["zone_code"]]})
    # Walk: along the aisle to the front, along the cross-aisle, into the next aisle
    path, step = [], 0
    for a, b in zip(points, points[1:] + [points[0]]):
        for x, y in ([(a["x"], a["y"])] + ([] if a["y"] == b["y"] else
                     [(0.0, a["y"]), (0.0, b["y"])]) + [(b["x"], b["y"])]):
            path.append({"x": x, "y": y, "order": step})
            step += 1
    base = alt.Chart(pd.DataFrame(path)).mark_line(strokeWidth=2).encode(
        x=alt.X("x:Q", title="Depth into aisle (m)"),
        y=alt.Y("y:Q", title="Cross-aisle position (m)"),
        order="order:Q")
    stops = alt.Chart(pd.DataFrame(points)).mark_circle(size=120).encode(
        x="x:Q", y="y:Q", tooltip=["step", "label"])
    text = alt.Chart(pd.DataFrame(points)).mark_text(dy=-12).encode(
        x="x:Q", y="y:Q", text="label")
    st.altair_chart(base + stops + text, alt="Walking route of the pick list")


pick_tab, ship_tab = st.tabs(["Pick released orders", "Ship picked orders"])

# ---- Picking ----
with pick_tab:
    released = list_orders(status="Released")
    if not released:
        st.info("No released orders. Release an order on the Customer orders page.")
    else:
        labels = {o["order_id"]: f"{format_order_id(o['order_id'])} | {o['customer_name']} | "
                                 f"{o['requested_date']} | {o['priority']}" for o in released}
        order_id = st.selectbox("Order", list(labels), format_func=labels.get, key="pk_order")
        tasks, route = get_pick_list(order_id)
        if not tasks:
            method = st.segmented_control(
                "Route method", ["OR-Tools route", "Bin code order"],
                default="OR-Tools route", key="pk_method",
                help="Compare an optimised walking route with a list sorted by bin code.")
            if st.button("Create pick list", type="primary", key="pk_create"):
                try:
                    result = create_pick_list(
                        order_id, current_user, optimise=(method != "Bin code order"))
                    st.session_state.pick_message = (
                        f"Pick list created ({result['method']}): {result['distance_m']:g} m "
                        f"walking, bin-code order would be {result['naive_distance_m']:g} m.")
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))
        else:
            st.markdown(f"**Pick list for {format_order_id(order_id)}** "
                        f"({route['method']}: {route['distance_m']:g} m, "
                        f"bin-code order {route['naive_distance_m']:g} m)")
            st.dataframe(pd.DataFrame(tasks)[
                ["sequence", "bin_code", "product_name", "quantity", "unit_of_measure", "status"]
            ].rename(columns={"sequence": "Stop", "bin_code": "Bin", "product_name": "Product",
                              "quantity": "Quantity", "unit_of_measure": "UoM",
                              "status": "Status"}), hide_index=True)
            draw_route(tasks)
            shipping_bins = bin_labels(["Shipping"])
            if not shipping_bins:
                st.warning("Create a bin in a Shipping zone to receive picked goods.")
            else:
                with st.form("confirm_pick_form"):
                    target = st.selectbox("Put picked goods into", list(shipping_bins),
                                          format_func=shipping_bins.get, key="pk_ship_bin")
                    confirmed = st.form_submit_button("Confirm all picks", type="primary",
                                                      key="pk_confirm")
                if confirmed:
                    try:
                        confirm_picking(order_id, target, current_user)
                        st.session_state.pick_message = (
                            f"{format_order_id(order_id)} picked and staged for shipping.")
                        st.rerun()
                    except ValueError as error:
                        st.error(str(error))

# ---- Shipping ----
with ship_tab:
    picked = list_orders(status="Picked")
    if not picked:
        st.info("No picked orders waiting for shipping.")
    else:
        labels = {o["order_id"]: f"{format_order_id(o['order_id'])} | {o['customer_name']}"
                  for o in picked}
        order_id = st.selectbox("Order", list(labels), format_func=labels.get, key="sh_order")
        if st.button("Post goods issue and ship", type="primary", key="sh_ship"):
            try:
                ship_order(order_id, current_user)
                st.session_state.pick_message = f"{format_order_id(order_id)} shipped."
                st.rerun()
            except ValueError as error:
                st.error(str(error))
