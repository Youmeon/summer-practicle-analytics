"""Оркестратор ETL-конвейера: последовательный запуск шагов 01 → 02 → 03.

Запуск:  python etl/run_pipeline.py
"""
from __future__ import annotations

import runpy
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.logs import get_logger

log = get_logger("etl.pipeline")

STEPS = ["01_extract.py", "02_transform.py", "03_load.py"]


def main() -> None:
    here = Path(__file__).resolve().parent
    t0 = time.perf_counter()
    for step in STEPS:
        log.info("========== %s ==========", step)
        s = time.perf_counter()
        runpy.run_path(str(here / step), run_name="__main__")
        log.info("---------- %s завершён за %.1f c ----------", step, time.perf_counter() - s)
    log.info("Конвейер выполнен за %.1f c", time.perf_counter() - t0)


if __name__ == "__main__":
    main()
