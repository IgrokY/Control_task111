"""Полный прогон проекта edu_pipeline от чистого состояния.

Скрипт по очереди запускает этапы, проверяет тесты и контрольные суммы
исходных файлов. Ноутбук report_enrollments.ipynb запускается отдельно
в Jupyter (Run All) — его вывод уже сохранён в файле.

Запуск:  python run_all.py
"""

import hashlib
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "final"

STEPS = [
    ("Этап 3. Нормализация журнала", "normalize_audit.py"),
    ("Этап 2. Очередь проверки заявок", "review_queue.py"),
    ("Этап 4. Схема базы данных и справочники", "create_db.py"),
    ("Этап 5. ETL: CSV -> SQLite", "etl_import.py"),
    ("Этап 4. Параметризованные запросы и агрегаты", "queries.py"),
    ("Этап 4. Транзакции и протокол commit/rollback", "batch_load.py"),
    ("Этап 5. Экспорт JSON/XML и внешние ответы", "export_data.py"),
    ("Этап 6. Класс заявки с историей", "demo.py"),
    ("Этап 7. Замеры timeit", "performance_bench.py"),
    ("Этап 7. Диагностика кодировок", "unicode_diagnostics.py"),
]


def snapshot(directory: Path) -> dict[str, str]:
    """Считает SHA-256 всех файлов папки, чтобы доказать их неизменность."""
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            result[str(path.relative_to(directory))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return result


def run(command: list[str], title: str) -> None:
    """Запускает команду в папке проекта и останавливает прогон при ошибке."""
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)
    completed = subprocess.run(command, cwd=BASE_DIR)
    if completed.returncode != 0:
        raise SystemExit(f"Шаг завершился с кодом {completed.returncode}: {title}")


def main() -> None:
    """Выполняет все шаги, тесты и проверку исходных файлов."""
    before = snapshot(DATA_DIR)

    for title, script in STEPS:
        run([sys.executable, "-X", "utf8", script], title)

    run([sys.executable, "-X", "utf8", "-m", "unittest", "discover", "-v"],
        "Этап 7. Модульные тесты unittest")

    after = snapshot(DATA_DIR)

    print("\n" + "=" * 70)
    print("Проверка исходных данных")
    print("=" * 70)
    print(f"Файлов в data/final: {len(before)}")
    if before == after:
        print("Контрольные суммы совпали: исходные файлы не изменены.")
    else:
        changed = sorted(
            name for name in before.keys() | after.keys()
            if before.get(name) != after.get(name)
        )
        raise SystemExit(f"Исходные файлы изменились: {changed}")

    print("\nЭтапы 1–7 выполнены. Ноутбук: откройте report_enrollments.ipynb"
          " и выполните Run All.")


if __name__ == "__main__":
    main()
