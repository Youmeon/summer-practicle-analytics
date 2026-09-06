"""Аналитика · визуализация и сборка отчёта.

Строит графики (Plotly) по витринам хранилища, сохраняет их в
reports/figures/ в двух форматах — .png (для Word) и .html (интерактивные),
затем собирает статический отчёт reports/report.html (шаблон Jinja2).

Запуск:  python analytics/03_visualization.py
"""
from __future__ import annotations

import base64
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from jinja2 import Environment, FileSystemLoader, select_autoescape

from analytics._common import fmt_gbp, log, pct
from core.config import FIGURES_DIR, REPORTS_DIR, TABLES_DIR
from core.db import read_sql

PALETTE = dict(primary="#2563eb", accent="#f97316", muted="#94a3b8",
               good="#16a34a", bad="#dc2626", ink="#0f172a")
SEQ = ["#2563eb", "#f97316", "#16a34a", "#dc2626", "#9333ea",
       "#0891b2", "#ca8a04", "#64748b", "#db2777", "#4d7c0f"]

pio.templates.default = "plotly_white"
FIG_W, FIG_H = 1000, 560

# name -> заголовок графика (заполняется в save_fig, используется в index.html)
FIG_TITLES: dict[str, str] = {}

# файл таблицы -> человекочитаемое название для index.html
TABLE_TITLES = {
    "kpi_summary": "Ключевые показатели",
    "revenue_monthly": "Выручка по месяцам",
    "seasonality_by_month": "Сезонность по календарным месяцам",
    "seasonality_by_dow": "Активность по дням недели",
    "abc_summary": "ABC-анализ: сводка по классам",
    "abc_products": "ABC-анализ: товары (полный список)",
    "top20_products": "Топ-20 товаров по выручке",
    "revenue_by_category": "Выручка по категориям",
    "top15_countries": "Топ-15 стран по выручке",
    "revenue_by_region": "Выручка по регионам",
    "customer_rfm": "RFM по каждому клиенту",
    "rfm_segment_profile": "RFM: профиль сегментов",
    "rfm_cluster_profile": "RFM: профиль кластеров KMeans",
    "returns_monthly": "Возвраты по месяцам",
    "returns_by_category": "Возвраты по категориям",
}

# приглушаем подробный лог движка экспорта PNG (kaleido/Chrome)
for _n in ("choreographer", "kaleido"):
    __import__("logging").getLogger(_n).setLevel(__import__("logging").WARNING)


def save_fig(fig: go.Figure, name: str, *, title: str) -> str:
    fig.update_layout(
        title=dict(text=title, x=0.02, font=dict(size=17, color=PALETTE["ink"])),
        margin=dict(l=60, r=40, t=60, b=55),
        font=dict(family="Segoe UI, Roboto, sans-serif", size=13),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        width=FIG_W, height=FIG_H,
    )
    png = FIGURES_DIR / f"{name}.png"
    fig.write_image(png, scale=2)
    fig.write_html(FIGURES_DIR / f"{name}.html", include_plotlyjs="cdn",
                   full_html=True, config={"displaylogo": False})
    FIG_TITLES[name] = title
    log.info("график → %s", png.name)
    return name


# --------------------------------------------------------------------------- #
def fig_revenue_trend() -> str:
    df = read_sql("SELECT * FROM v_revenue_monthly ORDER BY ym")
    ma3 = df["gross_revenue"].rolling(3, min_periods=1).mean()
    fig = go.Figure()
    fig.add_bar(x=df["ym"], y=df["returns_amount"], name="Возвраты",
                marker_color=PALETTE["muted"], opacity=0.6)
    fig.add_scatter(x=df["ym"], y=df["gross_revenue"], name="Валовая выручка",
                    mode="lines+markers", line=dict(color=PALETTE["primary"], width=3))
    fig.add_scatter(x=df["ym"], y=ma3, name="Скользящее среднее (3 мес.)",
                    mode="lines", line=dict(color=PALETTE["accent"], width=2, dash="dash"))
    fig.update_yaxes(title="GBP")
    return save_fig(fig, "revenue_trend", title="Помесячная динамика выручки и возвратов")


