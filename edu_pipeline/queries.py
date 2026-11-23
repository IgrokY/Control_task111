"""Этап 4. Параметризованные выборки и агрегаты по базе edu.db.

Модуль показывает три обязательных приёма работы с DB-API 2.0:

* фильтры по статусу, курсу, формату и длительности собираются из условий,
  а все значения передаются отдельно параметрами (никакой конкатенации);
* результат можно получить двумя способами: список кортежей (fetch_rows)
  и список словарей (fetch_dicts);
* агрегаты считает сам SQLite, а не Python: так меньше кода и одна точка
  ответственности за расчёты.

Запуск:  python queries.py   (после create_db.py и etl_import.py)
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "edu.db"

PAID_STATUSES = ("enrolled", "completed")

# Контрольные числа для базы, загруженной из data/final/.
EXPECTED_ENROLLMENTS = 10
EXPECTED_REVENUE = 332_000
EXPECTED_AVG_DURATION = 42.0

BASE_SQL = """
    SELECT e.enrollment_id,
           s.full_name       AS student,
           e.student_email,
           c.title           AS course,
           e.course_code,
           e.status,
           e.created_date,
           e.duration_hours,
           e.format
    FROM enrollments e
    JOIN students s ON s.student_email = e.student_email
    JOIN courses  c ON c.course_code   = e.course_code
"""

AVG_DURATION_SQL = """
    SELECT c.course_code,
           c.title,
           COUNT(*)                      AS enrollments,
           ROUND(AVG(e.duration_hours), 1) AS avg_hours
    FROM enrollments e
    JOIN courses c ON c.course_code = e.course_code
    GROUP BY c.course_code, c.title
    ORDER BY avg_hours DESC, c.course_code
"""

REVENUE_SQL = """
    SELECT c.course_code,
           c.title,
           c.price_rub,
           COUNT(*)                AS paid_enrollments,
           SUM(c.price_rub)        AS revenue_rub
    FROM enrollments e
    JOIN courses c ON c.course_code = e.course_code
    WHERE e.status IN (?, ?)
    GROUP BY c.course_code, c.title, c.price_rub
    ORDER BY revenue_rub DESC, c.course_code
"""

STATUS_SQL = """
    SELECT status, COUNT(*) AS enrollments
    FROM enrollments
    GROUP BY status
    ORDER BY enrollments DESC, status
"""

FORMAT_SQL = """
    SELECT format, COUNT(*) AS enrollments
    FROM enrollments
    GROUP BY format
    ORDER BY enrollments DESC, format
"""


def build_enrollments_query(
    status: str | None = None,
    course_code: str | None = None,
    study_format: str | None = None,
    min_duration: float | None = None,
) -> tuple[str, tuple]:
    """Собирает SELECT с фильтрами; все значения остаются параметрами.

    Условия склеиваются только из фиксированных фрагментов кода, поэтому
    пользовательское значение не может попасть в текст SQL-запроса.
    """
    conditions: list[str] = []
    params: list = []

    if status is not None:
        conditions.append("e.status = ?")
        params.append(status)
    if course_code is not None:
        conditions.append("e.course_code = ?")
        params.append(course_code)
    if study_format is not None:
        conditions.append("e.format = ?")
        params.append(study_format)
    if min_duration is not None:
        conditions.append("e.duration_hours >= ?")
        params.append(float(min_duration))

    sql = BASE_SQL
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY e.created_date, e.enrollment_id"
    return sql, tuple(params)


def fetch_rows(connection: sqlite3.Connection, sql: str, params: tuple = ()) -> list[tuple]:
    """Возвращает результат запроса списком кортежей (первый способ)."""
    return connection.execute(sql, params).fetchall()


def fetch_dicts(connection: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    """Возвращает результат запроса списком словарей (второй способ).

    Имена колонок берутся из cursor.description, поэтому запрос можно менять
    без правки кода разбора результата.
    """
    cursor = connection.execute(sql, params)
    names = [description[0] for description in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def open_database(path: Path = DB_PATH) -> sqlite3.Connection:
    """Открывает edu.db и подсказывает порядок запуска, если файла ещё нет."""
    if not path.exists():
        raise FileNotFoundError(
            f"Нет файла {path.name}. Сначала выполните create_db.py и etl_import.py"
        )
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def print_rows(title: str, rows: list[tuple]) -> None:
    """Печатает кортежи без форматирования — так видно «сырой» результат."""
    print(title)
    for row in rows:
        print(" ", row)


def main() -> None:
    """Выполняет контрольные выборки и сверяет агрегаты с эталоном."""
    connection = open_database()
    try:
        total = connection.execute("SELECT COUNT(*) FROM enrollments").fetchone()[0]
        print(f"1. Всего заявок в базе: {total}")

        print("\n2. Фильтр status=enrolled (список кортежей):")
        sql, params = build_enrollments_query(status="enrolled")
        print_rows("", fetch_rows(connection, sql, params))

        print("\n3. Фильтр course_code=PY-100, format=online (словари):")
        sql, params = build_enrollments_query(
            course_code="PY-100", study_format="online"
        )
        for row in fetch_dicts(connection, sql, params):
            print(f"  {row['enrollment_id']}  {row['student']:<32}"
                  f"{row['status']:<10}{row['duration_hours']:>5} ч")

        print("\n4. Заявки длительностью не менее 48 часов:")
        sql, params = build_enrollments_query(min_duration=48)
        for row in fetch_dicts(connection, sql, params):
            print(f"  {row['enrollment_id']}  {row['course_code']}  {row['duration_hours']} ч")

        print("\n5. Средняя длительность по курсам:")
        for row in fetch_dicts(connection, AVG_DURATION_SQL):
            print(f"  {row['course_code']:<8}{row['title']:<22}"
                  f"заявок {row['enrollments']:>2}   среднее {row['avg_hours']:>5} ч")

        print("\n6. Выручка по курсам (статусы enrolled и completed):")
        revenue_total = 0
        for row in fetch_dicts(connection, REVENUE_SQL, PAID_STATUSES):
            revenue_total += row["revenue_rub"]
            print(f"  {row['course_code']:<8}{row['revenue_rub']:>9} руб."
                  f"   оплачено заявок: {row['paid_enrollments']}")
        print(f"  Итого выручка: {revenue_total} руб.")

        print("\n7. Количество заявок по статусам:")
        for row in fetch_dicts(connection, STATUS_SQL):
            print(f"  {row['status']:<12}{row['enrollments']}")

        print("\n8. Количество заявок по формату обучения:")
        for row in fetch_dicts(connection, FORMAT_SQL):
            print(f"  {row['format']:<10}{row['enrollments']}")

        avg_duration = connection.execute(
            "SELECT ROUND(AVG(duration_hours), 1) FROM enrollments"
        ).fetchone()[0]

        print("\nКонтроль:")
        print(f"  заявок:    {total} (ожидалось {EXPECTED_ENROLLMENTS})")
        print(f"  среднее:   {avg_duration} ч (ожидалось {EXPECTED_AVG_DURATION})")
        print(f"  выручка:   {revenue_total} руб. (ожидалось {EXPECTED_REVENUE})")

        assert total == EXPECTED_ENROLLMENTS, "Количество заявок не совпало"
        assert avg_duration == EXPECTED_AVG_DURATION, "Средняя длительность не совпала"
        assert revenue_total == EXPECTED_REVENUE, "Выручка не совпала"
        print("  Все контрольные числа совпали.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
