"""Customer orders with an availability check (ATP) before release.

Available to promise (ATP) = unrestricted stock - quantity already reserved
by released orders that are not yet picked. Quarantined, blocked, receiving
and shipping stock is never promised.
"""
from datetime import date

from warehouse.database import get_connection
from warehouse.inventory import QUANTITY_DECIMALS, available_quantity
from warehouse.products import clean_text

PRIORITIES = ["Normal", "Urgent"]
RESERVING_STATUSES = ("Released",)
MAX_CUSTOMER_LENGTH = 80


def format_order_id(order_id):
    return f"SO-{order_id:05d}"


def create_order(customer_name, requested_date, priority, lines, user, today=None):
    """Create an open order. `lines` is a list of (product_id, quantity).

    Return the order ID. Stock is not reserved until the order is released.
    """
    today = today or date.today()
    customer = clean_text(customer_name or "")
    errors = []
    if not customer:
        errors.append("Customer name is required.")
    elif len(customer) > MAX_CUSTOMER_LENGTH:
        errors.append(f"Customer name must be at most {MAX_CUSTOMER_LENGTH} characters.")
    if not isinstance(requested_date, date):
        errors.append("Requested delivery date is required.")
    elif requested_date < today:
        errors.append("Requested delivery date cannot be in the past.")
    if priority not in PRIORITIES:
        errors.append(f"Priority must be one of: {', '.join(PRIORITIES)}.")
    if not user or not user.strip():
        errors.append("User name is required to create an order.")
    clean_lines = [(pid, qty) for pid, qty in lines if pid is not None]
    if not clean_lines:
        errors.append("An order needs at least one line.")
    if any(qty is None or qty <= 0 for _, qty in clean_lines):
        errors.append("Every line needs a quantity greater than zero.")
    product_ids = [pid for pid, _ in clean_lines]
    if len(product_ids) != len(set(product_ids)):
        errors.append("Each product may appear only once per order.")
    if errors:
        raise ValueError(" ".join(errors))

    connection = get_connection()
    try:
        with connection:
            for pid in product_ids:
                if connection.execute(
                    "SELECT 1 FROM products WHERE product_id = ?", (pid,)
                ).fetchone() is None:
                    raise ValueError(f"Product {pid} does not exist.")
            cursor = connection.execute(
                """
                INSERT INTO sales_orders (customer_name, requested_date, priority, created_by)
                VALUES (?, ?, ?, ?)
                """,
                (customer, requested_date.isoformat(), priority, user.strip()),
            )
            order_id = cursor.lastrowid
            for pid, qty in clean_lines:
                connection.execute(
                    "INSERT INTO sales_order_lines (order_id, product_id, quantity) "
                    "VALUES (?, ?, ?)",
                    (order_id, pid, round(qty, QUANTITY_DECIMALS)),
                )
        return order_id
    finally:
        connection.close()


def list_orders(status=None):
    """Return orders, most urgent and earliest requested first."""
    sql = """
        SELECT o.order_id, o.customer_name, o.requested_date, o.priority, o.status,
               COUNT(l.line_id) AS lines, o.created_by, o.created_at,
               o.released_by, o.released_at, o.closed_at, o.cancel_reason
        FROM sales_orders AS o
        LEFT JOIN sales_order_lines AS l ON l.order_id = o.order_id
    """
    params = []
    if status:
        sql += " WHERE o.status = ?"
        params.append(status)
    sql += """
        GROUP BY o.order_id
        ORDER BY CASE o.priority WHEN 'Urgent' THEN 0 ELSE 1 END,
                 o.requested_date, o.order_id
    """
    connection = get_connection()
    try:
        return [dict(r) for r in connection.execute(sql, params).fetchall()]
    finally:
        connection.close()


def get_order(order_id):
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT * FROM sales_orders WHERE order_id = ?", (order_id,)
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise ValueError(f"Order {format_order_id(order_id)} does not exist.")
    return dict(row)


