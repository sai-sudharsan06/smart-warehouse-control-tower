"""Generate a synthetic demo warehouse for the fictional company AX Drives.

Usage (from the project folder, with the virtual environment active):

    python scripts/seed_demo_data.py              # 26 weeks, seed 42
    python scripts/seed_demo_data.py --weeks 12 --seed 7

It writes a SEPARATE database, data/demo_warehouse.db, and never touches
data/warehouse.db. Open the demo in the app with:

    $env:WAREHOUSE_DB = "data/demo_warehouse.db"; streamlit run app.py

Every receipt, putaway, order, pick, shipment and count goes through the same
business functions as the app, so all rules (ledger, ATP, four-eyes approval)
apply. Demand, deliveries and count errors are random but reproducible
(fixed seed). After each simulated day, the script moves that day's
timestamps back to the simulated date; this is the only direct database edit.
All data is synthetic. Customer and supplier names are invented.
"""
import argparse
import random
import sys
import time
from datetime import date, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from warehouse import database, picking  # noqa: E402
from warehouse.counts import REASONS, decide_count, list_counts, record_count  # noqa: E402
from warehouse.inventory import list_stock, transfer_stock  # noqa: E402
from warehouse.locations import add_bins_bulk, add_zone, find_bin, list_bins  # noqa: E402
from warehouse.orders import (  # noqa: E402
    cancel_order, create_order, list_orders, release_order)
from warehouse.picking import confirm_picking, create_pick_list, ship_order  # noqa: E402
from warehouse.products import add_product  # noqa: E402
from warehouse.receiving import receive_goods, suggest_putaway_bin  # noqa: E402

# name, category, unit, unit cost EUR, supplier, lead time days, mean weekly demand, variation
PRODUCTS = [
    ("Motor Housing AL-200", "Semi-Finished Good", "EA", 18.50, "Alu Guss Nord GmbH", 21, 40, 0.35),
    ("Gearbox Housing GH-32", "Semi-Finished Good", "EA", 24.90, "Alu Guss Nord GmbH", 21, 35, 0.35),
    ("Controller Housing CH-10", "Semi-Finished Good", "EA", 9.80, "Kunststoff Werk Sud", 14, 40, 0.30),
    ("Planetary Gear Set PG-3", "Semi-Finished Good", "EA", 31.00, "Getriebe Technik AG", 28, 30, 0.40),
    ("Drive Shaft 12mm", "Semi-Finished Good", "EA", 6.40, "Getriebe Technik AG", 14, 60, 0.30),
    ("Ball Bearing 6001-2RS", "Spare Part", "EA", 1.15, "Lager Handel Ost", 10, 240, 0.25),
    ("Hex Bolt M5x16", "Consumable", "EA", 0.06, "Schraub Direkt GmbH", 7, 2000, 0.20),
    ("O-Ring 32x2 NBR", "Consumable", "EA", 0.09, "Dicht Service KG", 7, 900, 0.25),
    ("Thermal Paste 50g", "Consumable", "EA", 4.20, "Chemie Bedarf GmbH", 10, 15, 0.50),
    ("Cable Harness CH-7", "Semi-Finished Good", "EA", 7.90, "Kabel Konfektion West", 21, 45, 0.35),
    ("Shipping Carton 40x30x20", "Packaging", "EA", 0.95, "Verpackung Nord GmbH", 5, 120, 0.30),
    ("Stretch Film 500mm", "Packaging", "EA", 12.50, "Verpackung Nord GmbH", 7, 8, 0.50),
    ("Gear Oil 75W-90", "Raw Material", "L", 6.30, "Chemie Bedarf GmbH", 10, 25, 0.40),
    ("Steel Sheet 2mm", "Raw Material", "KG", 1.35, "Stahl Service Rhein", 14, 300, 0.30),
]
CUSTOMERS = ["Velo Werke GmbH", "Rad Manufaktur AG", "E-Bike Nord KG", "Trail Bikes Sud GmbH",
             "Stadtrad Systeme GmbH"]  # invented names
USERS = {"receive": "anna.meier", "putaway": "ben.wolf", "sales": "sam.vogel",
         "release": "lisa.lead", "pick": "pia.schulz", "ship": "otto.braun",
         "count": "carl.fischer", "approve": "dana.lead"}
