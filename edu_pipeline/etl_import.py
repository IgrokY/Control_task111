"""Этап 5. ETL-конвейер CSV -> SQLite для заявок на обучение.

Конвейер разделён на три шага:

* Extract   — read_source() читает «сырой» CSV и замечает строки с лишними полями;
* Validate  — validate_source() проверяет все поля сразу через validators.py,
              отсекает дубликаты и возвращает принятые и отклонённые строки;
* Load      — load_accepted() вставляет строки параметризованно и защищает
              базу от дублей через INSERT OR IGNORE.

Ошибочные строки не теряются: они попадают в rejected_enrollments.csv вместе
с номером строки и понятной причиной. Контрольные числа пишутся в etl_report.txt.
Повторный запуск не создаёт дублей: об этом отчитывается второй проход загрузки.

Запуск:  python etl_import.py
"""

import csv
from collections import Counter
from pathlib import Path

import create_db
import validators

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "final"
SOURCE = DATA_DIR / "enrollments_raw.csv"
STUDENTS_CSV = DATA_DIR / "students.csv"
COURSES_CSV = DATA_DIR / "courses.csv"

REJECTED = BASE_DIR / "rejected_enrollments.csv"
REPORT = BASE_DIR / "etl_report.txt"

ENROLLMENT_COLUMNS = (
    "enrollment_id",
    "student_email",
    "course_code",
    "status",
    "created_date",
    "duration_hours",
    "format",
)

INSERT_SQL = """
    INSERT OR IGNORE INTO enrollments(
        enrollment_id, student_email, course_code, status,
        created_date, duration_hours, format
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
"""


def known_students(path: Path = STUDENTS_CSV) -> set[str]:
    """Возвращает множество e-mail из справочника студентов (в нижнем регистре)."""
    return {
        validators.normalize_email(row["student_email"])
        for row in create_db.read_reference(path)
    }


def known_courses(path: Path = COURSES_CSV) -> set[str]:
    """Возвращает множество кодов курсов из справочника."""
    return {
        validators.normalize_course_code(row["course_code"])
        for row in create_db.read_reference(path)
    }


def read_source(path: Path = SOURCE) -> tuple[list[str], list[tuple]]:
    """Extract: читает CSV и возвращает (заголовок, строки).

    Каждая строка — кортеж (номер_в_файле, словарь_полей, лишние_поля).
    csv.DictReader складывает лишние значения в ключ None: это признак
    неэкранированной запятой, такую строку нельзя проверять по полям.
    """
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        columns = list(reader.fieldnames or [])
        rows = []
        for number, row in enumerate(reader, start=2):  # строка 1 — заголовок
            extra = row.pop(None, None) or []
            rows.append((number, row, extra))
    return columns, rows


def validate_source(
    raw_rows: list[tuple],
    students: set[str],
    courses: set[str],
) -> tuple[list[tuple], list[tuple]]:
    """Validate: возвращает (принятые, отклонённые) строки.

    Принятая строка — (номер_в_файле, нормализованный_словарь).
    Отклонённая строка — (номер_в_файле, исходный_словарь, список_кодов_ошибок).
    Дубликат определяется по enrollment_id внутри пакета: первая строка
    принимается, повторная отклоняется с причиной duplicate_enrollment_id.
    """
    accepted: list[tuple] = []
    rejected: list[tuple] = []
    seen_ids: set[str] = set()

    for number, row, extra in raw_rows:
        if extra:
            # Поля сдвинуты, поэтому проверять их по отдельности бессмысленно.
            # Лишние значения сохраняем в extra_fields, чтобы строку можно было
            # вернуть отправителю целиком, без потери данных.
            rejected.append(
                (number, {**row, "extra_fields": "|".join(extra)}, ["malformed_row"])
            )
            continue

        normalized, errors = validators.normalize_enrollment(row, students, courses)
        if errors:
            rejected.append((number, row, errors))
            continue

        enrollment_id = normalized["enrollment_id"]
        if enrollment_id in seen_ids:
            rejected.append((number, row, ["duplicate_enrollment_id"]))
            continue

        seen_ids.add(enrollment_id)
        accepted.append((number, normalized))
    return accepted, rejected


