"""ETL · шаг 1 — ИЗВЛЕЧЕНИЕ.

- при отсутствии файла-источника скачивает Online Retail II с UCI и распаковывает;
- читает оба листа Excel, склеивает в один DataFrame, помечает лист-источник;
- строит профиль качества данных (json) — для отчёта и для контроля шага 2;
- сохраняет сырой снимок в data/processed/raw_sales.parquet.

Запуск:  python etl/01_extract.py
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import requests

from core.config import (
    DATASET_URL,
    DATASET_XLSX,
    DATASET_ZIP,
    ETL,
    PROFILE_JSON,
    RAW_PARQUET,
)
from core.logs import get_logger

log = get_logger("etl.extract")

SOURCE_COLUMNS = {
    "Invoice": "invoice",
    "StockCode": "stock_code",
    "Description": "description",
    "Quantity": "quantity",
    "InvoiceDate": "invoice_date",
    "Price": "price",
    "Customer ID": "customer_id",
    "Country": "country",
}


def ensure_source() -> None:
    """Скачать и распаковать датасет, если его ещё нет на диске."""
    if DATASET_XLSX.exists():
        log.info("Источник на месте: %s (%.1f МБ)", DATASET_XLSX.name,
                 DATASET_XLSX.stat().st_size / 1e6)
        return

    if not DATASET_ZIP.exists():
        log.info("Скачиваю датасет: %s", DATASET_URL)
        resp = requests.get(DATASET_URL, timeout=300)
        resp.raise_for_status()
        DATASET_ZIP.write_bytes(resp.content)
        log.info("Сохранено: %s (%.1f МБ)", DATASET_ZIP.name,
                 DATASET_ZIP.stat().st_size / 1e6)

    with zipfile.ZipFile(DATASET_ZIP) as zf:
        zf.extractall(DATASET_ZIP.parent)
    log.info("Распаковано в %s", DATASET_ZIP.parent)
    if not DATASET_XLSX.exists():
        raise FileNotFoundError(f"После распаковки не найден {DATASET_XLSX}")


def read_workbook() -> pd.DataFrame:
    """Прочитать все листы Excel в единый DataFrame."""
    nrows = ETL.sample_rows or None
    xl = pd.ExcelFile(DATASET_XLSX)
    frames = []
    for sheet in xl.sheet_names:
        part = xl.parse(sheet, nrows=nrows, dtype={"Invoice": str, "StockCode": str})
        part = part.rename(columns=SOURCE_COLUMNS)
        part["_source_sheet"] = sheet
        frames.append(part)
        log.info("Лист %-16s → %d строк", sheet, len(part))
    df = pd.concat(frames, ignore_index=True)
    df["invoice_date"] = pd.to_datetime(df["invoice_date"], errors="coerce")
    # в исходнике встречаются числовые значения в текстовых полях — приводим к строке
    for col in ("invoice", "stock_code", "description", "country"):
        df[col] = df[col].astype("string")
    return df


def build_profile(df: pd.DataFrame) -> dict:
    """Профиль качества сырых данных."""
    invoice = df["invoice"].astype(str)
    prof = {
        "rows": int(len(df)),
        "columns": list(df.columns),
        "null_counts": {k: int(v) for k, v in df.isna().sum().items()},
        "full_duplicates": int(df.duplicated().sum()),
        "date_min": str(df["invoice_date"].min()),
        "date_max": str(df["invoice_date"].max()),
        "returns_rows": int(invoice.str.startswith("C").sum()),
        "missing_customer_rows": int(df["customer_id"].isna().sum()),
        "quantity": {
            "min": int(df["quantity"].min()),
            "max": int(df["quantity"].max()),
            "le_zero": int((df["quantity"] <= 0).sum()),
        },
        "price": {
            "min": float(df["price"].min()),
            "max": float(df["price"].max()),
            "le_zero": int((df["price"] <= 0).sum()),
        },
        "distinct": {
            "invoices": int(invoice.nunique()),
            "stock_codes": int(df["stock_code"].nunique()),
            "customers": int(df["customer_id"].nunique(dropna=True)),
            "countries": int(df["country"].nunique()),
        },
        "sample_rows_limit": ETL.sample_rows,
    }
    return prof


def main() -> None:
    ensure_source()

    if RAW_PARQUET.exists() and not ETL.force_rebuild:
        log.info("%s уже существует — пропускаю чтение Excel "
                 "(ETL_FORCE_REBUILD=1 чтобы пересобрать)", RAW_PARQUET.name)
        return

    df = read_workbook()
    log.info("Всего строк: %d", len(df))

    profile = build_profile(df)
    PROFILE_JSON.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Профиль качества → %s", PROFILE_JSON.name)
    for key in ("rows", "full_duplicates", "returns_rows", "missing_customer_rows"):
        log.info("  %-22s %s", key, profile[key])

    df.to_parquet(RAW_PARQUET, index=False)
    log.info("Сырой снимок → %s (%.1f МБ)", RAW_PARQUET.name,
             RAW_PARQUET.stat().st_size / 1e6)


if __name__ == "__main__":
    main()
