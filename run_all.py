"""Одна команда: прогнать весь проект и показать результат.

    .venv/bin/python run_all.py              # ETL при необходимости + аналитика + отчёт
    .venv/bin/python run_all.py --reload     # принудительно пересобрать хранилище
    .venv/bin/python run_all.py --dashboard  # то же + запустить Streamlit-дашборд

Шаги:
  0. проверка .env (создаётся из .env.example при отсутствии);
  1. ETL-конвейер etl/run_pipeline.py — пропускается, если fact_sales уже заполнена
     (снять пропуск: --reload);
  2. analytics/01_kpi_analysis.py, 02_sales_analysis.py, 03_visualization.py;
  3. печать пути к reports/report.html и попытка открыть его в браузере;
  4. (--dashboard) streamlit run dashboard/app.py.
"""
from __future__ import annotations

import runpy
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core.config import REPORTS_DIR  # noqa: E402
from core.logs import get_logger  # noqa: E402

log = get_logger("run_all")


def ensure_env() -> None:
    env, example = ROOT / ".env", ROOT / ".env.example"
    if not env.exists() and example.exists():
        env.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        log.info(".env создан из .env.example")


def warehouse_ready() -> bool:
    try:
        from core.db import ping, read_sql
        if not ping():
            return False
        n = int(read_sql("SELECT COUNT(*) AS n FROM fact_sales").iloc[0]["n"])
        return n > 0
    except Exception:
        return False


def open_in_browser(path: Path) -> bool:
    """Открыть локальный html в браузере, включая сценарий WSL → Windows."""
    p = str(path)
    if shutil.which("wslview"):                       # wslu: открывает браузер Windows
        subprocess.Popen(["wslview", p],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    if shutil.which("explorer.exe"):                  # WSL без wslu
        try:
            win = subprocess.check_output(["wslpath", "-w", p], text=True).strip()
            subprocess.Popen(["explorer.exe", win],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            pass
    if shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", p],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    try:
        return webbrowser.open(path.as_uri())
    except Exception:
        return False


def run_script(rel: str) -> None:
    log.info("── %s", rel)
    t = time.perf_counter()
    runpy.run_path(str(ROOT / rel), run_name="__main__")
    log.info("   готово за %.1f c", time.perf_counter() - t)


def main() -> None:
    args = set(sys.argv[1:])
    ensure_env()

    if "--reload" in args or not warehouse_ready():
        run_script("etl/run_pipeline.py")
    else:
        log.info("Хранилище уже заполнено — ETL пропущен (--reload чтобы пересобрать)")

    for step in ("analytics/01_kpi_analysis.py",
                 "analytics/02_sales_analysis.py",
                 "analytics/03_visualization.py",
                 "reports/build_docx_report.py"):
        run_script(step)

    index = REPORTS_DIR / "index.html"
    report = REPORTS_DIR / "report.html"
    log.info("═" * 60)
    log.info("РЕЗУЛЬТАТЫ:   %s", index)
    log.info("ОТЧЁТ HTML:   %s", report)
    log.info("ОТЧЁТ WORD:   %s", REPORTS_DIR / "Отчет_по_практике.docx")
    log.info("ГРАФИКИ:      %s/*.png|html", REPORTS_DIR / "figures")
    log.info("ТАБЛИЦЫ:      %s/*.csv", REPORTS_DIR / "tables")
    log.info("═" * 60)
    target = index if index.exists() else report
    if open_in_browser(target):
        log.info("Открываю в браузере: %s", target.name)
    else:
        log.info("Открой вручную: %s", target)

    if "--dashboard" in args:
        log.info("Запускаю дашборд: http://localhost:8501  (Ctrl+C для остановки)")
        subprocess.run([sys.executable, "-m", "streamlit", "run",
                        str(ROOT / "dashboard" / "app.py")], check=False)


if __name__ == "__main__":
    main()
