"""Small builders for test data, shared by several test files."""
from warehouse.locations import add_bin, add_zone, find_bin
from warehouse.products import add_product

ZONES = {
    "R": ("Goods-in area", "Receiving"),
    "A": ("Bulk storage", "Storage"),
    "P": ("Pick face", "Picking"),
    "Q": ("Quarantine area", "Quarantine"),
    "D": ("Damaged goods", "Damaged"),
    "S": ("Shipping dock", "Shipping"),
}


def build_small_warehouse():
    """Create 2 products, one zone per zone type and a few bins.

    Return a dict: "bolt" and "film" are product IDs; bin codes such as
    "A-01-01" map to bin IDs.
    """
    ids = {
        "bolt": add_product("Hex Bolt M8", "Spare Part", "EA", 0.25, "Schmidt GmbH", 5),
        "film": add_product("Pallet Wrap Film", "Packaging", "BOX", 18.90, "Nord GmbH", 7),
    }
    for code, (name, zone_type) in ZONES.items():
        zone_id = add_zone(code, name, zone_type)
        add_bin(zone_id, 1, 1)
        if code == "A":
            add_bin(zone_id, 1, 2)
    for code in ["R-01-01", "A-01-01", "A-01-02", "P-01-01",
                 "Q-01-01", "D-01-01", "S-01-01"]:
        ids[code] = find_bin(code)["bin_id"]
    return ids
