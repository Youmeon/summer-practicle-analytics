-- =============================================================================
--  04_analytics_queries.sql
--  Аналитический слой: витрины-представления (VIEW) поверх «звезды»
--  + набор демонстрационных аналитических запросов для отчёта.
--
--  Витрины создаются автоматически из etl/03_load.py.
--  Запросы в конце файла можно выполнять по отдельности в клиенте mysql.
-- =============================================================================

-- ======================  ВИТРИНЫ  ============================================

DROP VIEW IF EXISTS v_revenue_monthly;
CREATE VIEW v_revenue_monthly AS
SELECT
    d.ym                                                        AS ym,
    ROUND(SUM(CASE WHEN f.is_return = 0 THEN f.gross_amount ELSE 0 END), 2) AS gross_revenue,
    ROUND(SUM(CASE WHEN f.is_return = 1 THEN -f.gross_amount ELSE 0 END), 2) AS returns_amount,
    ROUND(SUM(f.gross_amount), 2)                                       AS net_revenue,
    COUNT(DISTINCT CASE WHEN f.is_return = 0 THEN f.invoice_no END)     AS orders,
    COUNT(DISTINCT CASE WHEN f.is_return = 0 THEN f.customer_key END)   AS customers,
    SUM(CASE WHEN f.is_return = 0 THEN f.quantity ELSE 0 END)           AS units,
    ROUND(
        SUM(CASE WHEN f.is_return = 0 THEN f.gross_amount ELSE 0 END)
        / NULLIF(COUNT(DISTINCT CASE WHEN f.is_return = 0 THEN f.invoice_no END), 0)
    , 2)                                                                AS avg_order_value
FROM fact_sales f
JOIN dim_date d ON d.date_key = f.date_key
GROUP BY d.ym;

DROP VIEW IF EXISTS v_top_products;
CREATE VIEW v_top_products AS
SELECT
    p.product_key,
    p.stock_code,
    p.description,
    p.category,
    ROUND(SUM(CASE WHEN f.is_return = 0 THEN f.gross_amount ELSE 0 END), 2) AS revenue,
    SUM(CASE WHEN f.is_return = 0 THEN f.quantity ELSE 0 END)               AS units,
    COUNT(DISTINCT f.invoice_no)                                           AS invoices
FROM fact_sales f
JOIN dim_product p ON p.product_key = f.product_key
WHERE p.is_service = 0
GROUP BY p.product_key, p.stock_code, p.description, p.category;

DROP VIEW IF EXISTS v_sales_by_country;
CREATE VIEW v_sales_by_country AS
SELECT
    c.country_key,
    c.country_name,
    c.region,
    ROUND(SUM(CASE WHEN f.is_return = 0 THEN f.gross_amount ELSE 0 END), 2) AS revenue,
    COUNT(DISTINCT CASE WHEN f.is_return = 0 THEN f.invoice_no END)         AS orders,
    COUNT(DISTINCT f.customer_key)                                         AS customers
FROM fact_sales f
JOIN dim_country c ON c.country_key = f.country_key
GROUP BY c.country_key, c.country_name, c.region;

DROP VIEW IF EXISTS v_customer_rfm;
CREATE VIEW v_customer_rfm AS
SELECT
    f.customer_key,
    dc.customer_id,
    dc.country,
    DATEDIFF((SELECT MAX(invoice_ts) FROM fact_sales), MAX(f.invoice_ts)) AS recency_days,
    COUNT(DISTINCT CASE WHEN f.is_return = 0 THEN f.invoice_no END)        AS frequency,
    ROUND(SUM(CASE WHEN f.is_return = 0 THEN f.gross_amount ELSE 0 END), 2) AS monetary
FROM fact_sales f
JOIN dim_customer dc ON dc.customer_key = f.customer_key
WHERE f.customer_key <> -1
GROUP BY f.customer_key, dc.customer_id, dc.country
HAVING frequency > 0;

DROP VIEW IF EXISTS v_returns_monthly;
CREATE VIEW v_returns_monthly AS
SELECT
    d.ym                                                            AS ym,
    ROUND(SUM(CASE WHEN f.is_return = 1 THEN -f.gross_amount ELSE 0 END), 2) AS returns_amount,
    ROUND(SUM(CASE WHEN f.is_return = 0 THEN f.gross_amount ELSE 0 END), 2)  AS gross_revenue,
    ROUND(
        SUM(CASE WHEN f.is_return = 1 THEN -f.gross_amount ELSE 0 END)
        / NULLIF(SUM(CASE WHEN f.is_return = 0 THEN f.gross_amount ELSE 0 END), 0)
    , 4)                                                                    AS returns_rate
