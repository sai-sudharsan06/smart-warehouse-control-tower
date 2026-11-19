"""Physical stock counts, discrepancies and approved adjustments.

Physical stock (what was counted) is stored separately from system stock
(what the `stock` table says). A difference never changes stock by itself:
it becomes a count adjustment movement, either automatically when it is
within tolerance, or after a second person approves it.
"""
from warehouse.database import get_connection
from warehouse.inventory import QUANTITY_DECIMALS, list_movements, post_movement
from warehouse.products import clean_text

REASONS = [
    "Counting error suspected",
    "Movement not posted",
    "Stock in wrong bin",
    "Damaged during handling",
    "Supplier delivered a different quantity",
    "Other",
]
# Differences inside BOTH limits are adjusted without approval.
TOLERANCE_VALUE_EUR = 50.0
TOLERANCE_PERCENT = 5.0


def format_count_id(count_id):
    return f"CNT-{count_id:05d}"


def needs_approval(system_quantity, difference, difference_value):
    """True if a difference is too large to adjust without a second person."""
    if difference == 0:
        return False
    if abs(difference_value) > TOLERANCE_VALUE_EUR:
        return True
    if system_quantity == 0:
        return True  # stock found where the system had none: always check
    return abs(difference) / system_quantity * 100 > TOLERANCE_PERCENT


def _post_adjustment(connection, count, user):
    """Book the counted difference as a count adjustment movement."""
    if count["difference"] > 0:
        return post_movement(
            connection, "ADJ_IN", count["product_id"], count["difference"], user,
            to_bin_id=count["bin_id"], reason=count["reason"],
            reference=format_count_id(count["count_id"]))
    return post_movement(
        connection, "ADJ_OUT", count["product_id"], -count["difference"], user,
        from_bin_id=count["bin_id"], reason=count["reason"],
        reference=format_count_id(count["count_id"]))


