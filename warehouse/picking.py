"""Pick lists, walking-route optimisation, picking and shipping.

Layout model (simplified, stated openly): every Storage or Picking zone is one
aisle, ordered by zone code. All aisles have the same length and connect a
front cross-aisle (where the depot / shipping area sits) with a rear
cross-aisle. Rack r lies r x RACK_WIDTH_M metres into its aisle. Pickers walk
along aisles and cross-aisles only (no shortcuts through racks), so moving to
another aisle goes via the front or the rear, whichever is shorter.
Rack level (height) does not change walking distance.

All distances are those of this simulated layout, not measured in a real hall.
"""
from itertools import permutations

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from warehouse.database import get_connection
from warehouse.inventory import QUANTITY_DECIMALS, post_movement
from warehouse.orders import format_order_id, get_order, get_order_lines

PICK_ZONE_TYPES = ("Picking", "Storage")
RACK_WIDTH_M = 2.5
AISLE_SPACING_M = 6.0
SOLVER_TIME_LIMIT_MS = 1000  # search time per route; the demo generator lowers it


# ---- Layout and distances ----

def _aisle_positions(connection):
    """{zone_id: y position of its aisle}, aisles ordered by zone code."""
    placeholders = ", ".join("?" for _ in PICK_ZONE_TYPES)
    rows = connection.execute(
        f"SELECT zone_id FROM zones WHERE zone_type IN ({placeholders}) ORDER BY zone_code",
        PICK_ZONE_TYPES,
    ).fetchall()
    return {row["zone_id"]: (i + 1) * AISLE_SPACING_M for i, row in enumerate(rows)}


def aisle_length(connection):
    """Length of every aisle: one rack width beyond the deepest rack in use."""
    placeholders = ", ".join("?" for _ in PICK_ZONE_TYPES)
    deepest = connection.execute(
        f"""
        SELECT COALESCE(MAX(b.rack), 0) FROM storage_bins AS b
        JOIN zones AS z ON z.zone_id = b.zone_id WHERE z.zone_type IN ({placeholders})
        """,
        PICK_ZONE_TYPES,
    ).fetchone()[0]
    return (deepest + 1) * RACK_WIDTH_M


def walking_distance(a, b, length=None):
    """Distance between two points (aisle_y, depth_x) in the aisle layout.

    Same aisle: walk along it. Different aisles: walk to the front cross-aisle
    (depth 0) or, if the layout has one, the rear cross-aisle (depth `length`),
    whichever is shorter, along it, and into the other aisle. Depot = (0, 0).
    """
    (y1, x1), (y2, x2) = a, b
    if y1 == y2:
        return abs(x1 - x2)
    via_front = x1 + x2
    if length is None:
        return via_front + abs(y1 - y2)
    via_rear = (length - x1) + (length - x2)
    return min(via_front, via_rear) + abs(y1 - y2)


def route_length(points, length=None):
    """Length of a round trip depot -> points in order -> depot."""
    path = [(0.0, 0.0), *points, (0.0, 0.0)]
    return round(sum(walking_distance(path[i], path[i + 1], length)
                     for i in range(len(path) - 1)), 1)


def naive_sequence(stops):
    """Baseline: visit bins in bin-code order (how a printed list is often sorted)."""
    return sorted(range(len(stops)), key=lambda i: stops[i]["bin_code"])


def optimised_sequence(points, length=None):
    """Shortest round trip found by OR-Tools (travelling salesman with a depot).

    Return the visiting order as indexes into `points`.
    """
    if len(points) <= 1:
        return list(range(len(points)))
    nodes = [(0.0, 0.0), *points]
    # OR-Tools works with whole numbers: use decimetres.
    matrix = [[int(round(walking_distance(a, b, length) * 10)) for b in nodes]
              for a in nodes]
    manager = pywrapcp.RoutingIndexManager(len(nodes), 1, 0)
    routing = pywrapcp.RoutingModel(manager)

    def distance(from_index, to_index):
        return matrix[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

    transit = routing.RegisterTransitCallback(distance)
    routing.SetArcCostEvaluatorOfAllVehicles(transit)
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH)
    params.time_limit.FromMilliseconds(SOLVER_TIME_LIMIT_MS)
    solution = routing.SolveWithParameters(params)
    if solution is None:
        raise RuntimeError("OR-Tools found no route.")
    order, index = [], routing.Start(0)
    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        if node != 0:
            order.append(node - 1)
        index = solution.Value(routing.NextVar(index))
    return order