FROM fact_sales f
JOIN dim_date d ON d.date_key = f.date_key
GROUP BY d.ym;

DROP VIEW IF EXISTS v_cohort_retention;
CREATE VIEW v_cohort_retention AS
WITH first_purchase AS (
    SELECT customer_key,
           DATE_FORMAT(MIN(invoice_ts), '%Y-%m-01') AS cohort_month
    FROM fact_sales
    WHERE is_return = 0 AND customer_key <> -1
    GROUP BY customer_key
),
activity AS (
    SELECT DISTINCT customer_key,
           DATE_FORMAT(invoice_ts, '%Y-%m-01') AS activity_month
    FROM fact_sales
    WHERE is_return = 0 AND customer_key <> -1
)
SELECT
    fp.cohort_month,
    TIMESTAMPDIFF(MONTH, fp.cohort_month, a.activity_month) AS month_index,
    COUNT(DISTINCT a.customer_key)                          AS active_customers
FROM first_purchase fp
JOIN activity a ON a.customer_key = fp.customer_key
GROUP BY fp.cohort_month, month_index;


-- ======================  ДЕМОНСТРАЦИОННЫЕ ЗАПРОСЫ  ===========================
-- (побочных эффектов не имеют; для отчёта — приложить вывод)

-- Q1. Помесячная динамика выручки, заказов и среднего чека
SELECT * FROM v_revenue_monthly ORDER BY ym;

-- Q2. Топ-15 товаров по выручке
SELECT stock_code, description, category, revenue, units, invoices
FROM v_top_products
ORDER BY revenue DESC
LIMIT 15;

-- Q3. Выручка и клиенты по странам (кроме Великобритании), топ-10
SELECT country_name, region, revenue, orders, customers
FROM v_sales_by_country
WHERE country_name <> 'United Kingdom'
ORDER BY revenue DESC
LIMIT 10;

-- Q4. Доля возвратов по месяцам
SELECT ym, gross_revenue, returns_amount, returns_rate
FROM v_returns_monthly
ORDER BY ym;

-- Q5. ABC-анализ товаров: доля накопленной выручки
-- (оконные функции вынесены в CTE — MariaDB не допускает их внутри CASE)
WITH ranked AS (
    SELECT stock_code, description, revenue,
           100 * SUM(revenue) OVER (ORDER BY revenue DESC)
               / SUM(revenue) OVER () AS cum_pct
    FROM v_top_products
)
SELECT stock_code, description, revenue,
       ROUND(cum_pct, 2) AS cum_revenue_pct,
       CASE WHEN cum_pct <= 80 THEN 'A'
            WHEN cum_pct <= 95 THEN 'B'
            ELSE 'C' END AS abc_class
FROM ranked
ORDER BY revenue DESC
LIMIT 30;

-- Q6. Сводка RFM: средние метрики и число клиентов по квинтилю Monetary
WITH q AS (
    SELECT NTILE(5) OVER (ORDER BY monetary) AS monetary_quintile,
           recency_days, frequency, monetary
    FROM v_customer_rfm
)
SELECT monetary_quintile,
       COUNT(*)                    AS customers,
       ROUND(AVG(recency_days), 1) AS avg_recency_days,
       ROUND(AVG(frequency), 2)    AS avg_frequency,
       ROUND(AVG(monetary), 2)     AS avg_monetary
FROM q
GROUP BY monetary_quintile
ORDER BY monetary_quintile;

-- Q7. Удержание первых шести когорт (widened вручную при необходимости)
SELECT cohort_month, month_index, active_customers
FROM v_cohort_retention
ORDER BY cohort_month, month_index;

-- Q8. Средний чек по дням недели
SELECT
    d.day_of_week,
    d.day_name,
    COUNT(DISTINCT f.invoice_no)                          AS orders,
    ROUND(SUM(f.gross_amount) / COUNT(DISTINCT f.invoice_no), 2) AS avg_order_value
FROM fact_sales f
JOIN dim_date d ON d.date_key = f.date_key
WHERE f.is_return = 0
GROUP BY d.day_of_week, d.day_name
ORDER BY d.day_of_week;