def fig_orders_aov() -> str:
    df = read_sql("SELECT * FROM v_revenue_monthly ORDER BY ym")
    fig = go.Figure()
    fig.add_bar(x=df["ym"], y=df["orders"], name="Заказы",
                marker_color=PALETTE["primary"], opacity=0.65, yaxis="y1")
    fig.add_scatter(x=df["ym"], y=df["avg_order_value"], name="Средний чек (AOV)",
                    mode="lines+markers", line=dict(color=PALETTE["accent"], width=3),
                    yaxis="y2")
    fig.update_layout(
        yaxis=dict(title="Заказы"),
        yaxis2=dict(title="AOV, GBP", overlaying="y", side="right", showgrid=False),
    )
    return save_fig(fig, "orders_aov", title="Число заказов и средний чек по месяцам")


def fig_seasonality_month() -> str:
    df = pd.read_csv(TABLES_DIR / "seasonality_by_month.csv")
    fig = go.Figure(go.Bar(x=df["month_name"], y=df["revenue"],
                           marker_color=PALETTE["primary"]))
    fig.update_yaxes(title="GBP")
    return save_fig(fig, "seasonality_month",
                    title="Сезонность: суммарная выручка по календарным месяцам")


def fig_seasonality_dow() -> str:
    df = pd.read_csv(TABLES_DIR / "seasonality_by_dow.csv")
    fig = go.Figure()
    fig.add_bar(x=df["day_name"], y=df["orders"], name="Заказы",
                marker_color=PALETTE["muted"], yaxis="y1")
    fig.add_scatter(x=df["day_name"], y=df["avg_order_value"], name="AOV",
                    mode="lines+markers", line=dict(color=PALETTE["accent"], width=3),
                    yaxis="y2")
    fig.update_layout(
        yaxis=dict(title="Заказы"),
        yaxis2=dict(title="AOV, GBP", overlaying="y", side="right", showgrid=False),
    )
    return save_fig(fig, "seasonality_dow", title="Активность и средний чек по дням недели")


def fig_abc_pareto() -> str:
    df = pd.read_csv(TABLES_DIR / "abc_products.csv").reset_index(drop=True)
    x = np.arange(1, len(df) + 1)
    cum = 100 * df["cum_share"].to_numpy()
    n_a = int((df["abc_class"] == "A").sum())
    n_b = int((df["abc_class"] == "B").sum())

    fig = go.Figure()
    # заливка зон A / B / C под кривой
    for lo, hi, color, label in [
        (0, n_a, "rgba(22,163,74,0.14)", f"A · {n_a} тов."),
        (n_a, n_a + n_b, "rgba(249,115,22,0.14)", f"B · {n_b} тов."),
        (n_a + n_b, len(df), "rgba(148,163,184,0.16)", f"C · {len(df) - n_a - n_b} тов."),
    ]:
        fig.add_vrect(x0=lo + 0.5, x1=hi + 0.5, fillcolor=color, line_width=0,
                      annotation_text=label, annotation_position="bottom",
                      annotation_font_size=12)
    fig.add_scatter(x=x, y=cum, name="Накопленная доля выручки",
                    mode="lines", line=dict(color=PALETTE["primary"], width=3))
    for lvl in (80, 95):
        fig.add_hline(y=lvl, line=dict(color=PALETTE["muted"], width=1, dash="dot"),
                      annotation_text=f"{lvl}%", annotation_position="right")
    fig.update_layout(
        xaxis=dict(title="Товары, ранжированные по убыванию выручки"),
        yaxis=dict(title="Накопленная доля выручки, %", range=[0, 101]),
        showlegend=False,
    )
    return save_fig(fig, "abc_pareto", title="ABC-анализ ассортимента (кривая Парето)")


def fig_category_revenue() -> str:
    df = pd.read_csv(TABLES_DIR / "revenue_by_category.csv").sort_values("revenue")
    fig = go.Figure(go.Bar(x=df["revenue"], y=df["category"], orientation="h",
                           marker_color=PALETTE["primary"]))
    fig.update_xaxes(title="GBP")
    return save_fig(fig, "category_revenue", title="Выручка по товарным категориям")


