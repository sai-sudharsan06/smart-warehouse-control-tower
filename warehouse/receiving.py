"""Goods receiving and putaway suggestions."""
from warehouse.database import get_connection
from warehouse.inventory import list_stock, post_movement
from warehouse.products import clean_text

# Goods may only be received into these zone types. Goods that fail the
# visual check on arrival go straight to Quarantine or Damaged.
RECEIVING_ZONE_TYPES = ("Receiving", "Quarantine", "Damaged")
PUTAWAY_ZONE_TYPES = ("Storage", "Picking")
MAX_DELIVERY_NOTE_LENGTH = 40


def format_receipt_id(receipt_id):
    """Turn a database ID such as 7 into a display ID such as GR-00007."""
    return f"GR-{receipt_id:05d}"


def receive_goods(product_id, quantity, delivery_note, to_bin_id, user):
    """Record a goods receipt and book the stock into the receiving bin.

    The receipt and its stock movement are saved in one transaction.
    Return the receipt ID.
    """
    errors = []
    note = clean_text(delivery_note or "")
    if not note:
        errors.append("Delivery note number is required.")
    elif len(note) > MAX_DELIVERY_NOTE_LENGTH:
        errors.append(f"Delivery note must be at most {MAX_DELIVERY_NOTE_LENGTH} characters.")
    if quantity is None or quantity <= 0:
        errors.append("Quantity must be greater than zero.")
    if not user or not user.strip():
        errors.append("User name is required to receive goods.")
    if errors:
        raise ValueError(" ".join(errors))

    connection = get_connection()
    try:
        with connection:
            zone = connection.execute(
                """
                SELECT z.zone_type, b.bin_code FROM storage_bins AS b
                JOIN zones AS z ON z.zone_id = b.zone_id WHERE b.bin_id = ?
                """,
                (to_bin_id,),
            ).fetchone()
            if zone is None:
                raise ValueError("The selected bin does not exist.")
            if zone["zone_type"] not in RECEIVING_ZONE_TYPES:
                raise ValueError(
                    f"Bin {zone['bin_code']} is in a {zone['zone_type']} zone. Goods can "
                    f"only be received into: {', '.join(RECEIVING_ZONE_TYPES)}."
                )
            if connection.execute(
                "SELECT 1 FROM products WHERE product_id = ?", (product_id,)
            ).fetchone() is None:
                raise ValueError("The selected product does not exist.")
            cursor = connection.execute(
                """
                INSERT INTO goods_receipts (product_id, quantity, delivery_note,
                                            to_bin_id, received_by)
                VALUES (?, ?, ?, ?, ?)
                """,
                (product_id, quantity, note, to_bin_id, user.strip()),
            )
            receipt_id = cursor.lastrowid
            post_movement(connection, "GR", product_id, quantity, user,
                          to_bin_id=to_bin_id, reference=format_receipt_id(receipt_id),
                          reason=f"Delivery note {note}")
        return receipt_id
    finally:
        connection.close()


def list_receipts(limit=200):
    """Return goods receipts, newest first."""
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT r.receipt_id, r.received_at, r.product_id, p.name AS product_name,
                   r.quantity, p.unit_of_measure, r.delivery_note,
                   b.bin_code, r.received_by
            FROM goods_receipts AS r
            JOIN products AS p ON p.product_id = r.product_id
            JOIN storage_bins AS b ON b.bin_id = r.to_bin_id
            ORDER BY r.receipt_id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        connection.close()
    return [dict(r) for r in rows]


def stock_waiting_for_putaway():
    """Stock still in Receiving zones."""
    return [row for row in list_stock() if row["zone_type"] == "Receiving"]


def suggest_putaway_bin(product_id):
    """Suggest a storage bin for a product, or None if no bin is free.

    Rule (simple and explainable): first a non-blocked storage bin that already
    holds this product, so the product stays together; otherwise the empty,
    non-blocked storage bin with the lowest bin code.
    """
    placeholders = ", ".join("?" for _ in PUTAWAY_ZONE_TYPES)
    connection = get_connection()
    try:
        same_product = connection.execute(
            f"""
            SELECT b.bin_id, b.bin_code FROM stock AS s
            JOIN storage_bins AS b ON b.bin_id = s.bin_id
            JOIN zones AS z ON z.zone_id = b.zone_id
            WHERE s.product_id = ? AND b.is_blocked = 0
              AND z.zone_type IN ({placeholders})
            ORDER BY b.bin_code LIMIT 1
            """,
            (product_id, *PUTAWAY_ZONE_TYPES),
        ).fetchone()
        if same_product:
            return {**dict(same_product), "rule": "Bin already holds this product"}
        empty = connection.execute(
            f"""
            SELECT b.bin_id, b.bin_code FROM storage_bins AS b
            JOIN zones AS z ON z.zone_id = b.zone_id
            WHERE b.is_blocked = 0 AND z.zone_type IN ({placeholders})
              AND NOT EXISTS (SELECT 1 FROM stock AS s WHERE s.bin_id = b.bin_id)
            ORDER BY b.bin_code LIMIT 1
            """,
            PUTAWAY_ZONE_TYPES,
        ).fetchone()
        if empty:
            return {**dict(empty), "rule": "First empty storage bin"}
        return None
    finally:
        connection.close()
