-- =============================================================================
--  01_create_database.sql
--  Первичная инициализация: база данных + пользователь приложения.
--
--  Запускать ОДИН РАЗ под административной учётной записью, например:
--      sudo mysql < database/01_create_database.sql
--  (в WSL к локальному MariaDB root подключается через unix-сокет по sudo)
--
--  Значения логина/пароля должны совпадать с .env (DB_USER / DB_PASSWORD).
-- =============================================================================

CREATE DATABASE IF NOT EXISTS retail_dwh
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

-- Пользователь приложения. Пароль — учебный; в .gitignore лежит .env, не этот файл,
-- поэтому для реального стенда пароль здесь и в .env нужно поменять.
CREATE USER IF NOT EXISTS 'retail_app'@'localhost'  IDENTIFIED BY 'retail_app_pwd';
CREATE USER IF NOT EXISTS 'retail_app'@'127.0.0.1'  IDENTIFIED BY 'retail_app_pwd';
CREATE USER IF NOT EXISTS 'retail_app'@'%'          IDENTIFIED BY 'retail_app_pwd';

GRANT ALL PRIVILEGES ON retail_dwh.* TO 'retail_app'@'localhost';
GRANT ALL PRIVILEGES ON retail_dwh.* TO 'retail_app'@'127.0.0.1';
GRANT ALL PRIVILEGES ON retail_dwh.* TO 'retail_app'@'%';

FLUSH PRIVILEGES;

SELECT 'retail_dwh + retail_app готовы' AS status;
