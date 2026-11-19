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
                (name.strip(), category, unit_of_measure, round(unit_cost, 2),
                 supplier_name.strip(), lead_time_days),
            )
        return cursor.lastrowid
    except sqlite3.IntegrityError as error:
        if "UNIQUE" in str(error):
            raise ValueError(f"A product named '{name.strip()}' already exists.")
        raise
    finally:
        connection.close()