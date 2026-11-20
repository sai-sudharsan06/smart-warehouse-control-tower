# Power BI report: step-by-step guide

You build this report yourself in Power BI Desktop. It reads the CSV files the
app exports. Plan about 2 to 3 hours the first time.

All data is synthetic. Put a text box "Synthetic data, fictional company" on
every page.

## 0. Before you start

1. Install **Power BI Desktop** (free) from the Microsoft Store.
2. Create the demo data and export it. In the VS Code terminal, with `(.venv)`
   active:
   ```powershell
   python scripts/seed_demo_data.py
   $env:WAREHOUSE_DB = "data/demo_warehouse.db"; python scripts/export_power_bi.py
   ```
   Expected: nine lines `wrote exports\power_bi\...csv`.
   (You can also use the **Export for Power BI** button on the Control tower page.)

## 1. Set the import locale (important on a German Windows)

The CSV files use a decimal **point** (`0.25`). With German regional settings,
Power BI may read `0.25` as `25`.

File → Options and settings → Options → **Current file → Regional settings** →
Locale for import: **English (United States)**. Do this before importing.

## 2. Import the nine tables

Home → Get data → **Text/CSV** → choose `exports/power_bi/dim_product.csv` →
**Transform Data** (not Load). Repeat for the other eight files:
`dim_bin`, `fact_movements`, `fact_orders`, `fact_order_lines`, `fact_counts`,
`fact_pick_routes`, `snapshot_stock`, `snapshot_planning`.

In Power Query, check the column types (icon left of each column name):

| Table | Column | Type |
|---|---|---|
| fact_movements | movement_date | Date |
| fact_orders | requested_date, created_date, closed_date | Date |
| fact_counts | count_date | Date |
| fact_pick_routes | shipped_date | Date |
| all | quantities, values, distances | Decimal number |
| snapshot_planning | reorder_now | True/False |

Then **Close & Apply**.

## 3. Add a date table

Modeling → **New table**, and paste:

```DAX
Date =
ADDCOLUMNS (
    CALENDARAUTO (),  -- covers every date found in the imported tables
    "Year", YEAR ( [Date] ),
    "Month", FORMAT ( [Date], "YYYY-MM" ),
    "Week start", [Date] - WEEKDAY ( [Date], 2 ) + 1
)
```

Select the new table → Table tools → **Mark as date table** → column `Date`.

## 4. Relationships (Model view)

**First remove the automatic ones.** Power BI creates some relationships by
itself when it loads the files, and it may link fact tables to
`snapshot_planning` instead of `dim_product`. Open **Model view** (left bar,
third icon), click each line between tables and press **Delete**, until no
lines are left. Then create exactly the ones below.

Drag a column onto the matching column in another table. All are one-to-many
(1 on the dimension side), single direction.

| From (1 side) | To (many side) |
|---|---|
| dim_product[product_id] | fact_movements, fact_order_lines, fact_counts, snapshot_stock, snapshot_planning [product_id] |
| dim_bin[bin_id] | fact_counts[bin_id], snapshot_stock[bin_id] |
| fact_orders[order_id] | fact_order_lines[order_id], fact_pick_routes[order_id] |
| Date[Date] | fact_orders[closed_date], fact_movements[movement_date], fact_counts[count_date] |

Movements have two bins (from and to). Leave them unlinked to `dim_bin` for
now. This is a common modelling question and a good interview topic.

## 5. Measures

Create a table for measures: Home → Enter data → name it `Measures` → Load.
Then select it and use Modeling → **New measure** for each:

