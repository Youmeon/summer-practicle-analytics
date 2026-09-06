"""ETL · шаг 3 — ЗАГРУЗКА.

- создаёт схему хранилища (database/02_create_schema.sql);
- при ETL_LOAD_STAGING=1 заливает сырой слой stg_online_retail;
- грузит parquet-таблицы «звезды» (dim_*, fact_sales);
- создаёт витрины-представления (database/04_analytics_queries.sql);
- печатает сверку строк.

Запуск:  python etl/03_load.py
"""
from __future__ import annotations

import hashlib
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from core.config import (
    DATABASE_DIR,
    DIM_COUNTRY_PARQUET,
    DIM_CUSTOMER_PARQUET,
    DIM_DATE_PARQUET,
    DIM_PRODUCT_PARQUET,
    ETL,
    FACT_SALES_PARQUET,
    RAW_PARQUET,
)
from core.db import get_engine, ping, run_sql_script, write_dataframe
from core.logs import get_logger

log = get_logger("etl.load")

STG_COLUMNS = ["invoice", "stock_code", "description", "quantity",
               "invoice_date", "price", "customer_id", "country"]


def load_staging() -> None:
    if not ETL.load_staging:
        log.info("ETL_LOAD_STAGING=0 — слой staging пропущен")
        return
    raw = pd.read_parquet(RAW_PARQUET)
    stg = pd.DataFrame({
        "invoice": raw["invoice"].astype("string"),
        "stock_code": raw["stock_code"].astype("string"),
        "description": raw["description"].astype("string"),
        "quantity": raw["quantity"].astype("string"),
        "invoice_date": raw["invoice_date"].astype("string"),
        "price": raw["price"].astype("string"),
        "customer_id": raw["customer_id"].astype("string"),
        "country": raw["country"].astype("string"),
        "_source_sheet": raw["_source_sheet"].astype("string"),
    })
    stg["_loaded_at"] = datetime.now().replace(microsecond=0)
    joined = stg[STG_COLUMNS].fillna("").agg("|".join, axis=1)
    stg["_row_hash"] = [hashlib.sha1(s.encode("utf-8")).hexdigest() for s in joined]

    log.info("Заливаю staging: %d строк (может занять пару минут)…", len(stg))
    write_dataframe(stg, "stg_online_retail", if_exists="append",
                    chunksize=ETL.load_chunk_size)


def load_star() -> None:
    tables = [
        ("dim_date", DIM_DATE_PARQUET),
        ("dim_country", DIM_COUNTRY_PARQUET),
        ("dim_product", DIM_PRODUCT_PARQUET),
        ("dim_customer", DIM_CUSTOMER_PARQUET),
        ("fact_sales", FACT_SALES_PARQUET),
    ]
    for name, path in tables:
        if not path.exists():
            raise SystemExit(f"Нет {path.name} — сначала запустите etl/02_transform.py")
        df = pd.read_parquet(path)
        # NaT/NA → None для драйвера
        df = df.astype(object).where(pd.notna(df), None)
        write_dataframe(df, name, if_exists="append", chunksize=ETL.load_chunk_size)


def reconcile() -> None:
    eng = get_engine()
    with eng.connect() as conn:
        rows = {}
        for tbl in ("stg_online_retail", "dim_date", "dim_country",
                    "dim_product", "dim_customer", "fact_sales"):
            rows[tbl] = conn.exec_driver_sql(
                f"SELECT COUNT(*) FROM {tbl}").scalar()
        views = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM information_schema.views "
            "WHERE table_schema = DATABASE()").scalar()
    log.info("── Сверка строк ─────────────────────────")
    for k, v in rows.items():
        log.info("   %-20s %10s", k, f"{v:,}")
    log.info("   витрин (VIEW):        %10s", views)


def main() -> None:
    if not ping():
        raise SystemExit(
            "Нет подключения к БД. Проверьте, что MariaDB запущен и выполнен\n"
            "    sudo mysql < database/01_create_database.sql\n"
            "а параметры в .env совпадают с созданным пользователем."
        )

    log.info("1/4  DDL схемы хранилища")
    run_sql_script(DATABASE_DIR / "02_create_schema.sql")

    log.info("2/4  Слой staging")
    load_staging()

    log.info("3/4  Таблицы «звезды»")
    load_star()

    log.info("4/4  Витрины-представления")
    run_sql_script(DATABASE_DIR / "04_analytics_queries.sql",
                   stop_at="ДЕМОНСТРАЦИОННЫЕ ЗАПРОСЫ")

    reconcile()
    log.info("Загрузка завершена.")


if __name__ == "__main__":
    main()
