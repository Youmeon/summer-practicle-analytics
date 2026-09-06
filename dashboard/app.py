"""Интерактивный дашборд (демо BI) поверх хранилища retail_dwh.

Запуск:  streamlit run dashboard/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import plotly.express as px
import streamlit as st

from core.db import read_sql

st.set_page_config(page_title="Розничные продажи · дашборд", layout="wide")

PX = dict(color_discrete_sequence=px.colors.qualitative.Set2)


@st.cache_data(ttl=3600)
def load_daily() -> pd.DataFrame:
    return read_sql("""
        SELECT d.full_date, d.ym, c.country_name, c.region, p.category,
               ROUND(SUM(CASE WHEN f.is_return=0 THEN f.gross_amount ELSE 0 END),2) AS revenue,
               ROUND(SUM(CASE WHEN f.is_return=1 THEN -f.gross_amount ELSE 0 END),2) AS returns_amount,
               SUM(CASE WHEN f.is_return=0 THEN f.quantity ELSE 0 END) AS units
        FROM fact_sales f
        JOIN dim_date d    ON d.date_key    = f.date_key
        JOIN dim_country c ON c.country_key = f.country_key
        JOIN dim_product p ON p.product_key = f.product_key
        GROUP BY d.full_date, d.ym, c.country_name, c.region, p.category
    """)


@st.cache_data(ttl=3600)
def load_orders() -> pd.DataFrame:
    return read_sql("""
        SELECT d.full_date, c.country_name,
               COUNT(DISTINCT CASE WHEN f.is_return=0 THEN f.invoice_no END) AS orders
        FROM fact_sales f
        JOIN dim_date d    ON d.date_key    = f.date_key
        JOIN dim_country c ON c.country_key = f.country_key
        GROUP BY d.full_date, c.country_name
    """)


@st.cache_data(ttl=3600)
def load_top_products() -> pd.DataFrame:
    return read_sql("SELECT * FROM v_top_products ORDER BY revenue DESC LIMIT 200")


@st.cache_data(ttl=3600)
def load_rfm() -> pd.DataFrame:
    return read_sql("SELECT * FROM v_customer_rfm")


daily = load_daily()
orders = load_orders()
daily["full_date"] = pd.to_datetime(daily["full_date"])
orders["full_date"] = pd.to_datetime(orders["full_date"])

st.title("Аналитика розничных онлайн-продаж")
st.caption("Источник: Online Retail II (UCI). Хранилище: retail_dwh (звезда) → витрины.")

# --- Фильтры --------------------------------------------------------------- #
with st.sidebar:
    st.header("Фильтры")
    dmin, dmax = daily["full_date"].min(), daily["full_date"].max()
    dr = st.date_input("Период", value=(dmin, dmax), min_value=dmin, max_value=dmax)
    if isinstance(dr, tuple) and len(dr) == 2:
        d0, d1 = pd.Timestamp(dr[0]), pd.Timestamp(dr[1])
    else:
        d0, d1 = dmin, dmax
    regions = sorted(daily["region"].unique())
    sel_regions = st.multiselect("Регионы", regions, default=regions)
    cats = sorted(daily["category"].unique())
    sel_cats = st.multiselect("Категории", cats, default=cats)

m = (daily["full_date"].between(d0, d1)
     & daily["region"].isin(sel_regions)
     & daily["category"].isin(sel_cats))
f = daily[m]
countries_in = f["country_name"].unique()
o = orders[orders["full_date"].between(d0, d1) & orders["country_name"].isin(countries_in)]

# --- KPI ----------------------------------------------------------------- #
rev = f["revenue"].sum()
ret = f["returns_amount"].sum()
units = int(f["units"].sum())
n_orders = int(o["orders"].sum())
aov = rev / n_orders if n_orders else 0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Валовая выручка", f"£{rev:,.0f}")
c2.metric("Возвраты", f"£{ret:,.0f}", f"{(ret / rev * 100 if rev else 0):.1f}%")
c3.metric("Заказы", f"{n_orders:,}")
c4.metric("Средний чек", f"£{aov:,.0f}")
c5.metric("Ед. товара", f"{units:,}")

# --- Динамика ----------------------------------------------------------- #
st.subheader("Динамика выручки по месяцам")
by_month = f.groupby("ym", as_index=False)["revenue"].sum()
st.plotly_chart(px.bar(by_month, x="ym", y="revenue", **PX)
                .update_layout(xaxis_title="", yaxis_title="GBP"),
                use_container_width=True)

col_a, col_b = st.columns(2)
with col_a:
    st.subheader("Выручка по категориям")
    by_cat = f.groupby("category", as_index=False)["revenue"].sum().sort_values("revenue")
    st.plotly_chart(px.bar(by_cat, x="revenue", y="category", orientation="h", **PX)
                    .update_layout(xaxis_title="GBP", yaxis_title=""),
                    use_container_width=True)
with col_b:
    st.subheader("Топ-10 стран")
    by_c = (f.groupby("country_name", as_index=False)["revenue"].sum()
              .sort_values("revenue", ascending=False).head(10).sort_values("revenue"))
    st.plotly_chart(px.bar(by_c, x="revenue", y="country_name", orientation="h", **PX)
                    .update_layout(xaxis_title="GBP", yaxis_title=""),
                    use_container_width=True)

# --- Товары и клиенты -------------------------------------------------- #
st.subheader("Топ-15 товаров по выручке (за весь период)")
top = load_top_products()
if sel_cats:
    top = top[top["category"].isin(sel_cats)]
st.dataframe(top.head(15)[["stock_code", "description", "category", "revenue", "units"]],
            use_container_width=True, hide_index=True)

st.subheader("Клиенты в осях «частота — оборот» (RFM)")
rfm = load_rfm()
rfm = rfm[(rfm["frequency"] > 0) & (rfm["monetary"] > 0)]
fig = px.scatter(rfm, x="frequency", y="monetary", log_x=True, log_y=True,
                 opacity=0.5, **PX)
fig.update_layout(xaxis_title="Частота (заказов)", yaxis_title="Оборот, GBP")
st.plotly_chart(fig, use_container_width=True)