def record_count(product_id, bin_id, counted_quantity, user, reason=None):
    """Record a physical count. Return (count_id, status).

    Matched: no difference. Adjusted: difference within tolerance, posted at
    once. Pending approval: difference too large, waits for a second person.
    """
    reason = clean_text(reason or "")
    if counted_quantity is None or counted_quantity < 0:
        raise ValueError("Counted quantity cannot be negative.")
    if not user or not user.strip():
        raise ValueError("User name is required to record a count.")

    counted_quantity = round(counted_quantity, QUANTITY_DECIMALS)
    connection = get_connection()
    try:
        with connection:
            product = connection.execute(
                "SELECT unit_cost FROM products WHERE product_id = ?", (product_id,)
            ).fetchone()
            if product is None:
                raise ValueError("The selected product does not exist.")
            if connection.execute(
                "SELECT 1 FROM storage_bins WHERE bin_id = ?", (bin_id,)
            ).fetchone() is None:
                raise ValueError("The selected bin does not exist.")
            row = connection.execute(
                "SELECT quantity FROM stock WHERE product_id = ? AND bin_id = ?",
                (product_id, bin_id),
            ).fetchone()
            system_quantity = row["quantity"] if row else 0
            difference = round(counted_quantity - system_quantity, QUANTITY_DECIMALS)
            difference_value = round(difference * product["unit_cost"], 2)

            if difference != 0 and reason not in REASONS:
                raise ValueError("Choose a reason for the difference.")
            if difference == 0:
                status = "Matched"
            elif needs_approval(system_quantity, difference, difference_value):
                status = "Pending approval"
            else:
                status = "Adjusted"

            cursor = connection.execute(
                """
                INSERT INTO stock_counts (product_id, bin_id, system_quantity,
                    counted_quantity, difference, difference_value, reason, status,
                    counted_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (product_id, bin_id, system_quantity, counted_quantity, difference,
                 difference_value, reason or None, status, user.strip()),
            )
            count_id = cursor.lastrowid
            if status == "Adjusted":
                count = _get_count(connection, count_id)
                movement_id = _post_adjustment(connection, count, user)
                connection.execute(
                    """
                    UPDATE stock_counts SET movement_id = ?, decided_by = ?,
                        decided_at = CURRENT_TIMESTAMP, decision_note = ?
                    WHERE count_id = ?
                    """,
                    (movement_id, "system", "Within tolerance, adjusted automatically",
                     count_id),
                )
        return count_id, status
    finally:
        connection.close()


def _get_count(connection, count_id):
    row = connection.execute(
        "SELECT * FROM stock_counts WHERE count_id = ?", (count_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"Count {format_count_id(count_id)} does not exist.")
    return dict(row)


def decide_count(count_id, approve, user, note):
    """Approve (post the adjustment) or reject a pending count.

    The approver must be a different person from the counter, and system
    stock must not have changed since the count; otherwise a recount is needed.
    """
    note = clean_text(note or "")
    if not user or not user.strip():
        raise ValueError("User name is required to approve or reject.")
    if not note:
        raise ValueError("A note explaining the decision is required.")
    connection = get_connection()
    try:
        with connection:
            count = _get_count(connection, count_id)
            if count["status"] != "Pending approval":
                raise ValueError(
                    f"{format_count_id(count_id)} is {count['status']}, not pending approval.")
            if user.strip().lower() == count["counted_by"].lower():
                raise ValueError(
                    "The person who counted cannot approve their own count "
                    "(four-eyes principle).")
            movement_id = None
            if approve:
                row = connection.execute(
                    "SELECT quantity FROM stock WHERE product_id = ? AND bin_id = ?",
                    (count["product_id"], count["bin_id"]),
                ).fetchone()
                current = row["quantity"] if row else 0
                if current != count["system_quantity"]:
                    raise ValueError(
                        f"System stock changed since the count ({count['system_quantity']:g}"
                        f" then, {current:g} now). Reject this count and count again.")
                movement_id = _post_adjustment(connection, count, user)
            connection.execute(
                """
                UPDATE stock_counts SET status = ?, decided_by = ?,
                    decided_at = CURRENT_TIMESTAMP, decision_note = ?, movement_id = ?
                WHERE count_id = ?
                """,
                ("Adjusted" if approve else "Rejected", user.strip(), note,
                 movement_id, count_id),
            )
    finally:
        connection.close()


def list_counts(status=None, limit=500):
    """Return counts, newest first, with product name and bin code."""
    sql = """
        SELECT c.count_id, c.counted_at, c.product_id, p.name AS product_name,
               b.bin_code, c.system_quantity, c.counted_quantity, c.difference,
               c.difference_value, c.reason, c.status, c.counted_by,
               c.decided_by, c.decided_at, c.decision_note
        FROM stock_counts AS c
        JOIN products AS p ON p.product_id = c.product_id
        JOIN storage_bins AS b ON b.bin_id = c.bin_id
    """
    params = []
    if status:
        sql += " WHERE c.status = ?"
        params.append(status)
    sql += " ORDER BY c.count_id DESC LIMIT ?"
    params.append(limit)
    connection = get_connection()
    try:
        return [dict(r) for r in connection.execute(sql, params).fetchall()]
    finally:
        connection.close()


def inventory_accuracy():
    """Share of counts whose difference was within tolerance (incl. exact matches).

    Return (percent, number_of_counts); percent is None when nothing was counted.
    """
    counts = list_counts(limit=1_000_000)
    if not counts:
        return None, 0
    within = sum(
        1 for c in counts
        if not needs_approval(c["system_quantity"], c["difference"], c["difference_value"])
    )
    return round(within / len(counts) * 100, 1), len(counts)


def investigation_hints(count_id):
    """Neutral, data-based hints for investigating a difference.

    These point at processes and records to check. They never name or blame
    a person: a difference has many possible causes, most of them honest.
    """
    connection = get_connection()
    try:
        count = _get_count(connection, count_id)
        other_bins = connection.execute(
            """
            SELECT b.bin_code, s.quantity FROM stock AS s
            JOIN storage_bins AS b ON b.bin_id = s.bin_id
            WHERE s.product_id = ? AND s.bin_id != ?
            ORDER BY b.bin_code
            """,
            (count["product_id"], count["bin_id"]),
        ).fetchall()
    finally:
        connection.close()

    hints = []
    if count["difference"] == 0:
        return ["No difference. Nothing to investigate."]
    recent = list_movements(product_id=count["product_id"], bin_id=count["bin_id"], limit=10)
    if recent:
        hints.append(
            f"{len(recent)} recent movement(s) in this bin for this product. Check "
            "that each one physically happened as posted (quantity and bin).")
    else:
        hints.append("No movements recorded in this bin for this product.")
    if count["difference"] < 0:
        if other_bins:
            codes = ", ".join(f"{b['bin_code']} ({b['quantity']:g})" for b in other_bins)
            hints.append(f"Less found than expected. The product is also stored in: "
                         f"{codes}. Check whether stock was put into a neighbouring bin.")
        hints.append("Check for picks or issues that were done physically but not posted.")
    else:
        hints.append("More found than expected. Check for a receipt or putaway that was "
                     "done physically but not posted, or stock placed in the wrong bin.")
    hints.append("Recount before adjusting if the counter is unsure. A counting error is "
                 "one of the most common causes of a difference.")
    return hints