```DAX
Orders Shipped = CALCULATE ( COUNTROWS ( fact_orders ), fact_orders[status] = "Shipped" )

On-time % =
DIVIDE ( CALCULATE ( COUNTROWS ( fact_orders ), fact_orders[on_time] = 1 ), [Orders Shipped] )

Avg Cycle Days = AVERAGE ( fact_orders[cycle_days] )

Inventory Accuracy % = DIVIDE ( SUM ( fact_counts[within_tolerance] ), COUNTROWS ( fact_counts ) )

Count Difference EUR = SUM ( fact_counts[difference_value] )

Stock Value EUR = SUM ( snapshot_stock[stock_value] )

Units Issued =
CALCULATE ( SUM ( fact_movements[quantity] ), fact_movements[movement_type] = "GI" )

Route Saving % =
1 - DIVIDE ( SUM ( fact_pick_routes[distance_m] ), SUM ( fact_pick_routes[naive_distance_m] ) )

Products to Reorder =
CALCULATE ( COUNTROWS ( snapshot_planning ), snapshot_planning[reorder_now] = TRUE () )
```

Format the % measures as Percentage (Measure tools → Format).

**Check your numbers.** Your cards must show the same values as the Control
tower page of the app on the same database. For the demo data with seed 42
(generated on 2026-11-19) that was:

| Measure | Value |
|---|---|
| On-time % | 88.8 % |
| Avg Cycle Days | 2.5 |
| Inventory Accuracy % | 90.0 % |
| Route Saving % | 3.8 % |
| Stock Value EUR | 17,028.01 |
| Products to Reorder | 7 |

The demo dates follow the day you generate it, so the reorder figures can
differ slightly on another day. If Power BI differs from the app, check the
locale (step 1) and the column types (step 2) first.

## 6. Theme (three colours)

View → Themes → **Browse for themes** → `docs/powerbi_theme.json`.
The same three colours as the app: dark green `#0F3D3A` for main values,
burgundy `#6C151E` for attention, cream `#F6DABF` (lighter tint as background).

## 7. Report pages

**Page 1: Overview**
- Cards: Orders Shipped, On-time %, Avg Cycle Days, Inventory Accuracy %, Stock Value EUR
- Line chart: Date[Week start] on the X axis, Orders Shipped and On-time % on the Y axes
- Slicer: Date[Month]

**Page 2: Inventory**
- Donut chart: Stock Value EUR by snapshot_stock[status]
- Bar chart: Stock Value EUR by dim_product[abc_class]
- Table: dim_product[product_code], product_name, abc_class, Stock Value EUR

**Page 3: Inventory accuracy**
- Line chart: Inventory Accuracy % by Date[Week start]
- Bar chart: Count Difference EUR by fact_counts[reason]
- Bar chart: COUNTROWS(fact_counts) by dim_bin[zone_name]
- Do not build a chart "differences by counted_by". Accuracy is a process
  measure, and a per-person ranking is not what this report is for.

**Page 4: Replenishment**
- Table from snapshot_planning with dim_product[product_name]: abc_class,
  weekly_mean, safety_stock, reorder_point, inventory_position, reorder_now,
  proposed_quantity
- Conditional formatting on `reorder_now`: Format → Cell elements →
  Background color → rules → value is True → burgundy `#6C151E`, font white

## 8. Save and share

1. In File Explorer, create the folder `docs\powerbi` inside the project.
2. Power BI: **File → Save as** → `docs\powerbi\warehouse_report.pbix`.
3. **File → Export → Export to PDF** → `docs\powerbi\warehouse_report.pdf`
   (anyone can open a PDF, also people without Power BI).
4. Screenshot each page (Win+Shift+S, select the report canvas) and save as
   `docs\powerbi\page1_overview.png`, `page2_inventory.png`,
   `page3_accuracy.png`, `page4_replenishment.png`. Use exactly these
   lower-case names: GitHub is case-sensitive.

The `.pbix` file contains the data, which is synthetic, so committing it is
fine.

## What to say in an interview

- Star schema: dimensions (product, bin, date) and facts (movements, orders,
  counts, routes) exported from an operational database.
- Every KPI is defined once (measures) and cross-checked against the app.
- The data is simulated. The point is the method, not the numbers.
