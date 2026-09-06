-- =============================================================================
--  03_load_data.sql
--  SQL-вариант трансформации: наполнение «звезды» из staging средствами СУБД.
--
--  Основной конвейер проекта — Python (etl/02_transform.py + etl/03_load.py).
--  Этот скрипт реализует ТУ ЖЕ логику очистки и загрузки чистым SQL и может
--  выполняться самостоятельно после того, как заполнена таблица
--  stg_online_retail:
--      mysql retail_dwh < database/03_load_data.sql
--
--  Требует MariaDB 10.2+ (оконные функции) / 10.11 (рекурсивные CTE).
-- =============================================================================

SET FOREIGN_KEY_CHECKS = 0;
TRUNCATE TABLE fact_sales;
TRUNCATE TABLE dim_date;
TRUNCATE TABLE dim_customer;
TRUNCATE TABLE dim_product;
TRUNCATE TABLE dim_country;
SET FOREIGN_KEY_CHECKS = 1;

-- ---------------------------------------------------------------------------
-- 1. dim_date — календарный спайн на диапазон дат из staging (рекурсивный CTE)
-- ---------------------------------------------------------------------------
INSERT INTO dim_date
WITH RECURSIVE bounds AS (
    SELECT
        MIN(DATE(STR_TO_DATE(invoice_date, '%Y-%m-%d %H:%i:%s'))) AS d_min,
        MAX(DATE(STR_TO_DATE(invoice_date, '%Y-%m-%d %H:%i:%s'))) AS d_max
    FROM stg_online_retail
),
calendar AS (
    SELECT d_min AS d, d_max FROM bounds
    UNION ALL
    SELECT d + INTERVAL 1 DAY, d_max FROM calendar WHERE d < d_max
)
SELECT
    CAST(DATE_FORMAT(d, '%Y%m%d') AS UNSIGNED)        AS date_key,
    d                                                 AS full_date,
    YEAR(d)                                            AS year,
    QUARTER(d)                                         AS quarter,
    MONTH(d)                                           AS month,
    DATE_FORMAT(d, '%M')                               AS month_name,
    DATE_FORMAT(d, '%Y-%m')                            AS ym,
    WEEK(d, 3)                                         AS week_iso,
    DAYOFMONTH(d)                                      AS day_of_month,
    WEEKDAY(d) + 1                                     AS day_of_week,   -- 1=Пн
    DATE_FORMAT(d, '%W')                               AS day_name,
    CASE WHEN WEEKDAY(d) >= 5 THEN 1 ELSE 0 END        AS is_weekend
FROM calendar;

-- ---------------------------------------------------------------------------
--  Промежуточное представление: staging, приведённый к типам и очищенный.
--  Правила совпадают с etl/02_transform.py.
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS v_stg_clean;
CREATE VIEW v_stg_clean AS
SELECT
    TRIM(invoice)                                              AS invoice_no,
    UPPER(TRIM(stock_code))                                    AS stock_code,
    NULLIF(TRIM(description), '')                              AS description,
    CAST(quantity AS SIGNED)                                   AS quantity,
    STR_TO_DATE(invoice_date, '%Y-%m-%d %H:%i:%s')             AS invoice_ts,
    CAST(price AS DECIMAL(12,4))                               AS unit_price,
    CASE WHEN TRIM(COALESCE(customer_id, '')) = '' THEN NULL
         ELSE CAST(CAST(customer_id AS DECIMAL(12,0)) AS SIGNED) END AS customer_id,
    CASE
        WHEN TRIM(country) IN ('', 'Unspecified')  THEN 'Unknown'
        WHEN TRIM(country) = 'EIRE'                THEN 'Ireland'
        WHEN TRIM(country) = 'USA'                 THEN 'United States'
        WHEN TRIM(country) = 'RSA'                 THEN 'South Africa'
        WHEN TRIM(country) = 'Channel Islands'     THEN 'Channel Islands'
        ELSE TRIM(country)
    END                                                        AS country_name,
    CASE WHEN TRIM(invoice) LIKE 'C%' THEN 1 ELSE 0 END        AS is_return,
    CASE WHEN UPPER(TRIM(stock_code)) IN
        ('POST','DOT','M','MANUAL','BANK CHARGES','C2','CRUK','PADS','AMAZONFEE','ADJUST','ADJUST2')
        OR UPPER(TRIM(stock_code)) REGEXP '^(D|S|B)$'
        THEN 1 ELSE 0 END                                      AS is_service
-- дедупликация по _row_hash повторяет df.drop_duplicates() из Python-ETL
FROM (SELECT * FROM stg_online_retail GROUP BY _row_hash) s
WHERE quantity REGEXP '^-?[0-9]+$'
  AND price    REGEXP '^-?[0-9]+(\\.[0-9]+)?$'
  AND CAST(price AS DECIMAL(12,4)) > 0
  AND STR_TO_DATE(invoice_date, '%Y-%m-%d %H:%i:%s') IS NOT NULL
  AND (
        (TRIM(invoice) NOT LIKE 'C%' AND CAST(quantity AS SIGNED) > 0)
     OR (TRIM(invoice)     LIKE 'C%' AND CAST(quantity AS SIGNED) < 0)
  );

