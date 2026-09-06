"""Аналитика · продажи.

Тренды и сезонность, ABC-анализ ассортимента, топ-товары, разрез по странам,
RFM-сегментация клиентов (правила + KMeans), анализ возвратов.
Все результаты — в reports/tables/*.csv.

Запуск:  python analytics/02_sales_analysis.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from analytics._common import log, save_table
from core.db import read_sql


# --------------------------------------------------------------------------- #
def revenue_trend() -> pd.DataFrame:
    df = read_sql("SELECT * FROM v_revenue_monthly ORDER BY ym")
    df["mom_growth"] = df["gross_revenue"].pct_change().round(4)
    df["revenue_ma3"] = df["gross_revenue"].rolling(3, min_periods=1).mean().round(2)
    save_table(df, "revenue_monthly")
    return df


def seasonality() -> None:
    by_month = read_sql("""
        SELECT d.month, d.month_name,
               ROUND(SUM(CASE WHEN f.is_return=0 THEN f.gross_amount ELSE 0 END),2) AS revenue,
               COUNT(DISTINCT f.invoice_no) AS orders
        FROM fact_sales f JOIN dim_date d ON d.date_key = f.date_key
        GROUP BY d.month, d.month_name ORDER BY d.month
    """)
    save_table(by_month, "seasonality_by_month")

    by_dow = read_sql("""
        SELECT d.day_of_week, d.day_name,
               ROUND(SUM(CASE WHEN f.is_return=0 THEN f.gross_amount ELSE 0 END),2) AS revenue,
               COUNT(DISTINCT f.invoice_no) AS orders,
               ROUND(SUM(CASE WHEN f.is_return=0 THEN f.gross_amount ELSE 0 END)
                     / COUNT(DISTINCT f.invoice_no),2) AS avg_order_value
        FROM fact_sales f JOIN dim_date d ON d.date_key = f.date_key
        GROUP BY d.day_of_week, d.day_name ORDER BY d.day_of_week
    """)
    save_table(by_dow, "seasonality_by_dow")


def abc_analysis() -> pd.DataFrame:
    prod = read_sql("SELECT * FROM v_top_products WHERE revenue > 0 ORDER BY revenue DESC")
    prod = prod.reset_index(drop=True)
    total = prod["revenue"].sum()
    prod["revenue_share"] = (prod["revenue"] / total).round(5)
    prod["cum_share"] = prod["revenue_share"].cumsum().round(5)
    prod["abc_class"] = np.where(prod["cum_share"] <= 0.80, "A",
                         np.where(prod["cum_share"] <= 0.95, "B", "C"))
    save_table(prod, "abc_products")

    summary = (prod.groupby("abc_class")
                   .agg(products=("stock_code", "count"),
                        revenue=("revenue", "sum"))
                   .assign(products_share=lambda x: (x["products"] / x["products"].sum()).round(4),
                           revenue_share=lambda x: (x["revenue"] / x["revenue"].sum()).round(4))
                   .reset_index())
    save_table(summary, "abc_summary")
    log.info("ABC: A=%d тов. / %.0f%% выручки, B=%d, C=%d",
             summary.loc[summary.abc_class == "A", "products"].iat[0],
             100 * summary.loc[summary.abc_class == "A", "revenue_share"].iat[0],
             summary.loc[summary.abc_class == "B", "products"].iat[0],
             summary.loc[summary.abc_class == "C", "products"].iat[0])
    return prod


def top_products(prod: pd.DataFrame) -> None:
    save_table(prod.head(20)[["stock_code", "description", "category",
                              "revenue", "units", "invoices"]], "top20_products")
    by_cat = (prod.groupby("category")
                  .agg(revenue=("revenue", "sum"), products=("stock_code", "count"),
                       units=("units", "sum"))
                  .sort_values("revenue", ascending=False).reset_index())
    save_table(by_cat, "revenue_by_category")


def by_country() -> None:
    df = read_sql("SELECT * FROM v_sales_by_country ORDER BY revenue DESC")
    save_table(df.head(15), "top15_countries")
    save_table(df.groupby("region").agg(revenue=("revenue", "sum"),
                                        customers=("customers", "sum"),
                                        countries=("country_name", "count"))
                 .reset_index().sort_values("revenue", ascending=False),
               "revenue_by_region")


# --------------------------------------------------------------------------- #
def _score(series: pd.Series, reverse: bool = False) -> pd.Series:
    """Квинтильные оценки 1..5 (reverse=True — меньше значение → выше оценка)."""
    labels = [5, 4, 3, 2, 1] if reverse else [1, 2, 3, 4, 5]
    try:
        return pd.qcut(series.rank(method="first"), 5, labels=labels).astype(int)
    except ValueError:  # мало уникальных значений
        return pd.Series(3, index=series.index)


def _segment(r: int, f: int) -> str:
    if r >= 4 and f >= 4:
        return "Чемпионы"
    if f >= 4:
        return "Лояльные"
    if r >= 4 and f <= 2:
        return "Новички"
    if r <= 2 and f >= 3:
        return "В зоне риска"
    if r <= 2 and f <= 2:
        return "Спящие"
    return "Требуют внимания"


def rfm_segmentation() -> None:
    rfm = read_sql("SELECT * FROM v_customer_rfm")
    rfm = rfm[rfm["monetary"] > 0].reset_index(drop=True)

    rfm["R"] = _score(rfm["recency_days"], reverse=True)
    rfm["F"] = _score(rfm["frequency"])
    rfm["M"] = _score(rfm["monetary"])
    rfm["rfm_score"] = rfm["R"] * 100 + rfm["F"] * 10 + rfm["M"]
    rfm["segment"] = [_segment(r, f) for r, f in zip(rfm["R"], rfm["F"])]

    # KMeans на логарифмированных и стандартизованных R/F/M
    feats = np.column_stack([
        -np.log1p(rfm["recency_days"]),
        np.log1p(rfm["frequency"]),
        np.log1p(rfm["monetary"]),
    ])
    feats = StandardScaler().fit_transform(feats)
    km = KMeans(n_clusters=4, random_state=42, n_init=10)
    rfm["cluster"] = km.fit_predict(feats)
    # упорядочим кластеры по средней Monetary → метка «уровня»
    order = rfm.groupby("cluster")["monetary"].mean().sort_values().index
    rank = {c: i for i, c in enumerate(order)}
    names = {0: "Низкая ценность", 1: "Развивающиеся", 2: "Стабильные", 3: "VIP"}
    rfm["cluster_name"] = rfm["cluster"].map(lambda c: names[rank[c]])

    save_table(rfm[["customer_id", "country", "recency_days", "frequency",
                    "monetary", "R", "F", "M", "rfm_score", "segment",
                    "cluster_name"]], "customer_rfm")

    seg_profile = (rfm.groupby("segment")
                      .agg(customers=("customer_id", "count"),
                           avg_recency=("recency_days", "mean"),
                           avg_frequency=("frequency", "mean"),
                           avg_monetary=("monetary", "mean"),
                           total_monetary=("monetary", "sum"))
                      .round(2).reset_index()
                      .sort_values("total_monetary", ascending=False))
    seg_profile["revenue_share"] = (seg_profile["total_monetary"]
                                    / seg_profile["total_monetary"].sum()).round(4)
    save_table(seg_profile, "rfm_segment_profile")

    clu_profile = (rfm.groupby("cluster_name")
                      .agg(customers=("customer_id", "count"),
                           avg_recency=("recency_days", "mean"),
                           avg_frequency=("frequency", "mean"),
                           avg_monetary=("monetary", "mean"),
                           total_monetary=("monetary", "sum"))
                      .round(2).reset_index()
                      .sort_values("avg_monetary", ascending=False))
    save_table(clu_profile, "rfm_cluster_profile")
    log.info("RFM: %d клиентов, сегментов %d, кластеров 4",
             len(rfm), rfm["segment"].nunique())


# --------------------------------------------------------------------------- #
def returns_analysis() -> None:
    monthly = read_sql("SELECT * FROM v_returns_monthly ORDER BY ym")
    save_table(monthly, "returns_monthly")

    by_cat = read_sql("""
        SELECT p.category,
               ROUND(SUM(CASE WHEN f.is_return=1 THEN -f.gross_amount ELSE 0 END),2) AS returns_amount,
               ROUND(SUM(CASE WHEN f.is_return=0 THEN  f.gross_amount ELSE 0 END),2) AS gross_revenue
        FROM fact_sales f JOIN dim_product p ON p.product_key = f.product_key
        GROUP BY p.category
        HAVING gross_revenue > 0
        ORDER BY returns_amount DESC
    """)
    by_cat["returns_rate"] = (by_cat["returns_amount"] / by_cat["gross_revenue"]).round(4)
    save_table(by_cat, "returns_by_category")


def main() -> None:
    revenue_trend()
    seasonality()
    prod = abc_analysis()
    top_products(prod)
    by_country()
    rfm_segmentation()
    returns_analysis()
    log.info("Анализ продаж завершён — таблицы в reports/tables/")


if __name__ == "__main__":
    main()
