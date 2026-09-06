"""Общие помощники аналитического слоя."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.config import TABLES_DIR
from core.logs import get_logger

log = get_logger("analytics")


def save_table(df: pd.DataFrame, name: str) -> Path:
    """Сохранить таблицу в reports/tables/<name>.csv."""
    path = TABLES_DIR / f"{name}.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    log.info("таблица → %s (%d строк)", path.name, len(df))
    return path


def fmt_gbp(value: float) -> str:
    return f"£{value:,.0f}"


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"
