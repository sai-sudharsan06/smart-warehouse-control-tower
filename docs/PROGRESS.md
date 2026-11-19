# Project progress log

## Completed

### Setup (2026-11-19)
- Development environment checked
- Python 3.13.17 installed for the project (Google OR-Tools has no build for Python 3.15 yet)
- Project folder outside OneDrive, virtual environment, folder structure, Git repository

### Module 1: Product Master Data (2026-11-19)
- `products` table with database constraints: unique name (case-insensitive),
  cost and lead time not negative, required fields
- System-assigned product IDs, displayed as `MAT-00001`
- Input validation in Python (`validate_product`) shared by create and edit
- Register, list, search (ID, name, category, supplier) and edit products
- Text cleaning: leading, trailing and repeated spaces are removed
- Field-level change history (`product_changes` table): field, old value,
  new value, user, timestamp, written in the same transaction as the change
- Foreign key from `product_changes` to `products`, enforced
- Automated tests: 32 (7 validation, 25 database), run against a temporary
  database so real data is never touched

## In progress
- Module 1 close-out: process diagram (Draw.io), screenshots

## Remaining modules
2. Warehouse Structure Management
3. Inventory Management
4. Goods Receiving
5. Barcode and Movement Tracking
6. Stock Discrepancy Investigation
7. Order Management
8. Picking and Route Optimisation
9. Inventory Optimisation
10. Demand Forecasting
11. Warehouse Analytics
12. Management Control Tower

## Known limitations
- **No real login.** The "current user" is typed in the sidebar and is not
  authenticated. Real systems take the user from the login.
- **Unit cost is stored as a floating-point number (REAL)** and rounded to
  2 decimals. Enterprise systems use exact decimal types for money.
- **Product creation is not in the change history** (only edits are).
  `created_at` records when, but not who.
- **Products cannot be deactivated from the screen yet.** The `is_active`
  column exists, but no screen uses it.
- **Search treats `%` and `_` as wildcards** (SQL `LIKE` behaviour).
- **After renaming a product, the edit dropdown shows the old name** until the
  next click. The database and the product table are correct immediately.
- **Timestamps are stored in UTC** and shown in UTC (one hour behind German
  winter time).
- **Changes made before the change history existed are not recorded.**
