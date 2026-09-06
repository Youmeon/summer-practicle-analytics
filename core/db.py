"""Фабрика подключений к СУБД и вспомогательные операции с ней."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import Engine, create_engine, text

from core.config import DB
from core.logs import get_logger

log = get_logger("core.db")


def get_engine(*, with_db: bool = True, echo: bool = False) -> Engine:
    """Создать SQLAlchemy Engine.

    with_db=False — подключение без выбора базы (для CREATE DATABASE и т.п.).
    """
    url = DB.url if with_db else DB.url_no_db
    return create_engine(url, echo=echo, pool_pre_ping=True, future=True)


def ping() -> bool:
    """Проверка доступности БД."""
    try:
        eng = get_engine()
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 — сознательно показываем причину
        log.error("Нет подключения к БД (%s): %s", DB.url.split("@")[-1], exc)
        return False


def run_sql_script(path: str | Path, *, with_db: bool = True,
                   stop_at: str | None = None) -> None:
    """Выполнить .sql-файл, разбивая его по ';' на верхнем уровне.

    Достаточно для наших DDL-скриптов (без хранимых процедур и DELIMITER).
    stop_at — если задан, обработка файла прекращается на первой строке,
    содержащей эту подстроку (используется, чтобы не выполнять справочные
    запросы в конце 04_analytics_queries.sql).
    """
    path = Path(path)
    sql = path.read_text(encoding="utf-8")
    if stop_at:
        sql = sql.split(stop_at)[0]
    statements = _split_statements(sql)
    eng = get_engine(with_db=with_db)
    # Работаем через «сырой» курсор DBAPI и execute(stmt) без аргументов: иначе
    # PyMySQL прогоняет текст через `query % args` и падает на литеральных '%'
    # (DATE_FORMAT(..., '%Y-%m-01')), а SQLAlchemy — на ':i'/':s' как на bind-параметрах.
    raw = eng.raw_connection()
    try:
        cur = raw.cursor()
        for stmt in statements:
            cur.execute(stmt)
        cur.close()
        raw.commit()
    finally:
        raw.close()
    log.info("Выполнен скрипт %s (%d операторов)", path.name, len(statements))


def _split_statements(sql: str) -> list[str]:
    out: list[str] = []
    buf: list[str] = []
    in_line_comment = False
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or not stripped:
            continue
        buf.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(buf).rstrip().rstrip(";").strip()
            if statement:
                out.append(statement)
            buf = []
    tail = "\n".join(buf).strip().rstrip(";").strip()
    if tail:
        out.append(tail)
    return out


def read_sql(query: str, params: dict | None = None) -> pd.DataFrame:
    """Прочитать результат запроса в DataFrame.

    Без params запрос уходит в драйвер как есть (последовательности ':i'/':s'
    в DATE_FORMAT не трактуются как bind-параметры). С params используется
    именованная подстановка SQLAlchemy.
    """
    eng = get_engine()
    if params:
        with eng.connect() as conn:
            result = conn.execute(text(query), params)
            return pd.DataFrame(result.fetchall(), columns=list(result.keys()))
    # без параметров — «сырой» курсор, чтобы литеральные '%' в SQL не ломали PyMySQL
    raw = eng.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute(query)
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()
        cur.close()
    finally:
        raw.close()
    df = pd.DataFrame(rows, columns=cols)
    # DECIMAL приходит как Decimal (object) — приводим числовые столбцы к float
    for col in df.columns:
        if df[col].dtype == object:
            conv = pd.to_numeric(df[col], errors="coerce")
            if df[col].notna().any() and conv.notna().sum() == df[col].notna().sum():
                df[col] = conv
    return df


def write_dataframe(
    df: pd.DataFrame,
    table: str,
    *,
    if_exists: str = "append",
    chunksize: int = 20_000,
) -> int:
    """Записать DataFrame в таблицу. Возвращает число строк."""
    eng = get_engine()
    with eng.begin() as conn:
        df.to_sql(
            table,
            conn,
            if_exists=if_exists,
            index=False,
            chunksize=chunksize,
            method="multi",
        )
    log.info("В таблицу %s записано %d строк", table, len(df))
    return len(df)


def truncate(*tables: str) -> None:
    """Очистить таблицы, временно отключив проверку внешних ключей."""
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for tbl in tables:
            conn.execute(text(f"TRUNCATE TABLE `{tbl}`"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    log.info("Очищены таблицы: %s", ", ".join(tables))
