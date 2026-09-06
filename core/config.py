"""Единая точка конфигурации проекта.

Читает `.env` из корня проекта (если есть) и предоставляет:
- пути к каталогам данных и артефактам;
- параметры подключения к СУБД;
- параметры ETL-конвейера.

Скрипты в `etl/` и `analytics/` называются с цифрового префикса и не могут быть
импортированы как модули, поэтому каждый из них добавляет корень проекта в
`sys.path` и делает `from core.config import ...`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv не обязателен, если переменные заданы в окружении
    def load_dotenv(*_args, **_kwargs):  # type: ignore
        return False

# --- Каталоги -------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
REPORTS_DIR = PROJECT_ROOT / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"
TABLES_DIR = REPORTS_DIR / "tables"
DATABASE_DIR = PROJECT_ROOT / "database"

for _d in (RAW_DIR, PROCESSED_DIR, FIGURES_DIR, TABLES_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Источник данных ----------------------------------------------------------

DATASET_URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
DATASET_ZIP = RAW_DIR / "online_retail_II.zip"
DATASET_XLSX = RAW_DIR / "online_retail_II.xlsx"

# Промежуточные parquet-снимки
RAW_PARQUET = PROCESSED_DIR / "raw_sales.parquet"
PROFILE_JSON = PROCESSED_DIR / "raw_profile.json"
DIM_DATE_PARQUET = PROCESSED_DIR / "dim_date.parquet"
DIM_CUSTOMER_PARQUET = PROCESSED_DIR / "dim_customer.parquet"
DIM_PRODUCT_PARQUET = PROCESSED_DIR / "dim_product.parquet"
DIM_COUNTRY_PARQUET = PROCESSED_DIR / "dim_country.parquet"
FACT_SALES_PARQUET = PROCESSED_DIR / "fact_sales.parquet"


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class DBConfig:
    host: str = os.getenv("DB_HOST", "127.0.0.1")
    port: int = _int_env("DB_PORT", 3306)
    name: str = os.getenv("DB_NAME", "retail_dwh")
    user: str = os.getenv("DB_USER", "retail_app")
    password: str = os.getenv("DB_PASSWORD", "retail_app_pwd")

    @property
    def url(self) -> str:
        """SQLAlchemy URL для PyMySQL."""
        return (
            f"mysql+pymysql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}?charset=utf8mb4"
        )

    @property
    def url_no_db(self) -> str:
        """URL без выбора базы — для служебных операций."""
        return (
            f"mysql+pymysql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/?charset=utf8mb4"
        )


@dataclass(frozen=True)
class ETLConfig:
    # 0 = читать все строки источника
    sample_rows: int = _int_env("ETL_SAMPLE_ROWS", 0)
    force_rebuild: bool = _int_env("ETL_FORCE_REBUILD", 0) == 1
    # грузить ли слой staging (сырые ~1.07 млн строк); на анализ не влияет
    load_staging: bool = _int_env("ETL_LOAD_STAGING", 1) == 1
    load_chunk_size: int = 10_000


DB = DBConfig()
ETL = ETLConfig()
