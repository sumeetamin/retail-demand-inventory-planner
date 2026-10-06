# Retail Demand & Inventory Replenishment Lab

A rolling-origin demand-forecast comparison and an interactive reorder-point scenario based on real UCI Online Retail II transactions.

## What is measured

- Positive item quantities are aggregated to daily demand for each SKU; canceled invoices, returns/nonpositive quantities and rows with invalid dates or missing item codes are excluded.
- The top 12 SKUs are selected by unit volume before the final 56-day holdout.
- Eight weekly rolling-origin folds cover those final 56 days. The first four folds are validation; the final four are test. Each forecast uses only data available before that week's forecast origin.
- A previous-week same-weekday baseline is compared with the trailing 28-day mean. Validation WAPE selects the method; final test WAPE, MAE and bias are reported separately.
- The interactive reorder point uses a normal lead-time demand approximation and user-selected lead time, target and on-hand quantity.

The web app uses only aggregate historical weekly demand, next-week SKU forecasts and test metrics. Invoice numbers and customer IDs are neither published nor used in its interface.

## Dataset and attribution

Chen, D. (2012). [Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail). UCI Machine Learning Repository. DOI: [10.24432/C5CG6D](https://doi.org/10.24432/C5CG6D). License: CC BY 4.0.

The UCI source has 1,067,371 transaction rows from a UK non-store retailer spanning December 2009–December 2011. The workbook is downloaded locally by the runner and is not committed to this repository.

## Reproduce

From the repository root:

```powershell
python -m pip install -r requirements.txt
python benchmark/run.py
```

The script downloads the UCI archive to the ignored `benchmark_data/` directory and writes the aggregate output consumed by the app to `data/benchmark.json`.

## Limitations

- This is a historical dataset from one retailer, not current inventory or supplier data.
- SKU selection uses only the period before the holdout; the benchmark evaluates twelve high-volume items and says nothing about cold-start or long-tail SKUs.
- Weekly folds form a walk-forward operational backtest, but the short test window cannot establish seasonal robustness.
- The baselines omit promotions, stockouts, substitutions, lead-time variation, ordering costs, supplier constraints and demand censoring.
- The reorder-point normal/independent-demand calculation is a teaching scenario. The selected service target is not a guarantee of achieved service.

