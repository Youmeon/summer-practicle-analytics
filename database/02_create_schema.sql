-- =============================================================================
--  02_create_schema.sql
--  DDL хранилища: staging + многомерная модель «звезда» + индексы.
--  Запуск:  выполняется автоматически из etl/03_load.py,
--           либо вручную:  mysql retail_dwh < database/02_create_schema.sql
-- =============================================================================

-- Порядок DROP — от фактов к измерениям (из-за внешних ключей).
DROP VIEW  IF EXISTS v_stg_clean;
DROP TABLE IF EXISTS fact_sales;
DROP TABLE IF EXISTS dim_date;
DROP TABLE IF EXISTS dim_customer;
DROP TABLE IF EXISTS dim_product;
DROP TABLE IF EXISTS dim_country;
DROP TABLE IF EXISTS stg_online_retail;

-- ---------------------------------------------------------------------------
-- STAGING. Сырые данные из Excel «как есть», все содержательные поля — текст.
-- ---------------------------------------------------------------------------
CREATE TABLE stg_online_retail (
    invoice        VARCHAR(32),
    stock_code     VARCHAR(32),
    description    VARCHAR(512),
    quantity       VARCHAR(32),
    invoice_date   VARCHAR(32),
    price          VARCHAR(32),
    customer_id    VARCHAR(32),
    country        VARCHAR(128),
    _source_sheet  VARCHAR(32)  NOT NULL,
    _loaded_at     DATETIME     NOT NULL,
    _row_hash      CHAR(40)     NOT NULL,
    KEY ix_stg_hash (_row_hash),
    KEY ix_stg_invoice (invoice)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- ИЗМЕРЕНИЕ: КАЛЕНДАРЬ
-- ---------------------------------------------------------------------------
CREATE TABLE dim_date (
    date_key      INT          NOT NULL PRIMARY KEY,   -- YYYYMMDD
    full_date     DATE         NOT NULL,
    year          SMALLINT     NOT NULL,
    quarter       TINYINT      NOT NULL,
    month         TINYINT      NOT NULL,
    month_name    VARCHAR(16)  NOT NULL,
    ym    CHAR(7)      NOT NULL,               -- YYYY-MM
    week_iso      TINYINT      NOT NULL,
    day_of_month  TINYINT      NOT NULL,
    day_of_week   TINYINT      NOT NULL,               -- 1=Пн ... 7=Вс
    day_name      VARCHAR(16)  NOT NULL,
    is_weekend    TINYINT      NOT NULL,
    KEY ix_date_ym (ym),
    KEY ix_date_full (full_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- ИЗМЕРЕНИЕ: КЛИЕНТ
-- customer_key = -1  зарезервирован под покупки без идентификатора («гость»).
-- ---------------------------------------------------------------------------
CREATE TABLE dim_customer (
    customer_key      INT          NOT NULL PRIMARY KEY,
    customer_id       INT          NULL,
    is_guest          TINYINT      NOT NULL DEFAULT 0,
    country           VARCHAR(128) NOT NULL DEFAULT 'Unknown',
    first_order_date  DATE         NULL,
    last_order_date   DATE         NULL,
    orders_count      INT          NOT NULL DEFAULT 0,
    KEY ix_cust_id (customer_id),
    KEY ix_cust_country (country)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- ИЗМЕРЕНИЕ: ТОВАР
-- ---------------------------------------------------------------------------
CREATE TABLE dim_product (
    product_key   INT           NOT NULL PRIMARY KEY,
    stock_code    VARCHAR(32)   NOT NULL,
    description   VARCHAR(512)  NOT NULL DEFAULT '',
    category      VARCHAR(64)   NOT NULL DEFAULT 'OTHER',
    is_service    TINYINT       NOT NULL DEFAULT 0,     -- POST, MANUAL, BANK CHARGES...
    UNIQUE KEY uq_product_code (stock_code),
    KEY ix_product_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- ИЗМЕРЕНИЕ: СТРАНА
-- ---------------------------------------------------------------------------
CREATE TABLE dim_country (
    country_key   INT           NOT NULL PRIMARY KEY,
    country_name  VARCHAR(128)  NOT NULL,
    region        VARCHAR(32)   NOT NULL DEFAULT 'Other',
    UNIQUE KEY uq_country_name (country_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- ФАКТ: ПРОДАЖИ (гранулярность — товарная позиция в счёте)
-- ---------------------------------------------------------------------------
CREATE TABLE fact_sales (
    sales_key     BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
    date_key      INT           NOT NULL,
    customer_key  INT           NOT NULL,
    product_key   INT           NOT NULL,
    country_key   INT           NOT NULL,
    invoice_no    VARCHAR(32)   NOT NULL,
    invoice_ts    DATETIME      NOT NULL,
    quantity      INT           NOT NULL,
    unit_price    DECIMAL(10,2) NOT NULL,
    gross_amount  DECIMAL(12,2) NOT NULL,
    is_return     TINYINT       NOT NULL DEFAULT 0,
    KEY ix_fact_date (date_key),
    KEY ix_fact_customer (customer_key),
    KEY ix_fact_product (product_key),
    KEY ix_fact_country (country_key),
    KEY ix_fact_invoice (invoice_no),
    CONSTRAINT fk_fact_date     FOREIGN KEY (date_key)     REFERENCES dim_date(date_key),
    CONSTRAINT fk_fact_customer FOREIGN KEY (customer_key) REFERENCES dim_customer(customer_key),
    CONSTRAINT fk_fact_product  FOREIGN KEY (product_key)  REFERENCES dim_product(product_key),
    CONSTRAINT fk_fact_country  FOREIGN KEY (country_key)  REFERENCES dim_country(country_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