TIMESTAMP_COLUMNS = {
    "stock_movements": ["created_at"], "goods_receipts": ["received_at"],
    "sales_orders": ["created_at", "released_at", "closed_at"],
    "pick_tasks": ["created_at", "picked_at"],
    "stock_counts": ["counted_at", "decided_at"],
    "products": ["created_at"], "zones": ["created_at"], "storage_bins": ["created_at"],
}


def backdate(start_marker, day, hour=10):
    """Set every timestamp written since start_marker to the simulated day."""
    stamp = f"{day.isoformat()} {hour:02d}:00:00"
    connection = database.get_connection()
    with connection:
        for table, columns in TIMESTAMP_COLUMNS.items():
            for column in columns:
                connection.execute(
                    f"UPDATE {table} SET {column} = ? WHERE {column} >= ?",
                    (stamp, start_marker))
    connection.close()


def build_master_data(rng):
    product_ids = [add_product(*p[:6]) for p in PRODUCTS]
    receiving = add_zone("R", "Goods-in area", "Receiving")
    add_bins_bulk(receiving, 1, 2, 1, 1)
    for code in "ABC":
        add_bins_bulk(add_zone(code, f"Storage aisle {code}", "Storage"), 1, 10, 1, 3)
    add_bins_bulk(add_zone("Q", "Quarantine area", "Quarantine"), 1, 2, 1, 1)
    add_bins_bulk(add_zone("D", "Damaged goods cage", "Damaged"), 1, 1, 1, 1)
    add_bins_bulk(add_zone("S", "Shipping dock", "Shipping"), 1, 2, 1, 1)
    storage = [b for b in list_bins() if b["zone_type"] == "Storage"]
    home_bins = dict(zip(product_ids, rng.sample(storage, len(product_ids))))
    return product_ids, home_bins


