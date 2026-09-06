# Runbook — как запустить проект

## 0. Предварительные требования

- Python 3.12, установлен `venv` в `.venv/` со всеми зависимостями:
  ```bash
  .venv/bin/pip install -r requirements.txt
  ```
- Запущенный сервер MariaDB/MySQL (проект тестировался на MariaDB 10.11 в WSL).

## 1. Конфигурация

```bash
cp .env.example .env
# при необходимости отредактируйте DB_* и параметры ETL_*
```

## 2. Создание базы данных и пользователя (один раз)

Скрипт `database/01_create_database.sql` создаёт базу `retail_dwh` и
пользователя `retail_app`. Его нужно выполнить под административной учётной
записью СУБД:

```bash
sudo mysql < database/01_create_database.sql
```

> Если у вас задан пароль root MySQL:
> `mysql -u root -p < database/01_create_database.sql`

Логин/пароль в этом скрипте должны совпадать с `DB_USER` / `DB_PASSWORD` в `.env`.

Проверка подключения:
```bash
.venv/bin/python -c "from core.db import ping; print('OK' if ping() else 'FAIL')"
```

## 3. Всё одной командой

```bash
.venv/bin/python run_all.py              # ETL (если нужно) + аналитика + отчёт
.venv/bin/python run_all.py --reload     # принудительно пересобрать хранилище
.venv/bin/python run_all.py --dashboard  # то же + запустить дашборд
```

Дальнейшие разделы описывают те же шаги по отдельности.

## 3a. ETL-конвейер

Полный прогон (скачивание → очистка → загрузка в DWH → витрины):

```bash
.venv/bin/python etl/run_pipeline.py
```

или по шагам:

```bash
.venv/bin/python etl/01_extract.py     # xlsx → data/processed/raw_sales.parquet + профиль
.venv/bin/python etl/02_transform.py   # очистка → parquet-таблицы «звезды»
.venv/bin/python etl/03_load.py        # загрузка в MariaDB + создание витрин
```

Ориентировочное время полного прогона: чтение Excel ~40 c, трансформация ~10 c,
загрузка staging + звезды ~2–4 мин.
Чтобы пропустить тяжёлый слой staging: `ETL_LOAD_STAGING=0` в `.env`.
Быстрый прогон на подвыборке: `ETL_SAMPLE_ROWS=50000`, `ETL_FORCE_REBUILD=1`.

## 4. Аналитика и отчёт

```bash
.venv/bin/python analytics/01_kpi_analysis.py    # reports/tables/kpi_summary.*
.venv/bin/python analytics/02_sales_analysis.py  # тренды, ABC, RFM, страны → reports/tables/*.csv
.venv/bin/python analytics/03_visualization.py   # reports/figures/*.png|html + reports/report.html
```

Результаты:
- `reports/index.html` — навигационная страница: все интерактивные графики + таблицы;
- `reports/report.html` — оформленный отчёт (KPI, выводы, графики в PNG);
- `reports/figures/*.png|html`, `reports/tables/*.csv` — по отдельности.

`run_all.py` открывает `reports/index.html` в браузере автоматически.

## 5. Интерактивный дашборд

```bash
.venv/bin/streamlit run dashboard/app.py
```

Откроется на http://localhost:8501.

## 6. SQL-вариант трансформации (опционально)

После загрузки staging можно построить «звезду» чистым SQL вместо Python:

```bash
mysql retail_dwh < database/03_load_data.sql
mysql retail_dwh < database/04_analytics_queries.sql
```

Результаты двух реализаций совпадают по числу клиентов, товаров, стран и дат;
по числу строк факта расхождение около 2 % — из-за пограничных случаев
представления чисел с плавающей точкой как текста в staging. Канонической
считается Python-реализация (`etl/`).

## Проверка результата

```sql
-- в клиенте:  mysql retail_dwh
SELECT * FROM v_revenue_monthly ORDER BY year_month;
SELECT COUNT(*) FROM fact_sales;
```
