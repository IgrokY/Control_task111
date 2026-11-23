"""Этап 4. Схема базы данных edu.db и загрузка справочников.

Скрипт создаёт файл edu.db заново: таблицы students, courses и enrollments,
индексы и контроль внешних ключей. Справочники студентов и курсов
заполняются сразу, а заявки загружает ETL-конвейер Этапа 5 (etl_import.py).
Такое разделение не дублирует данные и позволяет доказать защиту от дублей.

Запуск:  python create_db.py
"""

import csv
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "final"
DB_PATH = BASE_DIR / "edu.db"

STUDENTS_CSV = DATA_DIR / "students.csv"
COURSES_CSV = DATA_DIR / "courses.csv"

# Контрольные числа взяты из справочников data/final/.
EXPECTED_STUDENTS = 16
EXPECTED_COURSES = 5

SCHEMA_SQL = """
    PRAGMA foreign_keys = ON;

    CREATE TABLE students(
        student_email   TEXT PRIMARY KEY,
        full_name       TEXT NOT NULL,
        phone           TEXT NOT NULL,
        registered_date TEXT NOT NULL
    );

    CREATE TABLE courses(
        course_code    TEXT PRIMARY KEY,
        title          TEXT NOT NULL UNIQUE,
        price_rub      INTEGER NOT NULL CHECK (price_rub >= 0),
        default_format TEXT NOT NULL CHECK (default_format IN ('online', 'offline'))
    );

    CREATE TABLE enrollments(
        enrollment_id  TEXT PRIMARY KEY,
        student_email  TEXT NOT NULL,
        course_code    TEXT NOT NULL,
        status         TEXT NOT NULL,
        created_date   TEXT NOT NULL,
        duration_hours REAL NOT NULL CHECK (duration_hours > 0),
        format         TEXT NOT NULL CHECK (format IN ('online', 'offline')),
        loaded_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(student_email) REFERENCES students(student_email),
        FOREIGN KEY(course_code)   REFERENCES courses(course_code)
    );

    CREATE INDEX idx_enrollments_status  ON enrollments(status);
    CREATE INDEX idx_enrollments_course  ON enrollments(course_code);
    CREATE INDEX idx_enrollments_student ON enrollments(student_email);
"""


def read_reference(path: Path) -> list[dict]:
    """Читает справочник CSV в UTF-8 (с BOM) и возвращает список словарей."""
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Открывает соединение и включает контроль внешних ключей."""
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def create_schema(connection: sqlite3.Connection) -> None:
    """Создаёт таблицы и индексы через executescript (один вызов, один сценарий)."""
    connection.executescript(SCHEMA_SQL)


def load_students(connection: sqlite3.Connection) -> set[str]:
    """Заполняет справочник студентов и возвращает множество e-mail."""
    rows = read_reference(STUDENTS_CSV)
    connection.executemany(
        "INSERT INTO students(student_email, full_name, phone, registered_date)"
        " VALUES (?, ?, ?, ?)",
        [
            (row["student_email"], row["full_name"], row["phone"], row["registered_date"])
            for row in rows
        ],
    )
    return {row["student_email"] for row in rows}


def load_courses(connection: sqlite3.Connection) -> set[str]:
    """Заполняет справочник курсов и возвращает множество кодов."""
    rows = read_reference(COURSES_CSV)
    connection.executemany(
        "INSERT INTO courses(course_code, title, price_rub, default_format)"
        " VALUES (?, ?, ?, ?)",
        [
            (row["course_code"], row["title"], int(row["price_rub"]),
             row["default_format"])
            for row in rows
        ],
    )
    return {row["course_code"] for row in rows}


def build_database(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Создаёт базу с нуля: удаляет старый файл, схему, справочники.

    Возвращает открытое соединение; закрывать его должен вызывающий код.
    """
    path = Path(db_path)
    if path.exists():
        path.unlink()
    connection = connect(path)
    create_schema(connection)
    load_students(connection)
    load_courses(connection)
    connection.commit()
    return connection


def ensure_database(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Возвращает соединение с готовой базой; пустую базу создаёт сам.

    Нужна ETL-конвейеру, чтобы он запускался с чистого состояния без
    предварительного ручного вызова create_db.py.
    """
    path = Path(db_path)
    if path.exists():
        return connect(path)
    connection = build_database(path)
    return connection


def count_rows(connection: sqlite3.Connection, table: str) -> int:
    """Возвращает количество строк таблицы (имя таблицы — только из белого списка)."""
    if table not in {"students", "courses", "enrollments"}:
        raise ValueError(f"Неизвестная таблица: {table}")
    return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def main() -> None:
    """Пересоздаёт базу и печатает контрольные числа."""
    connection = build_database()
    try:
        students = count_rows(connection, "students")
        courses = count_rows(connection, "courses")
        enrollments = count_rows(connection, "enrollments")

        print(f"База данных: {DB_PATH.name}")
        print(f"Студентов в справочнике: {students}")
        print(f"Курсов в справочнике:    {courses}")
        print(f"Заявок в базе:           {enrollments}")
        print("Заявки загружает etl_import.py (Этап 5).")

        assert students == EXPECTED_STUDENTS, "Контрольное число студентов не совпало"
        assert courses == EXPECTED_COURSES, "Контрольное число курсов не совпало"
        assert enrollments == 0, "Новая база должна быть без заявок"
        print("Контрольные числа совпали.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