def fig_top_products() -> str:
    df = pd.read_csv(TABLES_DIR / "top20_products.csv").head(15).sort_values("revenue")
    label = df["description"].str.slice(0, 34) + " (" + df["stock_code"] + ")"
    fig = go.Figure(go.Bar(x=df["revenue"], y=label, orientation="h",
                           marker_color=PALETTE["accent"]))
    fig.update_xaxes(title="GBP")
    return save_fig(fig, "top_products", title="Топ-15 товаров по выручке")


def fig_country_revenue() -> str:
    df = read_sql("""SELECT country_name, revenue FROM v_sales_by_country
                     WHERE country_name <> 'United Kingdom'
                     ORDER BY revenue DESC LIMIT 12""").sort_values("revenue")
    fig = go.Figure(go.Bar(x=df["revenue"], y=df["country_name"], orientation="h",
                           marker_color=PALETTE["primary"]))
    fig.update_xaxes(title="GBP")
    return save_fig(fig, "country_revenue",
                    title="Топ-12 стран по выручке (без Великобритании)")


def fig_rfm_segments() -> str:
    df = pd.read_csv(TABLES_DIR / "rfm_segment_profile.csv")
    fig = go.Figure()
    fig.add_bar(x=df["segment"], y=df["customers"], name="Клиентов",
                marker_color=PALETTE["muted"], yaxis="y1")
    fig.add_scatter(x=df["segment"], y=100 * df["revenue_share"], name="Доля выручки, %",
                    mode="lines+markers", line=dict(color=PALETTE["accent"], width=3),
                    yaxis="y2")
    fig.update_layout(
        yaxis=dict(title="Число клиентов"),
        yaxis2=dict(title="Доля выручки, %", overlaying="y", side="right", showgrid=False),
    )
    return save_fig(fig, "rfm_segments", title="RFM-сегменты: размер и вклад в выручку")


def fig_rfm_scatter() -> str:
    df = pd.read_csv(TABLES_DIR / "customer_rfm.csv")
    df = df[(df["frequency"] > 0) & (df["monetary"] > 0)]
    fig = go.Figure()
    for i, (name, g) in enumerate(df.groupby("cluster_name")):
        fig.add_scatter(x=g["frequency"], y=g["monetary"], mode="markers", name=name,
                        marker=dict(size=6, opacity=0.55, color=SEQ[i % len(SEQ)]))
    fig.update_xaxes(title="Частота покупок (заказов)", type="log")
    fig.update_yaxes(title="Оборот клиента, GBP", type="log")
    return save_fig(fig, "rfm_scatter",
                    title="Клиенты в осях «частота — оборот» (кластеры KMeans)")


def fig_cohort_heatmap() -> str:
    df = read_sql("SELECT * FROM v_cohort_retention ORDER BY cohort_month, month_index")
    if df.empty:
        return ""
    piv = df.pivot(index="cohort_month", columns="month_index", values="active_customers")
    base = piv[0]
    ret = piv.div(base, axis=0).round(3)
    ret = ret.iloc[:13, :13]
    z = (ret.values * 100)
    txt = [["" if np.isnan(v) else f"{v:.0f}" for v in row] for row in z]
    fig = go.Figure(go.Heatmap(
        z=z, x=[f"+{c}" for c in ret.columns], y=[str(i) for i in ret.index],
        colorscale="Blues", zmin=0, zmax=100,
        text=txt, texttemplate="%{text}", textfont=dict(size=10),
        colorbar=dict(title="%"),
    ))
    fig.update_xaxes(title="Месяцев с первой покупки")
    fig.update_yaxes(title="Когорта (месяц первой покупки)", autorange="reversed")
    return save_fig(fig, "cohort_heatmap",
                    title="Удержание клиентов по когортам, % от размера когорты")


