"""Этап 2. Очередь проверки заявок: две эквивалентные реализации pipeline.

Задача оператора — получить очередь заявок, которые нельзя обработать
автоматически. В очередь попадают:

* строки с ошибками данных (их нельзя загрузить, но и терять нельзя);
* корректные заявки в статусах new и on_review (нужно решение оператора).

Очередь строится двумя независимыми способами:

* pipeline_comprehension — list comprehension;
* pipeline_filter_map  — filter + map + lambda.

Эквивалентность доказывается сравнением q1 == q2, а неизменность исходных
данных — сравнением с deepcopy-снимком. Коллекции применяются по назначению:
Counter считает причины и приоритеты, defaultdict группирует очередь по курсам,
deque отдаёт заявки с головы очереди за O(1).

Запуск:  python review_queue.py
"""

import copy
import csv
from collections import Counter, defaultdict, deque
from pathlib import Path

import etl_import
import validators

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "final"
QUEUE_CSV = BASE_DIR / "review_queue.csv"
COMPARISON_CSV = BASE_DIR / "review_queue_comparison.csv"

REVIEW_STATUSES = {"new", "on_review"}
PRIORITY_RANK = {"high": 0, "normal": 1}
CONTACT_ERRORS = {
    "invalid_email",
    "unknown_student",
    "missing_field:student_email",
    "malformed_row",
}

COMPARISON_ROWS = [
    ("Порядок чтения", "слева направо: что строим, откуда и при каком if",
     "изнутри наружу: сначала filter, затем map"),
    ("Условие отбора", "видно в той же конструкции", "вынесено в отдельную lambda"),
    ("Преобразование", "в начале выражения", "вторая lambda после filter"),
    ("Ленивость", "список создаётся сразу", "filter/map ленивы до sorted"),
    ("Отладка", "имя функции видно в трейсбеке", "в трейсбеке '<lambda>'"),
    ("Читаемость", "лучше для отбора + преобразования", "хуже при длинном условии"),
    ("Когда выбирать", "типовой случай этого проекта", "готовые именованные функции"),
]


