"""Backtest practical daily SKU-demand baselines on UCI Online Retail II."""

from __future__ import annotations

import hashlib
import json
import platform
import time
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "benchmark_data"
ZIP_PATH = DATA_DIR / "online_retail_ii.zip"
BOOK_PATH = DATA_DIR / "online_retail_II.xlsx"
ZIP_URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
OUTPUT = ROOT / "data/benchmark.json"
N_PRODUCTS = 12
HOLDOUT_DAYS = 56


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def ensure_data() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not BOOK_PATH.exists():
        if not ZIP_PATH.exists():
            request = urllib.request.Request(ZIP_URL, headers={"User-Agent": "retail-demand-inventory-planner/1.0"})
            with urllib.request.urlopen(request, timeout=180) as response, ZIP_PATH.open("wb") as output:
                output.write(response.read())
        with zipfile.ZipFile(ZIP_PATH) as archive:
            member = next(name for name in archive.namelist() if name.lower().endswith(".xlsx"))
            BOOK_PATH.write_bytes(archive.read(member))


def forecast(method: str, history: np.ndarray) -> np.ndarray:
    if method == "weekly_seasonal_naive":
        return np.maximum(0, history[-7:].astype(float))
    if method == "trailing_28_day_mean":
        return np.repeat(float(np.mean(history[-28:])), 7)
    raise ValueError(f"unknown forecast method {method}")


