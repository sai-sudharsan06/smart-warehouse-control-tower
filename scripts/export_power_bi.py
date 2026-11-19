"""Export the warehouse data as CSV files for the Power BI report.

    python scripts/export_power_bi.py                        # your own data
    $env:WAREHOUSE_DB = "data/demo_warehouse.db"; python scripts/export_power_bi.py

Files go to exports/power_bi/ (overwritten each time). See docs/POWER_BI_GUIDE.md.
"""
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from warehouse import database  # noqa: E402
from warehouse.analytics import export_for_power_bi  # noqa: E402

if __name__ == "__main__":
    folder = PROJECT_DIR / "exports" / "power_bi"
    for path in export_for_power_bi(folder):
        print(f"wrote {path.relative_to(PROJECT_DIR)}")
    print(f"Source database: {database.DB_PATH}")
