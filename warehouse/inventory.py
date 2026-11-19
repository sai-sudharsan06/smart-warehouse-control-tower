"""Stock per bin and the movement ledger.

Rule: stock never changes without a recorded movement. Every change to the
`stock` table goes through `post_movement`, which writes the movement row and
the stock change in the same database transaction.
"""
from warehouse.database import get_connection

# Stock status follows from the type of zone the stock is in.
STATUS_BY_ZONE_TYPE = {
    "Receiving": "In receiving",
    "Storage": "Unrestricted",
    "Picking": "Unrestricted",
    "Quarantine": "Quality inspection",
    "Damaged": "Blocked",
    "Shipping": "Staged for shipping",
}
AVAILABLE_STATUS = "Unrestricted"

MOVEMENT_TYPES = {
    "GR": "Goods receipt",
    "PUTAWAY": "Putaway",
    "TRANSFER": "Bin to bin transfer",
    "GI": "Goods issue",
    "ADJ_IN": "Count adjustment (+)",
    "ADJ_OUT": "Count adjustment (-)",
}
QUANTITY_DECIMALS = 3


def stock_status(zone_type):
    """Return the stock status for stock stored in a zone of this type."""
    return STATUS_BY_ZONE_TYPE[zone_type]


def _bin(connection, bin_id):
    row = connection.execute(
        """
        SELECT b.bin_id, b.bin_code, b.is_blocked, z.zone_type
        FROM storage_bins AS b JOIN zones AS z ON z.zone_id = b.zone_id
        WHERE b.bin_id = ?
        """,
        (bin_id,),
    ).fetchone()
    if row is None:
        raise ValueError("The selected bin does not exist.")
    return row


def _quantity_in_bin(connection, product_id, bin_id):
    row = connection.execute(
        "SELECT quantity FROM stock WHERE product_id = ? AND bin_id = ?",
        (product_id, bin_id),
    ).fetchone()
    return row["quantity"] if row else 0