# --------------------------------------------------------------------------
# Общая подготовка: валидация выполняется один раз для обоих pipeline
# --------------------------------------------------------------------------
def parse_hours(value) -> float | None:
    """Строку длительности -> float; нечисловое значение -> None."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def prepare_context(
    raw_rows: list[tuple],
    students: set[str],
    courses: set[str],
) -> dict:
    """Проверяет строки и возвращает контекст для pipeline.

    Контекст — обычный словарь:
    * rows   — номер строки -> нормализованная (или исходная) строка;
    * issues — номер строки -> список кодов ошибок.

    Валидация общая для двух реализаций: pipeline сравниваются по отбору
    и сборке очереди, а не по повторному вызову регулярок.
    """
    rows: dict[int, dict] = {}
    issues: dict[int, list[str]] = {}

    for number, row, extra in raw_rows:
        if extra:
            # Поля сдвинуты (лишняя запятая), поэтому «курс», «статус» и дата
            # в такой строке недостоверны. В очередь берём только идентификатор.
            rows[number] = {"enrollment_id": row.get("enrollment_id", "")}
            issues[number] = ["malformed_row"]
            continue
        normalized, errors = validators.normalize_enrollment(row, students, courses)
        rows[number] = normalized if not errors else row
        issues[number] = errors
    return {"rows": rows, "issues": issues}


def needs_review(number: int, context: dict) -> bool:
    """Нужна ли строке ручная проверка оператора."""
    row = context["rows"][number]
    return bool(context["issues"][number]) or row.get("status") in REVIEW_STATUSES


def make_item(number: int, context: dict) -> dict:
    """Создаёт элемент очереди — КОПИЮ данных строки с полями проверки.

    Исходный словарь не изменяется: все новые поля попадают только в копию.
    """
    row = context["rows"][number]
    errors = context["issues"][number]
    priority = "high" if errors else "normal"
    if errors:
        queue_reason = "ошибки данных: " + validators.describe_reasons(errors)
    else:
        queue_reason = f"статус {row.get('status')} требует решения оператора"

    return {
        "row_no": number,
        "enrollment_id": row.get("enrollment_id", ""),
        "student_email": row.get("student_email", ""),
        "course_code": row.get("course_code", ""),
        "status": row.get("status", ""),
        "created_date": row.get("created_date", ""),
        "duration_hours": parse_hours(row.get("duration_hours")),
        "format": row.get("format", ""),
        "source": "invalid" if errors else "valid",
        "reasons": list(errors),
        "review_priority": priority,
        "queue_reason": queue_reason,
        "needs_contact": any(error in CONTACT_ERRORS for error in errors),
    }


def sort_key(item: dict) -> tuple:
    """Сначала ошибки данных, затем статусы; внутри — по дате и номеру строки."""
    return (
        PRIORITY_RANK[item["review_priority"]],
        item["created_date"] or "9999-99-99",
        item["row_no"],
    )


# --------------------------------------------------------------------------
# Pipeline №1 — list comprehension
# --------------------------------------------------------------------------
def pipeline_comprehension(raw_rows: list[tuple], context: dict) -> list[dict]:
    """Очередь через list comprehension: отбор и сборка в одной конструкции."""
    selected = [
        make_item(number, context)
        for number, _, _ in raw_rows
        if needs_review(number, context)
    ]
    return sorted(selected, key=sort_key)


# --------------------------------------------------------------------------
# Pipeline №2 — filter + map + lambda
# --------------------------------------------------------------------------
def pipeline_filter_map(raw_rows: list[tuple], context: dict) -> list[dict]:
    """Та же очередь через filter + map + lambda (ленивые итераторы)."""
    numbers = map(lambda row: row[0], raw_rows)
    selected = map(
        lambda number: make_item(number, context),
        filter(lambda number: needs_review(number, context), numbers),
    )
    return sorted(selected, key=sort_key)


# --------------------------------------------------------------------------
# Работа с очередью через collections
# --------------------------------------------------------------------------
def build_processing_queue(queue: list[dict]) -> deque:
    """deque очереди: popleft() снимает заявку с головы за O(1)."""
    return deque(dict(item) for item in queue)


def process_queue(queue: deque, limit: int = 5) -> tuple[list[dict], int]:
    """Снимает до limit заявок с головы; возвращает (снятые, сколько осталось)."""
    processed = []
    while queue and len(processed) < limit:
        processed.append(queue.popleft())
    return processed, len(queue)


def group_by_course(queue: list[dict]) -> defaultdict:
    """defaultdict(list): группировка очереди по коду курса без проверки ключа.

    Заявки, у которых курс определить нельзя (сломанная строка), попадают
    в группу «(курс не определён)».
    """
    groups = defaultdict(list)
    for item in queue:
        groups[item["course_code"] or "(курс не определён)"].append(item)
    return groups


def count_reasons(queue: list[dict]) -> Counter:
    """Counter причин: одна строка может дать несколько причин."""
    counter = Counter()
    for item in queue:
        counter.update(item["reasons"] or ["status_review"])
    return counter


# --------------------------------------------------------------------------
# Вывод и отчёты
# --------------------------------------------------------------------------
def print_queue(queue: list[dict]) -> None:
    """Печатает очередь в виде таблицы."""
    print(f"\nОчередь проверки (заявок: {len(queue)})")
    print(f"{'№':>2} {'заявка':<18}{'приоритет':<13}{'источник':<10}"
          f"{'статус':<11}причина")
    for item in queue:
        print(f"{item['queue_position']:>2} {item['enrollment_id']:<18}"
              f"{item['review_priority']:<13}{item['source']:<10}"
              f"{item['status']:<11}{item['queue_reason'][:55]}")


def write_queue(queue: list[dict], path: Path = QUEUE_CSV) -> None:
    """Сохраняет очередь в CSV (Excel-friendly, UTF-8 с BOM)."""
    fieldnames = [
        "queue_position", "row_no", "enrollment_id", "student_email",
        "course_code", "status", "created_date", "duration_hours", "format",
        "source", "review_priority", "needs_contact", "reasons", "queue_reason",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        for item in queue:
            record = {key: item.get(key, "") for key in fieldnames}
            record["reasons"] = "; ".join(item["reasons"])
            writer.writerow(record)


def write_comparison(path: Path = COMPARISON_CSV) -> None:
    """Сохраняет таблицу сравнения двух реализаций pipeline."""
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.writer(target)
        writer.writerow(["criterion", "pipeline_1_comprehension", "pipeline_2_filter_map"])
        writer.writerows(COMPARISON_ROWS)


def print_comparison() -> None:
    """Печатает таблицу сравнения в консоль."""
    print("\nСравнение реализаций pipeline")
    print(f"{'критерий':<18} | {'№1 list comprehension':<44} | №2 filter + map + lambda")
    for criterion, first, second in COMPARISON_ROWS:
        print(f"{criterion:<18} | {first:<44} | {second}")


# --------------------------------------------------------------------------
# Точка входа
# --------------------------------------------------------------------------
def main() -> None:
    """Строит очередь двумя способами и доказывает их эквивалентность."""
    students = etl_import.known_students()
    courses = etl_import.known_courses()
    _, raw_rows = etl_import.read_source(DATA_DIR / "enrollments_raw.csv")
    snapshot = copy.deepcopy(raw_rows)  # эталон неизменности исходных данных

    context = prepare_context(raw_rows, students, courses)
    queue1 = pipeline_comprehension(raw_rows, context)
    queue2 = pipeline_filter_map(raw_rows, context)

    # Нумерация позиций — общая для обеих очередей (1..N).
    for position, item in enumerate(queue1, start=1):
        item["queue_position"] = position
    queue2 = [{**item, "queue_position": index}
              for index, item in enumerate(queue2, start=1)]

    print_queue(queue1)
    print_comparison()

    print("\nПроверки эквивалентности и неизменности")
    print("  Очереди идентичны (q1 == q2):        ", queue1 == queue2)
    print("  Исходные строки не изменились:       ", raw_rows == snapshot)
    print("  В исходных строках нет новых полей:  ",
          all("queue_reason" not in row for _, row, _ in raw_rows))
    print("  Элементы очереди — копии:            ",
          all(item is not row for item in queue1 for _, row, _ in raw_rows))

    priorities = Counter(item["review_priority"] for item in queue1)
    print(f"\nПриоритеты: high={priorities['high']}, normal={priorities['normal']}")

    print("\nПричины проверки (Counter):")
    for reason, count in count_reasons(queue1).most_common():
        print(f"  {reason:<28}{count}")

    print("\nОчередь по курсам (defaultdict):")
    for course, items in sorted(group_by_course(queue1).items()):
        print(f"  {course:<20}{len(items)}")

    processing = build_processing_queue(queue1)
    processed, left = process_queue(processing)
    print("\nПервые 5 заявок, снятых с головы deque:")
    for item in processed:
        print(f"  {item['enrollment_id']:<18}{item['review_priority']}")
    print(f"  осталось в очереди: {left}")

    write_queue(queue1)
    write_comparison()
    print(f"\nОчередь сохранена:      {QUEUE_CSV.name}")
    print(f"Таблица сравнения:      {COMPARISON_CSV.name}")

    assert queue1 == queue2, "Pipeline дали разные очереди"
    assert raw_rows == snapshot, "Исходные данные были изменены"
    assert len(queue1) == 11, "Контрольное число заявок в очереди не совпало"
    print("Эквивалентность доказана, исходные данные не изменены.")


if __name__ == "__main__":
    main()
