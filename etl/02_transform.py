"""ETL · шаг 2 — ПРЕОБРАЗОВАНИЕ.

Из сырого снимка (data/processed/raw_sales.parquet) строит очищенные
parquet-таблицы многомерной модели «звезда»:
    dim_date, dim_country, dim_product, dim_customer, fact_sales

Правила очистки продублированы в database/03_load_data.sql (SQL-вариант).

Запуск:  python etl/02_transform.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from core.config import (
    DIM_COUNTRY_PARQUET,
    DIM_CUSTOMER_PARQUET,
    DIM_DATE_PARQUET,
    DIM_PRODUCT_PARQUET,
    FACT_SALES_PARQUET,
    RAW_PARQUET,
)
from core.logs import get_logger

log = get_logger("etl.transform")

GUEST_KEY = -1

COUNTRY_FIXES = {
    "EIRE": "Ireland",
    "USA": "United States",
    "RSA": "South Africa",
    "Unspecified": "Unknown",
    "": "Unknown",
}

EUROPE = {
    "Ireland", "France", "Germany", "Spain", "Portugal", "Italy", "Belgium",
    "Netherlands", "Switzerland", "Austria", "Norway", "Sweden", "Finland",
    "Denmark", "Poland", "Czech Republic", "Greece", "Cyprus", "Malta",
    "Lithuania", "Iceland", "Channel Islands", "Lebanon", "European Community",
}

SERVICE_CODES = {
    "POST", "DOT", "M", "MANUAL", "BANK CHARGES", "C2", "CRUK", "PADS",
    "AMAZONFEE", "ADJUST", "ADJUST2", "D", "S", "B", "GIFT", "TEST001", "TEST002",
}

CATEGORY_RULES = [
    ("SERVICE", None),  # проставляется отдельно по is_service
    ("STORAGE", r"BAG|BASKET|BOX"),
    ("LIGHTING", r"LIGHT|LAMP|CANDLE|LANTERN"),
    ("KITCHEN", r"MUG|CUP|BOWL|PLATE|JUG|TEAPOT|BOTTLE|CUTLERY"),
    ("GIFT & STATIONERY", r"CARD|WRAP|GIFT|RIBBON|\bTAG\b|NOTEBOOK|PEN\b"),
    ("SEASONAL", r"CHRISTMAS|EASTER|VALENTINE|HALLOWEEN|ADVENT"),
    ("HOME DECOR", r"HEART|SIGN|FRAME|CLOCK|HOOK|DECORATION|CUSHION|CANDLEHOLDER"),
    ("KIDS & TOYS", r"BABY|CHILD|KIDS|\bTOY\b|GAME|DOLL|PLAYHOUSE"),
    ("GARDEN", r"GARDEN|PLANT|FLOWER|GREENHOUSE"),
]


# --------------------------------------------------------------------------- #
#  Очистка сырых строк                                                        #
# --------------------------------------------------------------------------- #
def clean_raw(df: pd.DataFrame) -> pd.DataFrame:
    n0 = len(df)
    df = df.copy()

    df["invoice"] = df["invoice"].astype("string").str.strip()
    df["stock_code"] = df["stock_code"].astype("string").str.strip().str.upper()
    df["description"] = df["description"].astype("string").str.strip()
    df["country"] = df["country"].astype("string").str.strip().fillna("")
    df["country_name"] = df["country"].replace(COUNTRY_FIXES)
    df["country_name"] = df["country_name"].where(df["country_name"].ne(""), "Unknown")

    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["invoice_date"] = pd.to_datetime(df["invoice_date"], errors="coerce")
    df["customer_id"] = pd.to_numeric(df["customer_id"], errors="coerce").astype("Int64")

    df["is_return"] = df["invoice"].str.upper().str.startswith("C").fillna(False)

    # --- фильтры ---
    before = len(df)
    df = df.drop_duplicates()
    log.info("  дубликаты удалены: %d", before - len(df))

    mask_valid_types = df[["quantity", "price", "invoice_date", "stock_code"]].notna().all(axis=1)
    df = df[mask_valid_types]

    sale = (~df["is_return"]) & (df["quantity"] > 0) & (df["price"] > 0)
    ret = (df["is_return"]) & (df["quantity"] < 0) & (df["price"] > 0)
    df = df[sale | ret]

    df["quantity"] = df["quantity"].astype(int)
    df["price"] = df["price"].round(2)

    log.info("  строк после очистки: %d (отброшено %d, %.1f%%)",
             len(df), n0 - len(df), 100 * (n0 - len(df)) / n0)
    return df.reset_index(drop=True)


# --------------------------------------------------------------------------- #
#  Измерения                                                                  #
# --------------------------------------------------------------------------- #
def build_dim_country(df: pd.DataFrame) -> pd.DataFrame:
    names = sorted(df["country_name"].dropna().unique())
    rows = []
    for i, name in enumerate(names, start=1):
        if name == "United Kingdom":
            region = "UK"
        elif name in EUROPE:
            region = "Europe"
        elif name == "Unknown":
            region = "Other"
        else:
            region = "World"
        rows.append({"country_key": i, "country_name": name, "region": region})
    dim = pd.DataFrame(rows)
    log.info("dim_country: %d стран", len(dim))
    return dim


def _categorise(description: str, is_service: bool) -> str:
    if is_service:
        return "SERVICE"
    text = (description or "").upper()
    for cat, pattern in CATEGORY_RULES:
        if pattern and re.search(pattern, text):
            return cat
    return "OTHER"


def build_dim_product(df: pd.DataFrame) -> pd.DataFrame:
    # эталонное описание = самое частое непустое для артикула
    desc = (
        df.dropna(subset=["description"])
          .groupby("stock_code")["description"]
          .agg(lambda s: s.value_counts().index[0])
    )
    codes = sorted(df["stock_code"].unique())
    dim = pd.DataFrame({"stock_code": codes})
    dim["description"] = dim["stock_code"].map(desc).fillna("")
    dim["is_service"] = dim["stock_code"].apply(
        lambda c: 1 if (c in SERVICE_CODES or (len(c) <= 3 and not any(ch.isdigit() for ch in c)))
        else 0
    )
    dim["category"] = [
        _categorise(d, bool(s)) for d, s in zip(dim["description"], dim["is_service"])
    ]
    dim.insert(0, "product_key", range(1, len(dim) + 1))
    log.info("dim_product: %d артикулов (%d служебных)",
             len(dim), int(dim["is_service"].sum()))
    return dim


def build_dim_customer(df: pd.DataFrame) -> pd.DataFrame:
    known = df[df["customer_id"].notna()].copy()
    known = known.sort_values("invoice_date")
    agg = known.groupby("customer_id").agg(
        country=("country_name", "last"),
        first_order_date=("invoice_date", "min"),
        last_order_date=("invoice_date", "max"),
        orders_count=("invoice", "nunique"),
    ).reset_index()
    agg["first_order_date"] = agg["first_order_date"].dt.date
    agg["last_order_date"] = agg["last_order_date"].dt.date
    agg = agg.sort_values("customer_id").reset_index(drop=True)
    agg.insert(0, "customer_key", range(1, len(agg) + 1))
    agg["customer_id"] = agg["customer_id"].astype(int)
    agg["is_guest"] = 0

    guest = pd.DataFrame([{
        "customer_key": GUEST_KEY, "customer_id": pd.NA, "is_guest": 1,
        "country": "Unknown", "first_order_date": pd.NaT,
        "last_order_date": pd.NaT, "orders_count": 0,
    }])
    dim = pd.concat([guest, agg], ignore_index=True)
    dim = dim[["customer_key", "customer_id", "is_guest", "country",
               "first_order_date", "last_order_date", "orders_count"]]
    dim["customer_id"] = dim["customer_id"].astype("Int64")
    log.info("dim_customer: %d клиентов (+1 строка «гость»)", len(agg))
    return dim


def build_dim_date(df: pd.DataFrame) -> pd.DataFrame:
    d0, d1 = df["invoice_date"].min().normalize(), df["invoice_date"].max().normalize()
    days = pd.date_range(d0, d1, freq="D")
    ru_month = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль",
                "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
    ru_day = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница",
              "Суббота", "Воскресенье"]
    dim = pd.DataFrame({"full_date": days})
    dim["date_key"] = dim["full_date"].dt.strftime("%Y%m%d").astype(int)
    dim["year"] = dim["full_date"].dt.year
    dim["quarter"] = dim["full_date"].dt.quarter
    dim["month"] = dim["full_date"].dt.month
    dim["month_name"] = dim["month"].map(lambda m: ru_month[m - 1])
    dim["ym"] = dim["full_date"].dt.strftime("%Y-%m")
    dim["week_iso"] = dim["full_date"].dt.isocalendar().week.astype(int)
    dim["day_of_month"] = dim["full_date"].dt.day
    dim["day_of_week"] = dim["full_date"].dt.weekday + 1
    dim["day_name"] = (dim["day_of_week"] - 1).map(lambda i: ru_day[i])
    dim["is_weekend"] = (dim["day_of_week"] >= 6).astype(int)
    dim["full_date"] = dim["full_date"].dt.date
    dim = dim[["date_key", "full_date", "year", "quarter", "month", "month_name",
               "ym", "week_iso", "day_of_month", "day_of_week",
               "day_name", "is_weekend"]]
    log.info("dim_date: %d дней (%s … %s)", len(dim), d0.date(), d1.date())
    return dim


# --------------------------------------------------------------------------- #
#  Факт                                                                       #
# --------------------------------------------------------------------------- #
def build_fact_sales(df, dim_product, dim_customer, dim_country) -> pd.DataFrame:
    prod_map = dict(zip(dim_product["stock_code"], dim_product["product_key"]))
    cust_map = {
        int(cid): int(k)
        for cid, k in zip(dim_customer["customer_id"], dim_customer["customer_key"])
        if pd.notna(cid)
    }
    country_map = dict(zip(dim_country["country_name"], dim_country["country_key"]))

    fact = pd.DataFrame({
        "date_key": df["invoice_date"].dt.strftime("%Y%m%d").astype(int),
        "customer_key": df["customer_id"].map(lambda c: cust_map.get(int(c), GUEST_KEY)
                                              if pd.notna(c) else GUEST_KEY),
        "product_key": df["stock_code"].map(prod_map),
        "country_key": df["country_name"].map(country_map),
        "invoice_no": df["invoice"].astype(str),
        "invoice_ts": df["invoice_date"],
        "quantity": df["quantity"].astype(int),
        "unit_price": df["price"].round(2),
        "is_return": df["is_return"].astype(int),
    })
    fact["gross_amount"] = (fact["quantity"] * fact["unit_price"]).round(2)

    missing = fact[["product_key", "country_key"]].isna().any(axis=1).sum()
    if missing:
        log.warning("  строк без ключа измерения отброшено: %d", int(missing))
        fact = fact.dropna(subset=["product_key", "country_key"])
    fact["product_key"] = fact["product_key"].astype(int)
    fact["country_key"] = fact["country_key"].astype(int)
    fact["customer_key"] = fact["customer_key"].astype(int)

    fact = fact[["date_key", "customer_key", "product_key", "country_key",
                 "invoice_no", "invoice_ts", "quantity", "unit_price",
                 "gross_amount", "is_return"]]
    log.info("fact_sales: %d строк, выручка (без возвратов) %.0f GBP",
             len(fact), fact.loc[fact["is_return"] == 0, "gross_amount"].sum())
    return fact.reset_index(drop=True)


def main() -> None:
    if not RAW_PARQUET.exists():
        raise SystemExit("Нет raw_sales.parquet — сначала запустите etl/01_extract.py")

    raw = pd.read_parquet(RAW_PARQUET)
    log.info("Загружено сырых строк: %d", len(raw))

    clean = clean_raw(raw)

    dim_country = build_dim_country(clean)
    dim_product = build_dim_product(clean)
    dim_customer = build_dim_customer(clean)
    dim_date = build_dim_date(clean)
    fact = build_fact_sales(clean, dim_product, dim_customer, dim_country)

    dim_date.to_parquet(DIM_DATE_PARQUET, index=False)
    dim_country.to_parquet(DIM_COUNTRY_PARQUET, index=False)
    dim_product.to_parquet(DIM_PRODUCT_PARQUET, index=False)
    dim_customer.to_parquet(DIM_CUSTOMER_PARQUET, index=False)
    fact.to_parquet(FACT_SALES_PARQUET, index=False)
    log.info("Parquet-таблицы «звезды» сохранены в data/processed/")


if __name__ == "__main__":
    main()