-- ---------------------------------------------------------------------------
-- 2. dim_country
-- ---------------------------------------------------------------------------
INSERT INTO dim_country (country_key, country_name, region)
SELECT
    ROW_NUMBER() OVER (ORDER BY country_name) AS country_key,
    country_name,
    CASE
        WHEN country_name = 'United Kingdom' THEN 'UK'
        WHEN country_name IN ('Ireland','France','Germany','Spain','Portugal',
             'Italy','Belgium','Netherlands','Switzerland','Austria','Norway',
             'Sweden','Finland','Denmark','Poland','Czech Republic','Greece',
             'Cyprus','Malta','Lithuania','Iceland','Channel Islands','Lebanon',
             'European Community') THEN 'Europe'
        WHEN country_name = 'Unknown' THEN 'Other'
        ELSE 'World'
    END AS region
FROM (SELECT DISTINCT country_name FROM v_stg_clean) c;

-- ---------------------------------------------------------------------------
-- 3. dim_product  (эталонное описание = самое частое для артикула)
-- ---------------------------------------------------------------------------
INSERT INTO dim_product (product_key, stock_code, description, category, is_service)
SELECT
    ROW_NUMBER() OVER (ORDER BY p.stock_code) AS product_key,
    p.stock_code,
    COALESCE(p.description, '')               AS description,
    CASE
        WHEN p.is_service = 1 THEN 'SERVICE'
        WHEN p.description REGEXP 'BAG|BASKET|BOX'            THEN 'STORAGE'
        WHEN p.description REGEXP 'LIGHT|LAMP|CANDLE|LANTERN' THEN 'LIGHTING'
        WHEN p.description REGEXP 'MUG|CUP|BOWL|PLATE|JUG|TEAPOT|BOTTLE' THEN 'KITCHEN'
        WHEN p.description REGEXP 'CARD|WRAP|GIFT|RIBBON|TAG'  THEN 'GIFT & STATIONERY'
        WHEN p.description REGEXP 'CHRISTMAS|EASTER|VALENTINE|HALLOWEEN' THEN 'SEASONAL'
        WHEN p.description REGEXP 'HEART|SIGN|FRAME|CLOCK|HOOK|DECORATION' THEN 'HOME DECOR'
        WHEN p.description REGEXP 'BABY|CHILD|KIDS|TOY|GAME'   THEN 'KIDS & TOYS'
        WHEN p.description REGEXP 'GARDEN|PLANT|FLOWER'        THEN 'GARDEN'
        ELSE 'OTHER'
    END AS category,
    p.is_service
FROM (
    SELECT
        stock_code,
        is_service,
        SUBSTRING_INDEX(
            GROUP_CONCAT(description ORDER BY description SEPARATOR '||'), '||', 1
        ) AS description
    FROM v_stg_clean
    WHERE description IS NOT NULL
    GROUP BY stock_code, is_service
) p;

-- артикулы, у которых вообще не было описания
INSERT INTO dim_product (product_key, stock_code, description, category, is_service)
SELECT
    (SELECT COALESCE(MAX(product_key), 0) FROM dim_product)
        + ROW_NUMBER() OVER (ORDER BY s.stock_code),
    s.stock_code, '', 'OTHER', MAX(s.is_service)
FROM v_stg_clean s
LEFT JOIN dim_product d ON d.stock_code = s.stock_code
WHERE d.product_key IS NULL
GROUP BY s.stock_code;

-- ---------------------------------------------------------------------------
-- 4. dim_customer  (+ строка -1 под покупки без идентификатора)
-- ---------------------------------------------------------------------------
INSERT INTO dim_customer
    (customer_key, customer_id, is_guest, country, first_order_date, last_order_date, orders_count)
VALUES (-1, NULL, 1, 'Unknown', NULL, NULL, 0);

INSERT INTO dim_customer
    (customer_key, customer_id, is_guest, country, first_order_date, last_order_date, orders_count)
SELECT
    ROW_NUMBER() OVER (ORDER BY customer_id) AS customer_key,
    customer_id,
    0 AS is_guest,
    -- страна клиента = страна его последнего заказа
    SUBSTRING_INDEX(
        GROUP_CONCAT(country_name ORDER BY invoice_ts DESC SEPARATOR '||'), '||', 1
    ) AS country,
    MIN(DATE(invoice_ts)) AS first_order_date,
    MAX(DATE(invoice_ts)) AS last_order_date,
    COUNT(DISTINCT invoice_no) AS orders_count
FROM v_stg_clean
WHERE customer_id IS NOT NULL
GROUP BY customer_id;

-- ---------------------------------------------------------------------------
-- 5. fact_sales
-- ---------------------------------------------------------------------------
INSERT INTO fact_sales
    (date_key, customer_key, product_key, country_key,
     invoice_no, invoice_ts, quantity, unit_price, gross_amount, is_return)
SELECT
    CAST(DATE_FORMAT(s.invoice_ts, '%Y%m%d') AS UNSIGNED)   AS date_key,
    COALESCE(dc.customer_key, -1)                           AS customer_key,
    dp.product_key,
    co.country_key,
    s.invoice_no,
    s.invoice_ts,
    s.quantity,
    CAST(s.unit_price AS DECIMAL(10,2))                     AS unit_price,
    CAST(s.quantity * s.unit_price AS DECIMAL(12,2))        AS gross_amount,
    s.is_return
FROM v_stg_clean s
JOIN dim_product  dp ON dp.stock_code   = s.stock_code
JOIN dim_country  co ON co.country_name = s.country_name
LEFT JOIN dim_customer dc ON dc.customer_id = s.customer_id;

SELECT
    (SELECT COUNT(*) FROM fact_sales)    AS fact_rows,
    (SELECT COUNT(*) FROM dim_customer)  AS customers,
    (SELECT COUNT(*) FROM dim_product)   AS products,
    (SELECT COUNT(*) FROM dim_country)   AS countries,
    (SELECT COUNT(*) FROM dim_date)      AS dates;