def put_away(product_id, bin_id, quantity, home_bins):
    target = suggest_putaway_bin(product_id) or {"bin_id": home_bins[product_id]["bin_id"]}
    transfer_stock(product_id, bin_id, target["bin_id"], quantity, USERS["putaway"], "PUTAWAY")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--weeks", type=int, default=26)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default="data/demo_warehouse.db")
    args = parser.parse_args()

    output = (PROJECT_DIR / args.output).resolve()
    if output.name == "warehouse.db":
        sys.exit("Refusing to overwrite the real database data/warehouse.db.")
    output.parent.mkdir(exist_ok=True)
    if output.exists():
        output.unlink()  # the demo database is generated, so it is safe to rebuild
    database.DB_PATH = output
    picking.SOLVER_TIME_LIMIT_MS = 100
    database.create_tables()

    rng = random.Random(args.seed)
    started = time.time()
    first_day = date.today() - timedelta(weeks=args.weeks)
    connection = database.get_connection()
    marker = connection.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]
    connection.close()

    product_ids, home_bins = build_master_data(rng)
    spec = {pid: PRODUCTS[i] for i, pid in enumerate(product_ids)}
    receiving_bin = find_bin("R-01-01")["bin_id"]
    quarantine_bin = find_bin("Q-01-01")["bin_id"]
    damaged_bin = find_bin("D-01-01")["bin_id"]
    shipping_bin = find_bin("S-01-01")["bin_id"]

    # Opening stock: about 5 weeks of demand per product
    for pid in product_ids:
        quantity = round(spec[pid][6] * 5)
        receive_goods(pid, quantity, "DN-OPENING", receiving_bin, USERS["receive"])
        transfer_stock(pid, receiving_bin, home_bins[pid]["bin_id"], quantity,
                       USERS["putaway"], "PUTAWAY")
    backdate(marker, first_day - timedelta(days=1))

    on_order = {}       # product_id -> (arrival day, quantity): simulated purchase orders
    quarantined = []    # (release day, product_id, quantity)
    note_number = 1000
    day = first_day
    while day < date.today():
        if day.weekday() < 5:
            # 1. Deliveries arriving today
            for pid, (arrival, quantity) in list(on_order.items()):
                if arrival <= day:
                    note_number += 1
                    if rng.random() < 0.05:   # fails the check on arrival
                        receive_goods(pid, quantity, f"DN-{note_number}", quarantine_bin,
                                      USERS["receive"])
                        quarantined.append((day + timedelta(days=2), pid, quantity))
                    else:
                        receive_goods(pid, quantity, f"DN-{note_number}", receiving_bin,
                                      USERS["receive"])
                        put_away(pid, receiving_bin, quantity, home_bins)
                    del on_order[pid]
            # 2. Quality decision on quarantined deliveries (simulated)
            for item in list(quarantined):
                release_day, pid, quantity = item
                if release_day <= day:
                    if rng.random() < 0.3:
                        transfer_stock(pid, quarantine_bin, damaged_bin, quantity,
                                       USERS["putaway"], reason="Failed quality inspection")
                    else:
                        put_away(pid, quarantine_bin, quantity, home_bins)
                    quarantined.remove(item)

            # 3. Customer demand -> orders
            orders = {}
            for pid in product_ids:
                weekly, variation = spec[pid][6], spec[pid][7]
                quantity = round(max(0, rng.gauss(weekly / 5, weekly / 5 * variation)))
                if quantity:
                    orders.setdefault(rng.choice(CUSTOMERS), []).append((pid, quantity))
            for customer, lines in orders.items():
                create_order(customer, day + timedelta(days=rng.randint(2, 7)),
                             "Urgent" if rng.random() < 0.15 else "Normal",
                             lines, USERS["sales"], today=day)

            # 4. Release what is available (urgent and oldest first), cancel stale orders
            for order in list_orders(status="Open"):
                try:
                    release_order(order["order_id"], USERS["release"])
                except ValueError:
                    if (day - date.fromisoformat(order["created_at"][:10])).days > 10:
                        cancel_order(order["order_id"], USERS["release"],
                                     "Customer cancelled: delivery too late (simulated)")

            # 5. Pick and ship everything released
            for order in list_orders(status="Released"):
                try:
                    create_pick_list(order["order_id"], USERS["pick"])
                    confirm_picking(order["order_id"], shipping_bin, USERS["pick"])
                    ship_order(order["order_id"], USERS["ship"])
                except ValueError as error:
                    print(f"  {day}: could not pick SO {order['order_id']}: {error}")

            # 6. Simulated purchasing: reorder at about lead time x 1.4 of demand
            for pid in product_ids:
                if pid in on_order:
                    continue
                weekly, lead_days = spec[pid][6], spec[pid][5]
                unrestricted = sum(r["quantity"] for r in list_stock(product_id=pid)
                                   if r["status"] == "Unrestricted")
                if unrestricted <= weekly * lead_days / 7 * 1.4:
                    on_order[pid] = (day + timedelta(days=lead_days), round(weekly * 4))

            # 7. Friday cycle counts: 5 random bins, a few with differences
            if day.weekday() == 4:
                stocked = [r for r in list_stock() if r["status"] == "Unrestricted"]
                for row in rng.sample(stocked, min(5, len(stocked))):
                    roll, counted, reason = rng.random(), row["quantity"], None
                    if roll > 0.80:
                        share = rng.uniform(0.01, 0.04) if roll < 0.93 else rng.uniform(0.06, 0.2)
                        counted = max(0, round(row["quantity"] * (1 - share)))
                        reason = rng.choice(REASONS[:5])
                    if counted == row["quantity"]:
                        reason = None
                    record_count(row["product_id"], row["bin_id"], counted,
                                 USERS["count"], reason)
            # Team lead decides pending counts on the next working day
            for count in list_counts(status="Pending approval"):
                try:
                    if rng.random() < 0.75:
                        decide_count(count["count_id"], True, USERS["approve"],
                                     "Recounted with counter, difference confirmed")
                    else:
                        decide_count(count["count_id"], False, USERS["approve"],
                                     "Stock found in neighbouring bin, recount")
                except ValueError:
                    decide_count(count["count_id"], False, USERS["approve"],
                                 "Stock moved since count, recount")
        backdate(marker, day)
        day += timedelta(days=1)

    shipped = len(list_orders(status="Shipped"))
    print(f"Demo database written to {output}")
    print(f"{args.weeks} weeks simulated, {shipped} orders shipped, "
          f"{len(list_counts())} counts, in {time.time() - started:.0f} s.")


if __name__ == "__main__":
    main()