def fig_returns_trend() -> str:
    df = read_sql("SELECT * FROM v_returns_monthly ORDER BY ym")
    fig = go.Figure()
    fig.add_bar(x=df["ym"], y=df["returns_amount"], name="Сумма возвратов",
                marker_color=PALETTE["muted"])
    fig.add_scatter(x=df["ym"], y=100 * df["returns_rate"],
                    name="Доля возвратов, %", mode="lines+markers",
                    line=dict(color=PALETTE["bad"], width=3), yaxis="y2")
    fig.update_layout(
        yaxis=dict(title="GBP"),
        yaxis2=dict(title="Доля возвратов, %", overlaying="y", side="right", showgrid=False),
    )
    return save_fig(fig, "returns_trend", title="Возвраты: сумма и доля от валовой выручки")


# --------------------------------------------------------------------------- #
def _b64(name: str) -> str:
    data = (FIGURES_DIR / f"{name}.png").read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def build_report(figures: list[str]) -> None:
    kpi = json.loads((TABLES_DIR / "kpi_summary.json").read_text(encoding="utf-8"))
    abc = pd.read_csv(TABLES_DIR / "abc_summary.csv")
    seg = pd.read_csv(TABLES_DIR / "rfm_segment_profile.csv")
    countries = pd.read_csv(TABLES_DIR / "top15_countries.csv")
    top = pd.read_csv(TABLES_DIR / "top20_products.csv").head(10)

    a_row = abc[abc["abc_class"] == "A"].iloc[0]
    uk_share = countries.loc[countries["country_name"] == "United Kingdom", "revenue"].sum() \
        / countries["revenue"].sum()

    kpi_cards = [
        ("Валовая выручка", fmt_gbp(kpi["gross_revenue"])),
        ("Чистая выручка", fmt_gbp(kpi["net_revenue"])),
        ("Заказов", f'{kpi["orders"]:,}'),
        ("Клиентов", f'{kpi["customers"]:,}'),
        ("Средний чек", fmt_gbp(kpi["avg_order_value"])),
        ("Доля возвратов", pct(kpi["returns_rate"])),
        ("Выручка на клиента", fmt_gbp(kpi["revenue_per_customer"])),
        ("Лучший месяц", f'{kpi["best_month"]}'),
    ]

    findings = [
        f'Период данных — {kpi["period"]} ({kpi["months"]} мес.). '
        f'Валовая выручка {fmt_gbp(kpi["gross_revenue"])}, чистая '
        f'{fmt_gbp(kpi["net_revenue"])} при доле возвратов {pct(kpi["returns_rate"])}.',
        f'Ассортимент подчиняется правилу Парето: {int(a_row["products"])} товаров '
        f'класса A ({pct(a_row["products_share"])} позиций) дают '
        f'{pct(a_row["revenue_share"])} выручки.',
        f'Рынок сильно сконцентрирован географически: на Великобританию приходится '
        f'{pct(uk_share)} выручки топ-15 стран.',
        f'Продажи выражено сезонны — пик приходится на осенне-зимние месяцы '
        f'(подготовка к рождественскому сезону).',
        f'Клиентская база по RFM делится на {len(seg)} сегментов; сегмент '
        f'«{seg.iloc[0]["segment"]}» обеспечивает {pct(seg.iloc[0]["revenue_share"])} оборота.',
        f'Доля «гостевых» продаж (без идентификатора клиента) — '
        f'{pct(kpi["guest_revenue_share"])}; это ограничивает точность '
        f'клиентской аналитики и является точкой улучшения источника данных.',
    ]

    env = Environment(
        loader=FileSystemLoader(REPORTS_DIR / "templates"),
        autoescape=select_autoescape(["html"]),
    )
    tpl = env.get_template("report.html.j2")
    html = tpl.render(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        kpi_cards=kpi_cards,
        findings=findings,
        figures=[{"name": n, "src": _b64(n)} for n in figures if n],
        abc=abc.to_dict("records"),
        seg=seg.to_dict("records"),
        top=top.to_dict("records"),
        countries=countries.head(10).to_dict("records"),
    )
    out = REPORTS_DIR / "report.html"
    out.write_text(html, encoding="utf-8")
    log.info("Отчёт собран → %s", out)