def brute_force_sequence(points, length=None):
    """Exact shortest round trip by trying every order. Only for few stops (tests)."""
    best = min(permutations(range(len(points))),
               key=lambda p: route_length([points[i] for i in p], length))
    return list(best)


# ---- Pick lists ----

def _allocate(connection, product_id, quantity, aisles):
    """Choose bins to pick from: Picking zone first, then bins with most stock.

    Return a list of dicts with bin_id, bin_code, quantity and point.
    """
    placeholders = ", ".join("?" for _ in PICK_ZONE_TYPES)
    rows = connection.execute(
        f"""
        SELECT s.bin_id, b.bin_code, b.rack, b.zone_id, z.zone_type,
               s.quantity - COALESCE(open_tasks.planned, 0) AS quantity
        FROM stock AS s
        JOIN storage_bins AS b ON b.bin_id = s.bin_id
        JOIN zones AS z ON z.zone_id = b.zone_id
        LEFT JOIN (
            -- stock already planned for other open pick lists stays in the bin
            -- until it is picked, so it must not be allocated twice
            SELECT bin_id, SUM(quantity) AS planned FROM pick_tasks
            WHERE product_id = ? AND status = 'Open' GROUP BY bin_id
        ) AS open_tasks ON open_tasks.bin_id = s.bin_id
        WHERE s.product_id = ? AND b.is_blocked = 0 AND z.zone_type IN ({placeholders})
          AND s.quantity - COALESCE(open_tasks.planned, 0) > 0
        ORDER BY CASE z.zone_type WHEN 'Picking' THEN 0 ELSE 1 END,
                 quantity DESC, b.bin_code
        """,
        (product_id, product_id, *PICK_ZONE_TYPES),
    ).fetchall()
    picks, remaining = [], quantity
    for row in rows:
        if remaining <= 0:
            break
        take = round(min(remaining, row["quantity"]), QUANTITY_DECIMALS)
        picks.append({
            "bin_id": row["bin_id"], "bin_code": row["bin_code"], "quantity": take,
            "point": (aisles[row["zone_id"]], row["rack"] * RACK_WIDTH_M),
        })
        remaining = round(remaining - take, QUANTITY_DECIMALS)
    if remaining > 0:
        raise ValueError("Not enough pickable stock in unblocked bins.")
    return picks


