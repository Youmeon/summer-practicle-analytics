"""Аналитика · KPI.

Считает ключевые показатели по данным хранилища и сохраняет их в
reports/tables/kpi_summary.{csv,json} — используется и в отчёте, и в дашборде.

Запуск:  python analytics/01_kpi_analysis.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from tabulate import tabulate

from analytics._common import fmt_gbp, log, pct, save_table
from core.config import TABLES_DIR
from core.db import read_sql


def compute_kpis() -> dict:
    fact = read_sql("""
        SELECT
            SUM(CASE WHEN is_return = 0 THEN gross_amount ELSE 0 END)   AS gross_revenue,
            SUM(CASE WHEN is_return = 1 THEN -gross_amount ELSE 0 END)  AS returns_amount,
            SUM(gross_amount)                                           AS net_revenue,
            SUM(CASE WHEN is_return = 0 THEN quantity ELSE 0 END)       AS units,
            COUNT(DISTINCT CASE WHEN is_return = 0 THEN invoice_no END) AS orders,
            COUNT(DISTINCT CASE WHEN is_return = 0 AND customer_key <> -1
                                THEN customer_key END)                  AS customers,
            MIN(invoice_ts) AS date_min,
            MAX(invoice_ts) AS date_max
        FROM fact_sales
    """).iloc[0]

    monthly = read_sql("SELECT * FROM v_revenue_monthly ORDER BY ym")
    guest_share = read_sql("""
        SELECT
            SUM(CASE WHEN customer_key = -1 THEN gross_amount ELSE 0 END)
            / SUM(gross_amount) AS guest_revenue_share
        FROM fact_sales WHERE is_return = 0
    """).iloc[0]["guest_revenue_share"]

    gross = float(fact["gross_revenue"])
    returns = float(fact["returns_amount"])
    orders = int(fact["orders"])
    customers = int(fact["customers"])
    units = int(fact["units"])

    last, prev = monthly.iloc[-1], monthly.iloc[-2]
    mom = (last["gross_revenue"] - prev["gross_revenue"]) / prev["gross_revenue"]
    best = monthly.loc[monthly["gross_revenue"].idxmax()]

    return {
        "period": f'{fact["date_min"]:%Y-%m-%d} — {fact["date_max"]:%Y-%m-%d}',
        "months": int(len(monthly)),
        "gross_revenue": round(gross, 2),
        "returns_amount": round(returns, 2),
        "net_revenue": round(gross - returns, 2),
        "returns_rate": round(returns / gross, 4),
        "orders": orders,
        "customers": customers,
        "units": units,
        "avg_order_value": round(gross / orders, 2),
        "avg_items_per_order": round(units / orders, 2),
        "revenue_per_customer": round(gross / customers, 2),
        "guest_revenue_share": round(float(guest_share), 4),
        "mom_growth_last": round(float(mom), 4),
        "best_month": str(best["ym"]),
        "best_month_revenue": round(float(best["gross_revenue"]), 2),
    }


def main() -> None:
    kpi = compute_kpis()

    (TABLES_DIR / "kpi_summary.json").write_text(
        json.dumps(kpi, ensure_ascii=False, indent=2), encoding="utf-8")

    pretty = [
        ("Период данных", kpi["period"]),
        ("Месяцев в периоде", kpi["months"]),
        ("Валовая выручка", fmt_gbp(kpi["gross_revenue"])),
        ("Сумма возвратов", fmt_gbp(kpi["returns_amount"])),
        ("Чистая выручка", fmt_gbp(kpi["net_revenue"])),
        ("Доля возвратов", pct(kpi["returns_rate"])),
        ("Заказов", f'{kpi["orders"]:,}'),
        ("Уникальных клиентов", f'{kpi["customers"]:,}'),
        ("Продано единиц товара", f'{kpi["units"]:,}'),
        ("Средний чек (AOV)", fmt_gbp(kpi["avg_order_value"])),
        ("Позиций в заказе", kpi["avg_items_per_order"]),
        ("Выручка на клиента", fmt_gbp(kpi["revenue_per_customer"])),
        ("Доля выручки «гостей»", pct(kpi["guest_revenue_share"])),
        ("Рост выручки M/M (посл.)", pct(kpi["mom_growth_last"])),
        ("Лучший месяц", f'{kpi["best_month"]} ({fmt_gbp(kpi["best_month_revenue"])})'),
    ]
    df = pd.DataFrame(pretty, columns=["Показатель", "Значение"])
    save_table(df, "kpi_summary")
    print("\n" + tabulate(df, headers="keys", tablefmt="github", showindex=False) + "\n")


if __name__ == "__main__":
    main()
