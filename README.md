# summer-practice-analytics

Учебная информационно-аналитическая система (ИАС) для ознакомительной практики
магистратуры 09.04.02 «Информационно-аналитические системы».

Полный цикл работы с данными: **источник → ETL → хранилище (модель «звезда»)
→ аналитический слой → визуализация и дашборд**.

## Предметная область

Анализ розничных онлайн-продаж на датасете **Online Retail II**
(UCI Machine Learning Repository, №502) — ~1,07 млн транзакций британского
интернет-магазина за 2009–2011 гг.

## Что делает проект

| Этап | Результат |
|---|---|
| **ETL** (`etl/`) | скачивание источника, очистка (дубликаты, типы, возвраты, нормализация стран), построение таблиц измерений и факта |
| **Хранилище** (`database/`) | БД MariaDB `retail_dwh`: staging + «звезда» (`dim_date`, `dim_customer`, `dim_product`, `dim_country`, `fact_sales`) + витрины-представления |
| **Аналитика** (`analytics/`) | KPI, тренды и сезонность, ABC-анализ ассортимента, RFM-сегментация клиентов (правила + KMeans), когортный анализ, возвраты |
| **Визуализация** (`analytics/03_visualization.py`) | 12 графиков Plotly (`reports/figures/`) + статический отчёт `reports/report.html` |
| **Дашборд** (`dashboard/app.py`) | интерактивная панель Streamlit с фильтрами |

## Структура

```
core/        общий код: конфиг (.env), подключение к БД, логирование
etl/         01_extract → 02_transform → 03_load  (+ run_pipeline.py)
database/    SQL-скрипты: создание БД, схема, SQL-вариант загрузки, витрины и запросы
analytics/   01_kpi_analysis, 02_sales_analysis, 03_visualization
dashboard/   app.py — Streamlit
reports/     figures/  tables/  templates/  index.html  report.html
             build_docx_report.py → Отчет_по_практике.docx
docs/        architecture.md, data_dictionary.md, schema.dbml, runbook.md
data/        raw/ (источник)  processed/ (parquet-снимки)
run_all.py   одна команда: ETL (при необходимости) + аналитика + отчёты
```

## Отчётные документы

| Файл | Что это |
|---|---|
| `reports/index.html` | все интерактивные графики и таблицы на одной странице |
| `reports/report.html` | оформленный аналитический отчёт (KPI, выводы, графики) |
| `reports/Отчет_по_практике.docx` | отчёт по практике с дневником (ГОСТ-оформление) |
| `docs/schema.dbml` | схема БД в формате DBML (dbdiagram.io) |

## Быстрый старт

Разовая подготовка:

```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/plotly_get_chrome -y                    # Chrome для экспорта графиков в PNG
sudo mysql < database/01_create_database.sql      # создать БД и пользователя
```

Затем **одна команда** — прогнать всё и получить отчёт:

```bash
.venv/bin/python run_all.py
```

Она сама создаёт `.env`, при необходимости прогоняет ETL (источник → DWH),
считает аналитику, собирает отчёт и **открывает в браузере** `reports/index.html`
— страницу со всеми интерактивными графиками и таблицами (в WSL — через браузер
Windows). Повторный запуск пропускает ETL (хранилище уже заполнено);
`--reload` — пересобрать с нуля, `--dashboard` — ещё и открыть дашборд Streamlit.

```bash
.venv/bin/python run_all.py --dashboard           # + http://localhost:8501
```

Пошаговый запуск и детали — [`docs/runbook.md`](docs/runbook.md).
Архитектура — [`docs/architecture.md`](docs/architecture.md).

## Стек

Python 3.12 · pandas · SQLAlchemy + PyMySQL · MariaDB 10.11 · scikit-learn ·
Plotly · Streamlit · Jinja2.