def create_pick_list(order_id, user, optimise=True):
    """Create pick tasks for a released order, in walking-route order.

    Return a dict with the method, the route distance and the bin-code-order
    distance for comparison.
    """
    if not user or not user.strip():
        raise ValueError("User name is required to create a pick list.")
    order = get_order(order_id)
    if order["status"] != "Released":
        raise ValueError(f"{format_order_id(order_id)} is {order['status']}; only "
                         "released orders can be picked.")
    connection = get_connection()
    try:
        with connection:
            if connection.execute(
                "SELECT 1 FROM pick_tasks WHERE order_id = ?", (order_id,)
            ).fetchone():
                raise ValueError(f"{format_order_id(order_id)} already has a pick list.")
            aisles = _aisle_positions(connection)
            length = aisle_length(connection)
            stops = []
            for line in get_order_lines(order_id):
                for pick in _allocate(connection, line["product_id"], line["quantity"], aisles):
                    stops.append({**pick, "line_id": line["line_id"],
                                  "product_id": line["product_id"]})
            points = [s["point"] for s in stops]
            naive = naive_sequence(stops)
            sequence = optimised_sequence(points, length) if optimise else naive
            distance = route_length([points[i] for i in sequence], length)
            naive_distance = route_length([points[i] for i in naive], length)
            for position, index in enumerate(sequence, start=1):
                stop = stops[index]
                connection.execute(
                    """
                    INSERT INTO pick_tasks (order_id, line_id, product_id, bin_id,
                                            quantity, sequence, created_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (order_id, stop["line_id"], stop["product_id"], stop["bin_id"],
                     stop["quantity"], position, user.strip()),
                )
            method = "OR-Tools route" if optimise else "Bin code order"
            connection.execute(
                "INSERT INTO pick_routes (order_id, method, distance_m, naive_distance_m) "
                "VALUES (?, ?, ?, ?)",
                (order_id, method, distance, naive_distance),
            )
        return {"method": method, "distance_m": distance, "naive_distance_m": naive_distance}
    finally:
        connection.close()


def get_pick_list(order_id):
    connection = get_connection()
    try:
        tasks = connection.execute(
            """
            SELECT t.task_id, t.sequence, b.bin_code, t.product_id, p.name AS product_name,
                   t.quantity, p.unit_of_measure, t.status, t.picked_by
            FROM pick_tasks AS t
            JOIN storage_bins AS b ON b.bin_id = t.bin_id
            JOIN products AS p ON p.product_id = t.product_id
            WHERE t.order_id = ? ORDER BY t.sequence
            """,
            (order_id,),
        ).fetchall()
        route = connection.execute(
            "SELECT * FROM pick_routes WHERE order_id = ?", (order_id,)
        ).fetchone()
    finally:
        connection.close()
    return [dict(t) for t in tasks], dict(route) if route else None


def confirm_picking(order_id, shipping_bin_id, user):
    """Confirm all pick tasks: move the stock to the shipping bin, order -> Picked.

    All tasks are confirmed in one transaction. If one bin no longer holds
    enough stock, nothing is booked (partial picking is not supported).
    """
    if not user or not user.strip():
        raise ValueError("User name is required to confirm picking.")
    connection = get_connection()
    try:
        with connection:
            zone = connection.execute(
                """
                SELECT z.zone_type FROM storage_bins AS b
                JOIN zones AS z ON z.zone_id = b.zone_id WHERE b.bin_id = ?
                """,
                (shipping_bin_id,),
            ).fetchone()
            if zone is None or zone["zone_type"] != "Shipping":
                raise ValueError("Picked goods must go to a bin in a Shipping zone.")
            order = connection.execute(
                "SELECT status FROM sales_orders WHERE order_id = ?", (order_id,)
            ).fetchone()
            if order is None or order["status"] != "Released":
                raise ValueError(f"{format_order_id(order_id)} is not released.")
            tasks = connection.execute(
                "SELECT * FROM pick_tasks WHERE order_id = ? AND status = 'Open' "
                "ORDER BY sequence",
                (order_id,),
            ).fetchall()
            if not tasks:
                raise ValueError("This order has no open pick tasks.")
            for task in tasks:
                movement_id = post_movement(
                    connection, "PICK", task["product_id"], task["quantity"], user,
                    from_bin_id=task["bin_id"], to_bin_id=shipping_bin_id,
                    reference=format_order_id(order_id))
                connection.execute(
                    """
                    UPDATE pick_tasks SET status = 'Picked', picked_by = ?,
                        picked_at = CURRENT_TIMESTAMP, movement_id = ?
                    WHERE task_id = ?
                    """,
                    (user.strip(), movement_id, task["task_id"]),
                )
                connection.execute(
                    "UPDATE sales_order_lines SET picked_quantity = picked_quantity + ? "
                    "WHERE line_id = ?",
                    (task["quantity"], task["line_id"]),
                )
            connection.execute(
                "UPDATE sales_orders SET status = 'Picked' WHERE order_id = ?", (order_id,))
    finally:
        connection.close()


def ship_order(order_id, user):
    """Post goods issue from the shipping bin(s) and close the order as Shipped."""
    if not user or not user.strip():
        raise ValueError("User name is required to ship an order.")
    connection = get_connection()
    try:
        with connection:
            order = connection.execute(
                "SELECT status FROM sales_orders WHERE order_id = ?", (order_id,)
            ).fetchone()
            if order is None or order["status"] != "Picked":
                raise ValueError(f"{format_order_id(order_id)} must be Picked before shipping.")
            picks = connection.execute(
                """
                SELECT m.product_id, m.to_bin_id, SUM(m.quantity) AS quantity
                FROM pick_tasks AS t JOIN stock_movements AS m ON m.movement_id = t.movement_id
                WHERE t.order_id = ? GROUP BY m.product_id, m.to_bin_id
                """,
                (order_id,),
            ).fetchall()
            for pick in picks:
                post_movement(connection, "GI", pick["product_id"], pick["quantity"], user,
                              from_bin_id=pick["to_bin_id"],
                              reference=format_order_id(order_id))
            connection.execute(
                """
                UPDATE sales_orders SET status = 'Shipped', closed_by = ?,
                    closed_at = CURRENT_TIMESTAMP WHERE order_id = ?
                """,
                (user.strip(), order_id),
            )
    finally:
        connection.close()


def route_statistics():
    """Total route distance versus bin-code order over all pick lists."""
    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT COUNT(*) AS pick_lists, COALESCE(SUM(distance_m), 0) AS distance_m,
                   COALESCE(SUM(naive_distance_m), 0) AS naive_distance_m
            FROM pick_routes
            """
        ).fetchone()
    finally:
        connection.close()
    return dict(row)