def build_index(figures: list[str]) -> None:
    """Единая навигационная страница: отчёт + интерактивные графики + все таблицы."""
    parts: list[str] = [f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
<title>Аналитика розничных продаж — результаты</title>
<style>
 body{{margin:0;font-family:"Segoe UI",Roboto,Arial,sans-serif;color:#0f172a;background:#f8fafc}}
 .wrap{{max-width:1160px;margin:0 auto;padding:32px 24px 90px}}
 h1{{font-size:24px;margin:0 0 4px}} h2{{font-size:19px;margin:38px 0 12px;
   border-top:1px solid #e2e8f0;padding-top:14px}}
 h3{{font-size:15px;margin:26px 0 8px;color:#334155}}
 .sub{{color:#64748b;font-size:13px}}
 a.btn{{display:inline-block;margin:10px 8px 0 0;padding:9px 15px;border-radius:8px;
   background:#2563eb;color:#fff;text-decoration:none;font-size:14px}}
 nav a{{margin-right:14px;font-size:13px;color:#2563eb}}
 iframe.fig{{width:100%;height:600px;border:1px solid #e2e8f0;border-radius:10px;background:#fff}}
 .tbl-wrap{{overflow-x:auto;border:1px solid #e2e8f0;border-radius:10px;background:#fff}}
 table{{border-collapse:collapse;width:100%;font-size:12.5px}}
 th,td{{padding:6px 10px;border-bottom:1px solid #eef2f7;text-align:right;white-space:nowrap}}
 th:first-child,td:first-child{{text-align:left}}
 thead th{{background:#eef2ff;position:sticky;top:0}}
 details>summary{{cursor:pointer;font-size:13px;color:#64748b;margin:6px 0}}
</style></head><body><div class="wrap">
<h1>Аналитика розничных онлайн-продаж — результаты</h1>
<div class="sub">Источник: Online Retail II (UCI). Сформировано {datetime.now():%Y-%m-%d %H:%M}.</div>
<a class="btn" href="report.html">Полный отчёт (report.html)</a>
<a class="btn" href="figures/">Папка с графиками</a>
<a class="btn" href="tables/">Папка с таблицами (CSV)</a>
<nav style="margin-top:18px">
  <a href="#figs">↓ Графики</a><a href="#tabs">↓ Таблицы</a>
</nav>

<h2 id="figs">Интерактивные графики</h2>"""]

    for name in [f for f in figures if f]:
        title = FIG_TITLES.get(name, name)
        parts.append(
            f'<h3>{title}</h3>'
            f'<iframe class="fig" src="figures/{name}.html" loading="lazy"></iframe>'
            f'<div class="sub"><a href="figures/{name}.html">открыть отдельно</a> · '
            f'<a href="figures/{name}.png">PNG</a></div>'
        )

    parts.append('<h2 id="tabs">Таблицы</h2>')
    for csv in sorted(TABLES_DIR.glob("*.csv")):
        key = csv.stem
        title = TABLE_TITLES.get(key, key)
        df = pd.read_csv(csv)
        big = len(df) > 60
        shown = df.head(60) if big else df
        table_html = shown.to_html(index=False, border=0, justify="right",
                                   float_format=lambda v: f"{v:,.2f}")
        block = (f'<h3>{title} <span class="sub">({len(df)} строк, '
                 f'{csv.name})</span></h3><div class="tbl-wrap">{table_html}</div>')
        if big:
            block += (f'<details><summary>показаны первые 60 из {len(df)} — '
                      f'весь файл: {csv.name}</summary></details>')
        parts.append(block)

    parts.append("</div></body></html>")
    out = REPORTS_DIR / "index.html"
    out.write_text("\n".join(parts), encoding="utf-8")
    log.info("Навигационная страница → %s", out)


def main() -> None:
    figures = [
        fig_revenue_trend(),
        fig_orders_aov(),
        fig_seasonality_month(),
        fig_seasonality_dow(),
        fig_abc_pareto(),
        fig_category_revenue(),
        fig_top_products(),
        fig_country_revenue(),
        fig_rfm_segments(),
        fig_rfm_scatter(),
        fig_cohort_heatmap(),
        fig_returns_trend(),
    ]
    build_report(figures)
    build_index(figures)
    log.info("Визуализация завершена — reports/index.html (графики + таблицы) + report.html")


if __name__ == "__main__":
    main()