def get_order_lines(order_id):
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT l.line_id, l.product_id, p.name AS product_name, p.unit_of_measure,
                   l.quantity, l.picked_quantity
            FROM sales_order_lines AS l JOIN products AS p ON p.product_id = l.product_id
            WHERE l.order_id = ? ORDER BY l.line_id
            """,
            (order_id,),
        ).fetchall()
    finally:
        connection.close()
    return [dict(r) for r in rows]


def reserved_quantity(product_id, exclude_order_id=None):
    """Quantity promised to released orders and not yet picked."""
    placeholders = ", ".join("?" for _ in RESERVING_STATUSES)
    sql = f"""
        SELECT COALESCE(SUM(l.quantity - l.picked_quantity), 0) AS reserved
        FROM sales_order_lines AS l JOIN sales_orders AS o ON o.order_id = l.order_id
        WHERE l.product_id = ? AND o.status IN ({placeholders})
    """
    params = [product_id, *RESERVING_STATUSES]
    if exclude_order_id is not None:
        sql += " AND o.order_id != ?"
        params.append(exclude_order_id)
    connection = get_connection()
    try:
        return round(connection.execute(sql, params).fetchone()["reserved"], QUANTITY_DECIMALS)
    finally:
        connection.close()


def available_to_promise(product_id, exclude_order_id=None):
    return round(
        available_quantity(product_id) - reserved_quantity(product_id, exclude_order_id),
        QUANTITY_DECIMALS,
    )


def check_order(order_id):
    """Availability per line: requested, available to promise and shortage."""
    result = []
    for line in get_order_lines(order_id):
        atp = available_to_promise(line["product_id"], exclude_order_id=order_id)
        result.append({
            **line,
            "available_to_promise": atp,
            "shortage": round(max(0, line["quantity"] - atp), QUANTITY_DECIMALS),
        })
    return result


def release_order(order_id, user):
    """Release an open order for picking, reserving its stock.

    Only complete orders are released: if any line is short, nothing changes.
    BEGIN IMMEDIATE takes the database write lock first, so two releases
    cannot both promise the same stock.
    """
    if not user or not user.strip():
        raise ValueError("User name is required to release an order.")
    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        try:
            order = get_order(order_id)
            if order["status"] != "Open":
                raise ValueError(
                    f"{format_order_id(order_id)} is {order['status']}, not Open.")
            short = [line for line in check_order(order_id) if line["shortage"] > 0]
            if short:
                details = "; ".join(
                    f"{line['product_name']}: short {line['shortage']:g} "
                    f"{line['unit_of_measure']}" for line in short)
                raise ValueError(f"Not enough available stock. {details}.")
            connection.execute(
                """
                UPDATE sales_orders SET status = 'Released', released_by = ?,
                    released_at = CURRENT_TIMESTAMP
                WHERE order_id = ?
                """,
                (user.strip(), order_id),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    finally:
        connection.close()


def cancel_order(order_id, user, reason):
    """Cancel an open or released order (releases its reservation)."""
    reason = clean_text(reason or "")
    if not reason:
        raise ValueError("A cancellation reason is required.")
    if not user or not user.strip():
        raise ValueError("User name is required to cancel an order.")
    order = get_order(order_id)
    if order["status"] not in ("Open", "Released"):
        raise ValueError(f"{format_order_id(order_id)} is {order['status']} and cannot be cancelled.")
    if any(line["picked_quantity"] > 0 for line in get_order_lines(order_id)):
        raise ValueError("Part of this order is already picked. Return the stock first.")
    connection = get_connection()
    try:
        with connection:
            # An open pick list is only a plan: remove it with the order.
            connection.execute(
                "DELETE FROM pick_tasks WHERE order_id = ? AND status = 'Open'", (order_id,))
            connection.execute("DELETE FROM pick_routes WHERE order_id = ?", (order_id,))
            connection.execute(
                """
                UPDATE sales_orders SET status = 'Cancelled', closed_by = ?,
                    closed_at = CURRENT_TIMESTAMP, cancel_reason = ?
                WHERE order_id = ?
                """,
                (user.strip(), reason, order_id),
            )
    finally:
        connection.close()