def score(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    denominator = max(float(actual.sum()), 1.0)
    return {
        "mae_units_per_sku_day": float(np.mean(np.abs(actual - predicted))),
        "wape": float(np.abs(actual - predicted).sum() / denominator),
        "bias_units_per_sku_day": float(np.mean(predicted - actual)),
        "actual_units": float(actual.sum()),
        "forecast_units": float(predicted.sum()),
    }


def main() -> None:
    started = time.perf_counter()
    ensure_data()
    sheets = pd.read_excel(BOOK_PATH, sheet_name=None, usecols=["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate"], dtype={"Invoice": str, "StockCode": str})
    frame = pd.concat(sheets.values(), ignore_index=True)
    raw_rows = len(frame)
    frame["InvoiceDate"] = pd.to_datetime(frame["InvoiceDate"], dayfirst=True, errors="coerce")
    frame["date"] = frame["InvoiceDate"].dt.normalize()
    frame["StockCode"] = frame["StockCode"].astype("string").str.strip()
    canceled = frame["Invoice"].str.upper().str.startswith("C", na=False)
    return_or_invalid = frame["Quantity"].le(0) | frame["date"].isna() | frame["StockCode"].isna()
    sales = frame.loc[~canceled & ~return_or_invalid, ["StockCode", "Description", "Quantity", "date"]].copy()
    if sales.empty:
        raise ValueError("No valid positive-quantity sales remain after data cleaning")
    sales["Quantity"] = sales["Quantity"].astype(float)
    max_date = sales["date"].max()
    holdout_start = max_date - pd.Timedelta(days=HOLDOUT_DAYS - 1)
    training = sales[sales["date"] < holdout_start]
    top_codes = training.groupby("StockCode")["Quantity"].sum().nlargest(N_PRODUCTS).index.tolist()
    selected = sales[sales["StockCode"].isin(top_codes)]
    descriptions = (
        selected.dropna(subset=["Description"]).groupby("StockCode")["Description"]
        .agg(lambda values: values.value_counts().index[0])
        .to_dict()
    )
    first_date = selected["date"].min()
    dates = pd.date_range(first_date, max_date, freq="D")
    daily = selected.groupby(["StockCode", "date"])["Quantity"].sum().unstack(fill_value=0).reindex(columns=dates, fill_value=0)

    methods = ["weekly_seasonal_naive", "trailing_28_day_mean"]
    by_partition: dict[str, dict[str, dict[str, list[float]]]] = {
        partition: {method: {"actual": [], "predicted": []} for method in methods}
        for partition in ("validation", "test")
    }
    fold_records = []
    for fold in range(8):
        fold_start = holdout_start + pd.Timedelta(days=fold * 7)
        fold_days = pd.date_range(fold_start, periods=7, freq="D")
        if fold_days[-1] > max_date:
            break
        partition = "validation" if fold < 4 else "test"
        fold_actual = []
        fold_predictions = {method: [] for method in methods}
        for code in top_codes:
            series = daily.loc[code]
            history = series.loc[series.index < fold_start].to_numpy(dtype=float)
            if len(history) < 28:
                continue
            actual = series.reindex(fold_days, fill_value=0).to_numpy(dtype=float)
            for method in methods:
                predicted = forecast(method, history)
                by_partition[partition][method]["actual"].extend(actual.tolist())
                by_partition[partition][method]["predicted"].extend(predicted.tolist())
                fold_predictions[method].extend(predicted.tolist())
            fold_actual.extend(actual.tolist())
        fold_records.append({"week_start": fold_start.strftime("%Y-%m-%d"), "partition": partition, "sku_days": len(fold_actual)})
    validation_scores = {
        method: score(by_partition["validation"][method]["actual"], by_partition["validation"][method]["predicted"])
        for method in methods
    }
    selected_method = min(methods, key=lambda method: validation_scores[method]["wape"])
    test_scores = {
        method: score(by_partition["test"][method]["actual"], by_partition["test"][method]["predicted"])
        for method in methods
    }

    product_rows = []
    for code in top_codes:
        series = daily.loc[code]
        history = series.loc[series.index < holdout_start]
        full_history = history.reindex(pd.date_range(history.index.min(), history.index.max(), freq="D"), fill_value=0)
        weekly = full_history.resample("W-SUN").sum().tail(12)
        next_week = forecast(selected_method, history.to_numpy(dtype=float))
        recent_90 = history.tail(90).reindex(pd.date_range(history.index.max() - pd.Timedelta(days=89), history.index.max(), freq="D"), fill_value=0)
        product_rows.append({
            "stock_code": str(code), "description": str(descriptions.get(code, "Unlabeled product"))[:100],
            "training_units": float(history.sum()), "mean_daily_demand": float(recent_90.mean()),
            "std_daily_demand": float(recent_90.std(ddof=1) if len(recent_90) > 1 else 0),
            "weekly_history": [{"week": day.strftime("%b %d"), "units": float(value)} for day, value in weekly.items()],
            "next_7_day_forecast": [float(value) for value in next_week],
            "forecast_total_7d": float(next_week.sum()),
        })

    report = {
        "project": "Retail Demand & Inventory Replenishment Lab",
        "dataset": {
            "name": "Online Retail II", "source": "UCI Machine Learning Repository",
            "source_url": "https://archive.ics.uci.edu/dataset/502/online+retail",
            "citation": "Chen, D. (2012). Online Retail II. UCI ML Repository. DOI: 10.24432/C5CG6D.",
            "license": "CC BY 4.0", "workbook_sha256": sha256(ZIP_PATH), "source_rows": int(raw_rows),
            "valid_positive_sale_rows": int(len(sales)), "canceled_invoice_rows_excluded": int(canceled.sum()),
            "nonpositive_or_invalid_rows_excluded": int(return_or_invalid.sum()),
            "first_sale_date": sales["date"].min().strftime("%Y-%m-%d"), "last_sale_date": max_date.strftime("%Y-%m-%d"),
            "selected_skus": len(top_codes),
        },
        "protocol": {
            "split": f"8 weekly rolling-origin folds over final {HOLDOUT_DAYS} days; first 4 validation, last 4 untouched test",
            "product_selection": "Top 12 SKU by positive sales quantity strictly before holdout start",
            "candidates": methods, "selected_model": selected_method,
            "selection_metric": "validation WAPE; no tuning on final four test folds",
            "inventory_policy": "Normal lead-time demand approximation; scenario only, not a calibrated service guarantee",
            "python": platform.python_version(), "pandas": pd.__version__,
            "run_seconds": round(time.perf_counter() - started, 3),
            "folds": fold_records,
        },
        "validation": validation_scores,
        "test": test_scores,
        "products": product_rows,
        "limitations": [
            "Historical transactions from one UK online retailer are not current market demand.",
            "Canceled invoices, returns and nonpositive quantities are excluded from unit-demand forecasts.",
            "Only the twelve highest-volume pre-holdout SKUs are evaluated; cold-start and long-tail products are not represented.",
            "The backtest uses aggregate daily units and simple baselines; it omits promotions, stock availability, lead-time variation and supplier constraints.",
            "The reorder-point simulator assumes independent daily demand and normal lead-time demand; it is an educational what-if, not a service-level guarantee.",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Source rows={raw_rows:,}; valid positive sales={len(sales):,}; selected SKUs={len(top_codes)}")
    print(f"Selected={selected_method}; validation WAPE={validation_scores[selected_method]['wape']:.3f}; final test WAPE={test_scores[selected_method]['wape']:.3f}; MAE={test_scores[selected_method]['mae_units_per_sku_day']:.3f} units/SKU/day")
    print(f"Aggregate report: {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

