# Smart Warehouse, Inventory Accuracy & Intralogistics Control Tower

A warehouse management prototype for a **fictional** German manufacturing and
distribution company, built with Python, Streamlit and SQLite. All data is
synthetic. This is a portfolio prototype, not a production-ready WMS.

## The problem

In many warehouses, the stock in the system does not match the stock on the
shelf. Products are registered twice, data is entered inconsistently, and
changes happen without anyone being able to trace them. Every later decision
(replenishment, picking, stock counts) inherits these errors.

This application is built around one rule: **no data changes without
validation and a recorded history.**

## What it does

**Product master data**
- Register products with category, unit of measure, unit cost, supplier and
  lead time. The system assigns each product a unique ID (`MAT-00001`).
- Reject invalid input with clear messages, such as a negative cost, a
  lead time over 365 days or missing fields.
- Prevent duplicate products, even when the name differs only in capital
  letters or extra spaces.
- Search by product ID, name, category or supplier.
- Edit products, with a full change history: every changed field is recorded
  with its old value, new value, user and timestamp.

## How it is built

- **Two layers of validation.** Python checks give the user clear messages,
  and database constraints act as the last line of defence.
- **Changes and their history are saved in one database transaction.** Either
  both are saved or neither is, so the history can never drift out of sync.
- **Parameterised SQL queries** throughout, which protects against SQL injection.
- **Business logic separated from the user interface.** The rules in
  `warehouse/` are tested without opening the app.
- **32 automated tests** (pytest), run against a temporary database so real
  data is never touched.

## Project structure

```
app.py                      Streamlit user interface
warehouse/
  database.py               database connection and table definitions
  products.py               validation, create, search, edit, change history
tests/
  conftest.py               temporary test database
  test_products.py          validation tests
  test_product_database.py  database tests
docs/                       progress log and diagrams
```

## Run it

```powershell
py -V:3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run app.py
```

Run the tests:

```powershell
python -m pytest -v
```

## Limitations

- There is no real login. The user name is typed in and not authenticated.
- Unit cost is stored as a rounded floating-point number. Enterprise systems
  use exact decimal types for money.

## Technology

Python 3.13 · Streamlit · SQLite · Pandas · pytest
