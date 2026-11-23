"""Этап 7. Исправленный модуль отчётности по заявкам.

Исходный buggy_report.py из data/final/ не изменялся. Здесь лежит версия
с исправленными дефектами; каждый дефект разобран в incident_report.md и
закрыт регрессионным тестом в test_report.py.

Отличия от исходного модуля:

1. load_enrollments() закрывает соединение даже при ошибке (try/finally);
2. average_duration() не падает на NULL и на пустом наборе;
3. top_courses() сортирует по убыванию, а не по возрастанию;
4. find_by_status() не сортирует список вызывающего кода;
5. report_line() приводит значения к строке и не падает на числах и None.
"""

import sqlite3
from pathlib import Path


def load_enrollments(db_path: str | Path) -> list[tuple]:
    """Возвращает список кортежей (enrollment_id, status, duration_hours).

    Соединение закрывается в finally: утечка соединения при исключении
    была одним из дефектов исходного модуля.
    """
    connection = sqlite3.connect(db_path)
    try:
        return connection.execute(
            "SELECT enrollment_id, status, duration_hours FROM enrollments"
        ).fetchall()
    finally:
        connection.close()


def average_duration(rows: list[tuple]) -> float:
    """Средняя длительность по записям, у которых часы заданы числом.

    NULL (None) в базе — нормальная ситуация для незаполненной заявки,
    поэтому такие строки пропускаются. Пустой набор даёт 0.0, а не деление
    на ноль. Отрицательные значения не встречаются в валидных данных, но
    если появятся — они тоже не должны ломать отчёт, поэтому берём только
    неотрицательные числа.
    """
    hours = []
    for _, _, value in rows:
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number >= 0:
            hours.append(number)
    return sum(hours) / len(hours) if hours else 0.0


def top_courses(rows: list[tuple], limit: int = 3) -> list[tuple]:
    """Топ курсов по числу заявок (по убыванию).

    rows — строки, где row[0] — код курса. При равенстве количества
    порядок определяется кодом курса, чтобы результат был воспроизводимым.
    """
    counts: dict[str, int] = {}
    for row in rows:
        counts[row[0]] = counts.get(row[0], 0) + 1
    ordered = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    return ordered[:limit]


def find_by_status(rows: list[tuple], status: str) -> list[tuple]:
    """Все заявки с заданным статусом.

    Исходный список не изменяется: сортировка «на месте» была дефектом,
    потому что вызывающий код терял свой порядок строк.
    """
    return [row for row in rows if row[1] == status]


def report_line(enrollment_id, status) -> str:
    """Строка отчёта. Значения приходят из внешнего файла и могут быть любыми.

    f-string вызывает str() сам, поэтому число или None не приводят к TypeError.
    """
    return f"Заявка {enrollment_id} в статусе {status}"
