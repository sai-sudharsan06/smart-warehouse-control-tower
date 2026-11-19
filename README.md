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

**Warehouse structure**
- Define zones by purpose: receiving, storage, picking, shipping, quarantine
  and damaged goods.
- Create storage bins one at a time or a whole rack and level range at once.
  The system generates every bin code (`A-01-02` = zone A, rack 1, level 2),
  so there are no hand-typed variants of the same location.

**Goods receiving**
- Post goods receipts against a delivery note, into a receiving bin, or
  straight into quarantine or damaged goods if the delivery fails the check.
- Put goods away with a suggested bin: one that already holds the product,
  otherwise the first empty storage bin.

**Inventory**
- Stock per product and bin, with its status. Only stock in storage and
  picking zones counts as available. Quarantined and damaged stock never does.
- Move stock between bins by typing or scanning bin codes.
- A movement ledger records every change with source bin, destination bin,
  quantity, user and time.
- A ledger check rebuilds all stock from the movements and reports any
  difference, which would mean stock was changed without a movement.

## How it is built

- **Two layers of validation.** Python checks give the user clear messages,
  and database constraints act as the last line of defence.
- **Changes and their history are saved in one database transaction.** Either
  both are saved or neither is, so the history can never drift out of sync.
- **Stock changes only through one function** that writes the movement and
  the stock change together, and refuses negative stock, blocked bins and
  moving more than is in a bin.
- **Parameterised SQL queries** throughout, which protects against SQL injection.
- **Business logic separated from the user interface.** The rules in
  `warehouse/` are tested without opening the app.
- **86 automated tests** (pytest), run against a temporary database so real
  data is never touched.

## Project structure

```
app.py                      entry point and navigation
app_pages/                  one screen per business process
warehouse/
  database.py               database connection and table definitions
  products.py               product validation, search, edit, change history
  locations.py              zones, bins and bin codes
  inventory.py              stock, movements, availability, ledger check
  receiving.py              goods receipts and putaway suggestions
  labels.py                 readable dropdown labels
tests/                      pytest tests on a temporary database
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
- Bin capacity (size, weight) is not modelled yet.

## Technology

Python 3.13 · Streamlit · SQLite · Pandas · pytest
