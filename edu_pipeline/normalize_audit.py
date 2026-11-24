"""Нормализация «грязного» журнала действий операторов (Этап 3).

Скрипт читает data/final/audit_messy.log, применяет правила из validators.py
и формирует два отчёта:
* before_after.csv — построчное сравнение исходной и нормализованной строки;
* expected_actual.csv — таблица expected/actual для контрольных примеров.

Исходный журнал не изменяется: результаты пишутся в папку проекта.
"""

import csv
from pathlib import Path

import validators

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "final"
SOURCE = DATA_DIR / "audit_messy.log"
BEFORE_AFTER = BASE_DIR / "before_after.csv"
EXPECTED_ACTUAL = BASE_DIR / "expected_actual.csv"

EXPECTED_CASES = [
    (
        "clean-01",
        "INFO  ,,  2026-10-01 09:14:03 ,  заявка 'EDU-202609-0001'  "
        'переведена в статус "enrolled"  оператором ivanov@example.com',
        "INFO, 2026-10-01 09:14:03, заявка \"EDU-202609-0001\" "
        'переведена в статус "enrolled" оператором ivanov@example.com',
        "двойная запятая, лишние пробелы, одинарные кавычки",
    ),
    (
        "clean-02",
        "WARNING , 2026-10-02 11:40:57 , заявка \"EDU-202609-0004\"  "
        "отклонена:  некорректный e-mail,, повторная отправка не требуется",
        "WARNING, 2026-10-02 11:40:57, заявка \"EDU-202609-0004\" "
        "отклонена: некорректный e-mail, повторная отправка не требуется",
        "пробелы вокруг разделителей и повторная запятая",
    ),
    (
        "clean-03",
        "  INFO,2026-10-03 15:02:11,заявка 'EDU-202610-0005'  создана; "
        "формат  обучения: offline  ",
        "INFO, 2026-10-03 15:02:11, заявка \"EDU-202610-0005\" создана; "
        "формат обучения: offline",
        "краевые пробелы и точка с запятой без пробела",
    ),
    (
        "clean-04",
        "INFO\t,\t2026-10-07 09:05:37,\tзаявка \"EDU-202610-0018\"  "
        "продублирована,,  дубликат проигнорирован",
        "INFO, 2026-10-07 09:05:37, заявка \"EDU-202610-0018\" "
        "продублирована, дубликат проигнорирован",
        "табуляции вместо пробелов",
    ),
    (
        "separator-05",
        "a||b;;c,,d",
        "a| b; c, d",
        "повторные разделители разных типов",
    ),
    (
        "quote-06",
        "  '  Иванов  '  ",
        '"Иванов"',
        "пробелы внутри парных кавычек и разные типы кавычек",
    ),
    (
        "quote-07",
        'INFO, 2026-10-08 19:22:48, заявка \'EDU-202610-0017\' '
        'содержит адрес "pavlova@example,com"',
        'INFO, 2026-10-08 19:22:48, заявка "EDU-202610-0017" '
        'содержит адрес "pavlova@example,com"',
        "запятая внутри кавычек не должна стать разделителем",
    ),
    (
        "quote-08",
        "WARNING , 2026-10-06 10:31:09 ,  неизвестный код курса  «XX-999» "
        "в заявке 'EDU-202610-0011'",
        'WARNING, 2026-10-06 10:31:09, неизвестный код курса "XX-999" '
        'в заявке "EDU-202610-0011"',
        "«ёлочки» приводятся к тем же двойным кавычкам",
    ),
    (
        "quote-09",
        "заявка д'Артаньян в статусе 'new'",
        "заявка д'Артаньян в статусе \"new\"",
        "апостроф внутри слова не считается кавычкой",
    ),
    (
        "negative-08",
        "заявка 'EDU-1 без закрывающей кавычки",
        "заявка 'EDU-1 без закрывающей кавычки",
        "незакрытая кавычка: строка не изменяется",
    ),
    (
        "negative-09",
        "",
        "",
        "пустая строка",
    ),
    (
        "negative-10",
        '  "  "  ',
        '""',
        "пустой фрагмент в парных кавычках",
    ),
    (
        "negative-11",
        "   ",
        "",
        "строка только из пробелов",
    ),
]


def read_lines(path: Path) -> list[str]:
    """Читает текстовый файл в UTF-8 с удалением BOM, сохраняя строки."""
    with path.open(encoding="utf-8-sig") as source:
        return [line.rstrip("\n") for line in source]


def write_before_after(rows: list[tuple[int, str, str]], path: Path) -> None:
    """Записывает отчёт before/after в CSV для открытия в Excel."""
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.writer(target)
        writer.writerow(["line_no", "before", "after", "changed", "unbalanced_quotes"])
        for line_no, before, after in rows:
            writer.writerow(
                [line_no, before, after, before != after,
                 validators.has_unbalanced_quotes(before)]
            )


def write_expected_actual(results: list[tuple], path: Path) -> None:
    """Записывает таблицу expected/actual и признак совпадения."""
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.writer(target)
        writer.writerow(
            ["case_id", "before", "expected", "actual", "match", "comment"]
        )
        writer.writerows(results)


def build_expected_actual() -> list[tuple]:
    """Прогоняет контрольные примеры и возвращает строки таблицы."""
    results = []
    for case_id, before, expected, comment in EXPECTED_CASES:
        actual = validators.normalize_audit_line(before)
        results.append((case_id, before, expected, actual, actual == expected, comment))
    return results


def main() -> None:
    """Нормализует журнал и печатает краткий отчёт."""
    lines = read_lines(SOURCE)
    normalized = [(number, line, validators.normalize_audit_line(line))
                  for number, line in enumerate(lines, start=1)]
    write_before_after(normalized, BEFORE_AFTER)

    results = build_expected_actual()
    write_expected_actual(results, EXPECTED_ACTUAL)

    changed = sum(1 for _, before, after in normalized if before != after)
    print(f"Строк в журнале: {len(lines)}")
    print(f"Изменено строк: {changed}")
    print(f"Контрольных примеров: {len(results)}")
    print(f"Совпало с expected: {sum(1 for item in results if item[4])}")
    print(f"Отчёт before/after: {BEFORE_AFTER.name}")
    print(f"Таблица expected/actual: {EXPECTED_ACTUAL.name}")

    for case_id, _, expected, actual, match, _ in results:
        if not match:
            print(f"  {case_id}: expected={expected!r}, actual={actual!r}")

    if not all(item[4] for item in results):
        raise SystemExit("Есть расхождения с контрольными примерами")


if __name__ == "__main__":
    main()
