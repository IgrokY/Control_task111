"""Этап 4. Пакетная загрузка и доказательство атомарности (commit / rollback).

Сценарий повторяет требование бизнеса: пакет из нескольких заявок должен
применяться целиком. Если в середине пакета возникает ошибка, база не должна
остаться частично обновлённой.

Скрипт делает три эксперимента:

1. rollback в базе :memory: — после ошибки в середине пакета строк нет;
2. commit в базе :memory: — успешный пакет сохранён полностью;
3. rollback в рабочей базе edu.db — контроль количества до и после отката.

Каждый эксперимент проверяется assert, а результаты пишутся в transaction_protocol.txt.
Запуск:  python batch_load.py
"""

import sqlite3
from pathlib import Path

import create_db

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = create_db.DB_PATH
PROTOCOL = BASE_DIR / "transaction_protocol.txt"

DEMO_SCHEMA = """
    CREATE TABLE batch_demo(
        item_id INTEGER PRIMARY KEY,
        label   TEXT NOT NULL,
        hours   REAL NOT NULL CHECK (hours > 0)
    );
"""

DEMO_BATCH = [("A", 4.0), ("B", 8.0), ("C", 12.0)]


def setup_demo_table(connection: sqlite3.Connection) -> None:
    """Создаёт тестовую таблицу через executescript (быстрый изолированный тест)."""
    connection.executescript(DEMO_SCHEMA)


def insert_one(connection: sqlite3.Connection, label: str, hours: float) -> None:
    """Вставляет одну запись параметризованным запросом."""
    connection.execute(
        "INSERT INTO batch_demo(label, hours) VALUES (?, ?)",
        (label, float(hours)),
    )


def insert_many(connection: sqlite3.Connection, batch: list[tuple]) -> None:
    """Вставляет пакет через executemany — штатный путь импорта."""
    connection.executemany(
        "INSERT INTO batch_demo(label, hours) VALUES (?, ?)",
        [(label, float(hours)) for label, hours in batch],
    )


def count_demo(connection: sqlite3.Connection) -> int:
    """Количество строк в тестовой таблице."""
    return connection.execute("SELECT COUNT(*) FROM batch_demo").fetchone()[0]


def demo_rollback(connection: sqlite3.Connection) -> dict:
    """Пакет с ошибкой в середине: ожидаем IntegrityError и пустую таблицу.

    Доказательство в два шага: перед откатом строки пакета ДОЛЖНЫ быть видны
    внутри транзакции (иначе проверка «после отката 0» ничего не доказывает),
    а после rollback их не должно остаться.
    """
    rows_inside = 0
    try:
        connection.execute("BEGIN")
        insert_many(connection, DEMO_BATCH)
        # Нарушение NOT NULL в середине пакета — имитация «плохой» строки.
        connection.execute(
            "INSERT INTO batch_demo(label, hours) VALUES (?, ?)",
            (None, 1.0),
        )
        connection.commit()
        error = "ошибки не было"
    except sqlite3.IntegrityError as exc:
        rows_inside = count_demo(connection)  # до отката: вставленное ещё видно
        connection.rollback()
        error = str(exc)

    rows = count_demo(connection)
    assert rows_inside == len(DEMO_BATCH), "Внутри транзакции не было вставленных строк"
    assert rows == 0, f"После rollback осталось {rows} строк"
    return {"stage": "rollback", "error": error,
            "rows_inside": rows_inside, "rows_after": rows}


def demo_commit(connection: sqlite3.Connection) -> dict:
    """Успешный пакет: одна вставка + executemany, затем commit."""
    try:
        connection.execute("BEGIN")
        insert_one(connection, *DEMO_BATCH[0])
        insert_many(connection, DEMO_BATCH[1:])
        connection.commit()
        error = "нет"
    except sqlite3.Error:
        connection.rollback()
        raise

    rows = count_demo(connection)
    assert rows == len(DEMO_BATCH), "Пакет сохранён не полностью"
    return {"stage": "commit", "error": error, "rows_after": rows}


def demo_real_db_rollback(db_path: Path = DB_PATH) -> dict:
    """Откатывает вставку в рабочей базе и доказывает, что число строк не изменилось."""
    if not db_path.exists():
        return {"stage": "edu.db rollback", "error": "база не создана", "rows_after": 0}

    connection = create_db.connect(db_path)
    try:
        before = connection.execute("SELECT COUNT(*) FROM enrollments").fetchone()[0]
        reference = connection.execute(
            "SELECT student_email, course_code FROM enrollments LIMIT 1"
        ).fetchone()
        if reference is None:
            return {"stage": "edu.db rollback", "error": "нет заявок для опыта",
                    "rows_after": before}

        student_email, course_code = reference
        try:
            connection.execute("BEGIN")
            connection.execute(
                "INSERT INTO enrollments(enrollment_id, student_email, course_code,"
                " status, created_date, duration_hours, format)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("EDU-209901-9999", student_email, course_code,
                 "new", "2099-01-01", 1.0, "online"),
            )
            rows_inside = connection.execute(
                "SELECT COUNT(*) FROM enrollments"
            ).fetchone()[0]
            connection.rollback()  # намеренный откат
            error = "вставка отменена вручную"
        except sqlite3.Error as exc:
            rows_inside = before
            connection.rollback()
            error = str(exc)

        after = connection.execute("SELECT COUNT(*) FROM enrollments").fetchone()[0]
        assert rows_inside == before + 1, "Внутри транзакции вставка не была видна"
        assert before == after, "После rollback количество заявок изменилось"
        return {"stage": "edu.db rollback", "error": error, "rows_after": after,
                "rows_before": before, "rows_inside": rows_inside}
    finally:
        connection.close()


def write_protocol(results: list[dict], path: Path = PROTOCOL) -> None:
    """Оформляет короткий протокол эксперимента в текстовый файл."""
    lines = ["ПРОТОКОЛ ТРАНЗАКЦИЙ", "=" * 60]
    lines.append("СУБД: SQLite (модуль sqlite3, DB-API 2.0)")
    lines.append("Изоляция: явные BEGIN / COMMIT / ROLLBACK")
    lines.append("")
    for index, result in enumerate(results, start=1):
        lines.append(f"{index}. {result['stage']}")
        if "rows_before" in result:
            lines.append(f"   строк до опыта:   {result['rows_before']}")
        if "rows_inside" in result:
            lines.append(f"   внутри транзакции перед откатом: {result['rows_inside']}")
        lines.append(f"   сообщение:        {result['error']}")
        lines.append(f"   строк после:      {result['rows_after']}")
        lines.append("")
    lines.append("Вывод: при ошибке в середине пакета rollback возвращает базу")
    lines.append("к исходному состоянию; после commit сохраняется весь пакет.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main() -> None:
    """Проводит эксперименты на :memory: и на рабочей базе, пишет протокол."""
    memory = sqlite3.connect(":memory:")
    try:
        setup_demo_table(memory)
        results = [demo_rollback(memory), demo_commit(memory)]
    finally:
        memory.close()

    results.append(demo_real_db_rollback())
    write_protocol(results)
    print(f"\nПротокол сохранён: {PROTOCOL.name}")


if __name__ == "__main__":
    main()