def load_accepted(connection, accepted: list[tuple]) -> tuple[int, int]:
    """Load: вставляет принятые строки и возвращает (вставлено, пропущено).

    INSERT OR IGNORE не падает на уже существующем enrollment_id,
    поэтому повторный запуск безопасен. Пропущенные строки — это дубли в БД.
    """
    before = connection.execute("SELECT COUNT(*) FROM enrollments").fetchone()[0]
    connection.executemany(
        INSERT_SQL,
        [
            (
                row["enrollment_id"],
                row["student_email"],
                row["course_code"],
                row["status"],
                row["created_date"],
                float(row["duration_hours"]),
                row["format"],
            )
            for _, row in accepted
        ],
    )
    connection.commit()
    after = connection.execute("SELECT COUNT(*) FROM enrollments").fetchone()[0]
    inserted = after - before
    return inserted, len(accepted) - inserted


def write_rejected(rejected: list[tuple], path: Path = REJECTED) -> None:
    """Пишет отклонённые строки в CSV: номер, исходные поля, коды и текст причин.

    Столбец extra_fields заполнен только у строк с лишней запятой: в нём лежат
    значения, которые не поместились в колонки заголовка.
    """
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        fieldnames = ["row_no", *ENROLLMENT_COLUMNS, "extra_fields", "errors", "reason"]
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        for number, row, errors in rejected:
            record = {column: row.get(column, "") for column in ENROLLMENT_COLUMNS}
            record["row_no"] = number
            record["extra_fields"] = row.get("extra_fields", "")
            record["errors"] = "; ".join(errors)
            record["reason"] = validators.describe_reasons(errors)
            writer.writerow(record)


def build_reason_counts(rejected: list[tuple]) -> Counter:
    """Считает, сколько раз встретился каждый код ошибки."""
    counter = Counter()
    for _, _, errors in rejected:
        counter.update(errors)
    return counter


def write_report(
    accepted: list[tuple],
    rejected: list[tuple],
    before: int,
    runs: list[tuple[int, int]],
    total_in_db: int,
    path: Path = REPORT,
) -> None:
    """Формирует контрольный отчёт ETL: объёмы, причины, протокол двух запусков."""
    reason_counts = build_reason_counts(rejected)

    lines = ["КОНТРОЛЬНЫЙ ОТЧЁТ ETL-КОНВЕЙЕРА", "=" * 60]
    lines.append(f"Источник: {SOURCE.relative_to(BASE_DIR)}")
    lines.append(f"Записей в базе до запуска: {before}")
    lines.append(f"Прочитано строк:          {len(accepted) + len(rejected)}")
    lines.append(f"Принято уникальных строк: {len(accepted)}")
    lines.append(f"Отклонено строк:          {len(rejected)}")
    lines.append("")

    lines.append("Протокол загрузки (защита от дублей):")
    for index, (inserted, skipped) in enumerate(runs, start=1):
        lines.append(
            f"  проход {index}: вставлено {inserted}, пропущено как дубли {skipped}"
        )
    lines.append(f"Всего записей в базе:     {total_in_db}")
    lines.append("")

    lines.append("Причины отклонения (сколько раз встретилась):")
    for error, count in reason_counts.most_common():
        lines.append(f"  {error:<28} {count}")
    lines.append("")

    lines.append("Отклонённые строки:")
    for number, row, errors in rejected:
        enrollment_id = row.get("enrollment_id") or "?"
        lines.append(
            f"  строка {number:>2}  {enrollment_id:<18} "
            f"{validators.describe_reasons(errors)}"
        )
    lines.append("")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main() -> None:
    """Выполняет полный ETL-цикл, пишет отчёт и доказательство идемпотентности."""
    connection = create_db.ensure_database()
    try:
        students = known_students()
        courses = known_courses()
        _, raw_rows = read_source()
        accepted, rejected = validate_source(raw_rows, students, courses)

        before = connection.execute("SELECT COUNT(*) FROM enrollments").fetchone()[0]
        first = load_accepted(connection, accepted)
        second = load_accepted(connection, accepted)  # повторный запуск
        total_in_db = connection.execute("SELECT COUNT(*) FROM enrollments").fetchone()[0]

        write_rejected(rejected)
        write_report(
            accepted,
            rejected,
            before,
            [first, second],
            total_in_db,
        )

        assert first[0] + first[1] == len(accepted), "Потеряны строки при загрузке"
        assert second[0] == 0, "Повторный запуск не должен вставлять строки"
        assert total_in_db == before + first[0], "Количество строк в базе не сошлось"

        print(f"\nФайл отклонённых строк: {REJECTED.name}")
        print(f"Контрольный отчёт:      {REPORT.name}")
        print(f"Строк в базе:           {total_in_db}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
