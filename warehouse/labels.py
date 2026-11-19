"""Readable labels for dropdowns (no Streamlit code here)."""
from warehouse.locations import list_bins
from warehouse.products import format_product_id, list_products


def product_labels():
    """{product_id: "MAT-00001 | Hex Bolt M8 (EA)"} for every product."""
    return {
        p["product_id"]: f"{format_product_id(p['product_id'])} | {p['name']} ({p['unit_of_measure']})"
        for p in list_products()
    }


def bin_labels(zone_types=None):
    """{bin_id: "A-01-02 (Storage)"}, optionally only for some zone types."""
    return {
        b["bin_id"]: f"{b['bin_code']} ({b['zone_type']}){' BLOCKED' if b['is_blocked'] else ''}"
        for b in list_bins()
        if zone_types is None or b["zone_type"] in zone_types
    }