def post_movement(connection, movement_type, product_id, quantity, user,
                  from_bin_id=None, to_bin_id=None, reason=None, reference=None):
    """Record one movement and change the stock. Must run inside a transaction.

    Raise ValueError (and change nothing) if the movement is not allowed.
    Return the new movement ID.
    """
    if movement_type not in MOVEMENT_TYPES:
        raise ValueError(f"Unknown movement type {movement_type}.")
    if not user or not user.strip():
        raise ValueError("User name is required to move stock.")
    if quantity is None or quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")
    if from_bin_id is None and to_bin_id is None:
        raise ValueError("A movement needs a source bin, a destination bin or both.")
    if from_bin_id is not None and from_bin_id == to_bin_id:
        raise ValueError("Source and destination bin must be different.")
    if connection.execute(
        "SELECT 1 FROM products WHERE product_id = ?", (product_id,)
    ).fetchone() is None:
        raise ValueError("The selected product does not exist.")

    quantity = round(quantity, QUANTITY_DECIMALS)

    if from_bin_id is not None:
        source = _bin(connection, from_bin_id)
        if source["is_blocked"]:
            raise ValueError(f"Bin {source['bin_code']} is blocked.")
        on_hand = _quantity_in_bin(connection, product_id, from_bin_id)
        if quantity > on_hand:
            raise ValueError(
                f"Only {on_hand:g} in bin {source['bin_code']}; cannot move {quantity:g}."
            )
        remaining = round(on_hand - quantity, QUANTITY_DECIMALS)
        if remaining == 0:
            connection.execute(
                "DELETE FROM stock WHERE product_id = ? AND bin_id = ?",
                (product_id, from_bin_id),
            )
        else:
            connection.execute(
                "UPDATE stock SET quantity = ? WHERE product_id = ? AND bin_id = ?",
                (remaining, product_id, from_bin_id),
            )

    if to_bin_id is not None:
        destination = _bin(connection, to_bin_id)
        if destination["is_blocked"]:
            raise ValueError(f"Bin {destination['bin_code']} is blocked.")
        new_quantity = round(
            _quantity_in_bin(connection, product_id, to_bin_id) + quantity,
            QUANTITY_DECIMALS,
        )
        connection.execute(
            """
            INSERT INTO stock (product_id, bin_id, quantity) VALUES (?, ?, ?)
            ON CONFLICT (product_id, bin_id) DO UPDATE SET quantity = excluded.quantity
            """,
            (product_id, to_bin_id, new_quantity),
        )

    cursor = connection.execute(
        """
        INSERT INTO stock_movements (movement_type, product_id, from_bin_id,
                                     to_bin_id, quantity, reason, reference, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (movement_type, product_id, from_bin_id, to_bin_id, quantity,
         (reason or "").strip() or None, reference, user.strip()),
    )
    return cursor.lastrowid


def transfer_stock(product_id, from_bin_id, to_bin_id, quantity, user,
                   movement_type="TRANSFER", reason=None):
    """Move stock from one bin to another. Return the movement ID."""
    if movement_type not in ("TRANSFER", "PUTAWAY"):
        raise ValueError("A transfer must be of type TRANSFER or PUTAWAY.")
    if from_bin_id is None or to_bin_id is None:
        raise ValueError("A transfer needs both a source and a destination bin.")
    connection = get_connection()
    try:
        with connection:
            return post_movement(connection, movement_type, product_id, quantity,
                                 user, from_bin_id, to_bin_id, reason)
    finally:
        connection.close()


STOCK_QUERY = """
    SELECT s.product_id, p.name AS product_name, p.unit_of_measure,
           s.bin_id, b.bin_code, z.zone_code, z.zone_type, s.quantity,
           ROUND(s.quantity * p.unit_cost, 2) AS stock_value
    FROM stock AS s
    JOIN products AS p ON p.product_id = s.product_id
    JOIN storage_bins AS b ON b.bin_id = s.bin_id
    JOIN zones AS z ON z.zone_id = b.zone_id
"""


def list_stock(product_id=None, bin_id=None):
    """Return stock per product and bin, with status and value."""
    conditions, params = [], []
    if product_id is not None:
        conditions.append("s.product_id = ?")
        params.append(product_id)
    if bin_id is not None:
        conditions.append("s.bin_id = ?")
        params.append(bin_id)
    sql = STOCK_QUERY
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY p.product_id, b.bin_code"
    connection = get_connection()
    try:
        rows = [dict(r) for r in connection.execute(sql, params).fetchall()]
    finally:
        connection.close()
    for row in rows:
        row["status"] = stock_status(row["zone_type"])
    return rows


def stock_summary():
    """Return one row per product with quantities per stock status."""
    statuses = list(dict.fromkeys(STATUS_BY_ZONE_TYPE.values()))
    summary = {}
    for row in list_stock():
        entry = summary.setdefault(row["product_id"], {
            "product_id": row["product_id"],
            "product_name": row["product_name"],
            "unit_of_measure": row["unit_of_measure"],
            **{status: 0 for status in statuses},
            "total": 0,
            "stock_value": 0,
        })
        entry[row["status"]] = round(entry[row["status"]] + row["quantity"], QUANTITY_DECIMALS)
        entry["total"] = round(entry["total"] + row["quantity"], QUANTITY_DECIMALS)
        entry["stock_value"] = round(entry["stock_value"] + row["stock_value"], 2)
    return list(summary.values())


def available_quantity(product_id):
    """Quantity that may be promised to customers (unrestricted stock only)."""
    return round(sum(
        row["quantity"] for row in list_stock(product_id=product_id)
        if row["status"] == AVAILABLE_STATUS
    ), QUANTITY_DECIMALS)


def list_movements(product_id=None, bin_id=None, limit=500):
    """Return movements, newest first, with bin codes and product names."""
    conditions, params = [], []
    if product_id is not None:
        conditions.append("m.product_id = ?")
        params.append(product_id)
    if bin_id is not None:
        conditions.append("(m.from_bin_id = ? OR m.to_bin_id = ?)")
        params.extend([bin_id, bin_id])
    sql = """
        SELECT m.movement_id, m.created_at, m.movement_type, m.product_id,
               p.name AS product_name, fb.bin_code AS from_bin, tb.bin_code AS to_bin,
               m.quantity, m.reason, m.reference, m.created_by
        FROM stock_movements AS m
        JOIN products AS p ON p.product_id = m.product_id
        LEFT JOIN storage_bins AS fb ON fb.bin_id = m.from_bin_id
        LEFT JOIN storage_bins AS tb ON tb.bin_id = m.to_bin_id
    """
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY m.movement_id DESC LIMIT ?"
    params.append(limit)
    connection = get_connection()
    try:
        return [dict(r) for r in connection.execute(sql, params).fetchall()]
    finally:
        connection.close()


def check_stock_against_ledger():
    """Rebuild stock from the movement ledger and compare it with the stock table.

    Return a list of mismatches (empty list = stock and ledger agree).
    """
    connection = get_connection()
    try:
        ledger = connection.execute(
            """
            SELECT product_id, bin_id, ROUND(SUM(qty), 3) AS quantity FROM (
                SELECT product_id, to_bin_id AS bin_id, quantity AS qty
                FROM stock_movements WHERE to_bin_id IS NOT NULL
                UNION ALL
                SELECT product_id, from_bin_id, -quantity
                FROM stock_movements WHERE from_bin_id IS NOT NULL
            )
            GROUP BY product_id, bin_id
            """
        ).fetchall()
        stock = connection.execute(
            "SELECT product_id, bin_id, quantity FROM stock"
        ).fetchall()
    finally:
        connection.close()

    expected = {(r["product_id"], r["bin_id"]): r["quantity"] for r in ledger if r["quantity"] != 0}
    actual = {(r["product_id"], r["bin_id"]): r["quantity"] for r in stock}
    mismatches = []
    for key in sorted(set(expected) | set(actual)):
        if round(expected.get(key, 0) - actual.get(key, 0), QUANTITY_DECIMALS) != 0:
            mismatches.append({
                "product_id": key[0], "bin_id": key[1],
                "ledger_quantity": expected.get(key, 0),
                "stock_quantity": actual.get(key, 0),
            })
    return mismatches
