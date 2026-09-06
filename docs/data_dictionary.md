# Словарь данных хранилища `retail_dwh`

## Слой staging

### `stg_online_retail`
Сырые строки источника «как есть», содержательные поля — текстовые.

| Поле | Тип | Описание |
|---|---|---|
| `invoice` | VARCHAR(32) | номер счёта; префикс `C` — возврат |
| `stock_code` | VARCHAR(32) | артикул товара |
| `description` | VARCHAR(512) | наименование |
| `quantity` | VARCHAR(32) | количество (текст) |
| `invoice_date` | VARCHAR(32) | дата-время операции (текст) |
| `price` | VARCHAR(32) | цена за единицу (текст) |
| `customer_id` | VARCHAR(32) | идентификатор клиента (может быть пустым) |
| `country` | VARCHAR(128) | страна клиента |
| `_source_sheet` | VARCHAR(32) | лист Excel-источника |
| `_loaded_at` | DATETIME | момент загрузки |
| `_row_hash` | CHAR(40) | SHA-1 значимых полей (дедуп, идемпотентность) |

## Многомерная модель («звезда»)

### Измерение `dim_date`
| Поле | Тип | Описание |
|---|---|---|
| `date_key` | INT PK | ключ вида `YYYYMMDD` |
| `full_date` | DATE | календарная дата |
| `year`, `quarter`, `month` | числовые | год / квартал / месяц |
| `month_name` | VARCHAR | название месяца (рус.) |
| `year_month` | CHAR(7) | `YYYY-MM` |
| `week_iso` | TINYINT | номер недели ISO |
| `day_of_month` | TINYINT | день месяца |
| `day_of_week` | TINYINT | 1 = понедельник … 7 = воскресенье |
| `day_name` | VARCHAR | название дня недели (рус.) |
| `is_weekend` | TINYINT | 1, если суббота/воскресенье |

### Измерение `dim_customer`
| Поле | Тип | Описание |
|---|---|---|
| `customer_key` | INT PK | суррогатный ключ; `-1` — покупки без идентификатора («гость») |
| `customer_id` | INT NULL | натуральный идентификатор клиента |
| `is_guest` | TINYINT | 1 для строки `-1` |
| `country` | VARCHAR | страна последнего заказа клиента |
| `first_order_date` | DATE | дата первой покупки |
| `last_order_date` | DATE | дата последней покупки |
| `orders_count` | INT | число уникальных счетов |

### Измерение `dim_product`
| Поле | Тип | Описание |
|---|---|---|
| `product_key` | INT PK | суррогатный ключ |
| `stock_code` | VARCHAR UNIQUE | артикул |
| `description` | VARCHAR | эталонное (самое частое) наименование |
| `category` | VARCHAR | укрупнённая категория (эвристика по наименованию) |
| `is_service` | TINYINT | 1 — служебный код (POST, MANUAL, BANK CHARGES …) |

### Измерение `dim_country`
| Поле | Тип | Описание |
|---|---|---|
| `country_key` | INT PK | суррогатный ключ |
| `country_name` | VARCHAR UNIQUE | нормализованное название страны |
| `region` | VARCHAR | `UK` / `Europe` / `World` / `Other` |

### Факт `fact_sales`
Гранулярность — товарная позиция в счёте.

| Поле | Тип | Описание |
|---|---|---|
| `sales_key` | BIGINT PK | суррогатный ключ строки |
| `date_key` | INT FK → `dim_date` | дата операции |
| `customer_key` | INT FK → `dim_customer` | клиент (`-1` — гость) |
| `product_key` | INT FK → `dim_product` | товар |
| `country_key` | INT FK → `dim_country` | страна |
| `invoice_no` | VARCHAR(32) | номер счёта |
| `invoice_ts` | DATETIME | дата-время операции |
| `quantity` | INT | количество (для возвратов — отрицательное) |
| `unit_price` | DECIMAL(10,2) | цена за единицу, GBP |
| `gross_amount` | DECIMAL(12,2) | `quantity * unit_price` |
| `is_return` | TINYINT | 1, если счёт-возврат |

## Витрины (VIEW)

| Витрина | Ключевые поля | Назначение |
|---|---|---|
| `v_revenue_monthly` | `year_month`, `gross_revenue`, `returns_amount`, `net_revenue`, `orders`, `customers`, `units`, `avg_order_value` | помесячная динамика |
| `v_top_products` | `stock_code`, `description`, `category`, `revenue`, `units`, `invoices` | рейтинг товаров (без служебных) |
| `v_sales_by_country` | `country_name`, `region`, `revenue`, `orders`, `customers` | география продаж |
| `v_customer_rfm` | `customer_id`, `recency_days`, `frequency`, `monetary` | база для RFM |
| `v_returns_monthly` | `year_month`, `returns_amount`, `gross_revenue`, `returns_rate` | динамика возвратов |
| `v_cohort_retention` | `cohort_month`, `month_index`, `active_customers` | когортное удержание |

## Правила очистки (ETL шаг 2 / `database/03_load_data.sql`)

- удаляются полные дубликаты строк;
- отбрасываются строки с непарсируемыми `quantity` / `price` / `invoice_date`;
- продажа: не возврат, `quantity > 0`, `price > 0`;
- возврат: `invoice` начинается с `C`, `quantity < 0`, `price > 0`;
- прочие комбинации (корректировки, `price <= 0`) отбрасываются;
- страны нормализуются: `EIRE→Ireland`, `USA→United States`, `RSA→South Africa`,
  пустая / `Unspecified` → `Unknown`;
- строки без `customer_id` сохраняются и относятся к клиенту `-1` («гость»).
