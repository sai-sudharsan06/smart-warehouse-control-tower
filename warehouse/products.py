import sqlite3

from warehouse.database import get_connection

# Allowed values (simplified versions of SAP material types and units)
CATEGORIES = [
    "Raw Material",
    "Semi-Finished Good",
    "Finished Good",
    "Spare Part",
    "Packaging",
    "Consumable",
]
UNITS_OF_MEASURE = ["EA", "KG", "L", "M", "BOX", "PAL"]
MAX_NAME_LENGTH = 100
MAX_LEAD_TIME_DAYS = 365


def clean_text(text):
    """Remove spaces at both ends and turn repeated spaces into one."""
    return " ".join(text.split())


def format_product_id(product_id):
    """Turn a database ID such as 7 into a display ID such as MAT-00007."""
    return f"MAT-{product_id:05d}"


def validate_product(name, category, unit_of_measure, unit_cost,
                     supplier_name, lead_time_days):
    """Check product data. Return a list of error messages (empty = valid)."""
    errors = []

    if not name or not name.strip():
        errors.append("Product name is required.")
    elif len(name.strip()) > MAX_NAME_LENGTH:
        errors.append(f"Product name must be at most {MAX_NAME_LENGTH} characters.")

    if category not in CATEGORIES:
        errors.append(f"Category must be one of: {', '.join(CATEGORIES)}.")

    if unit_of_measure not in UNITS_OF_MEASURE:
        errors.append(f"Unit of measure must be one of: {', '.join(UNITS_OF_MEASURE)}.")

    if unit_cost < 0:
        errors.append("Unit cost cannot be negative.")

    if not supplier_name or not supplier_name.strip():
        errors.append("Supplier name is required.")

    if lead_time_days < 0:
        errors.append("Lead time cannot be negative.")
    elif lead_time_days > MAX_LEAD_TIME_DAYS:
        errors.append(f"Lead time must be at most {MAX_LEAD_TIME_DAYS} days.")

    return errors


def add_product(name, category, unit_of_measure, unit_cost,
                supplier_name, lead_time_days):
    """Validate and save a new product. Return its new product_id."""
    errors = validate_product(name, category, unit_of_measure, unit_cost,
                              supplier_name, lead_time_days)
    if errors:
        raise ValueError(" ".join(errors))

    connection = get_connection()
    try:
        with connection:
            cursor = connection.execute(
                """
                INSERT INTO products
                    (name, category, unit_of_measure, unit_cost,
                     supplier_name, lead_time_days)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (clean_text(name), category, unit_of_measure, round(unit_cost, 2),
                 clean_text(supplier_name), lead_time_days),
            )
        return cursor.lastrowid
    except sqlite3.IntegrityError as error:
        if "UNIQUE" in str(error):
            raise ValueError(f"A product named '{name.strip()}' already exists.")
        raise
    finally:
        connection.close()


def list_products(search_text=""):
    """Return products, oldest first.

    If search_text is given, return only products whose product ID,
    name, category or supplier contains it (not case-sensitive).
    """
    sql = """
        SELECT product_id, name, category, unit_of_measure, unit_cost,
                supplier_name, lead_time_days, created_at, updated_at
        FROM products
    """
    parameters = []

    text = search_text.strip()
    if text:
        sql += """
        WHERE printf('MAT-%05d', product_id) LIKE ?
           OR name LIKE ?
           OR category LIKE ?
           OR supplier_name LIKE ?
        """
        parameters = [f"%{text}%"] * 4

    sql += " ORDER BY product_id"

    connection = get_connection()
    try:
        rows = connection.execute(sql, parameters).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def get_product(product_id):
    """Return one product as a dictionary, or None if it does not exist."""
    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT product_id, name, category, unit_of_measure, unit_cost,
                   supplier_name, lead_time_days, created_at, updated_at
            FROM products
            WHERE product_id = ?
            """,
            (product_id,),
        ).fetchone()
    finally:
        connection.close()
    return dict(row) if row else None


def update_product(product_id, name, category, unit_of_measure, unit_cost,
                   supplier_name, lead_time_days, changed_by):
    """Validate and save changes to a product, recording each changed field.

    Return the number of fields that changed (0 means nothing was saved).
    """
    errors = validate_product(name, category, unit_of_measure, unit_cost,
                              supplier_name, lead_time_days)
    if not changed_by or not changed_by.strip():
        errors.append("User name is required to change a product.")
    if errors:
        raise ValueError(" ".join(errors))

    new_values = {
        "name": clean_text(name),
        "category": category,
        "unit_of_measure": unit_of_measure,
        "unit_cost": round(unit_cost, 2),
        "supplier_name": clean_text(supplier_name),
        "lead_time_days": lead_time_days,
    }

    connection = get_connection()
    try:
        with connection:
            old = connection.execute(
                """
                SELECT name, category, unit_of_measure, unit_cost,
                       supplier_name, lead_time_days
                FROM products
                WHERE product_id = ?
                """,
                (product_id,),
            ).fetchone()
            if old is None:
                raise ValueError(f"Product {format_product_id(product_id)} does not exist.")

            changed_fields = [f for f in new_values if old[f] != new_values[f]]
            if not changed_fields:
                return 0

            connection.execute(
                """
                UPDATE products
                SET name = ?,
                    category = ?,
                    unit_of_measure = ?,
                    unit_cost = ?,
                    supplier_name = ?,
                    lead_time_days = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE product_id = ?
                """,
                (new_values["name"], category, unit_of_measure,
                 new_values["unit_cost"], new_values["supplier_name"],
                 lead_time_days, product_id),
            )
            for field in changed_fields:
                connection.execute(
                    """
                    INSERT INTO product_changes
                        (product_id, field_name, old_value, new_value, changed_by)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (product_id, field, str(old[field]), str(new_values[field]),
                     changed_by.strip()),
                )
        return len(changed_fields)
    except sqlite3.IntegrityError as error:
        if "UNIQUE" in str(error):
            raise ValueError(f"A product named '{new_values['name']}' already exists.")
        raise
    finally:
        connection.close()


def get_product_history(product_id):
    """Return the change history of one product, newest first."""
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT changed_at, changed_by, field_name, old_value, new_value
            FROM product_changes
            WHERE product_id = ?
            ORDER BY change_id DESC
            """,
            (product_id,),
        ).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]