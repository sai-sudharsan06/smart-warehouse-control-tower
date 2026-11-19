# Smart Warehouse, Inventory Accuracy & Intralogistics Control Tower

A learning and portfolio prototype of a warehouse management application for a
**fictional** German manufacturing and distribution company. All data is synthetic
and all results are simulated. This is not a production-ready enterprise WMS.

## Problem addressed

System stock that does not match physical stock, misplaced products, unrecorded
movements, unexplained adjustments, inefficient picking and late replenishment.

## Technology (introduced as the project needs it)

- Python 3.13
- Streamlit (web interface)
- SQLite (database)
- Pandas (data handling)
- pytest (tests)

## Setup

```powershell
py -V:3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Status

See [docs/PROGRESS.md](docs/PROGRESS.md).
