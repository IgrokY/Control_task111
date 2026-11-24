"""Этап 7. Замеры timeit: две реализации pipeline, Counter и deque.

Скрипт отвечает на практические вопросы:

1. насколько list comprehension отличается от filter + map + lambda;
2. выигрывает ли Counter у ручного подсчёта через dict.get;
3. почему deque, а не list.pop(0) для очереди.

Каждый замер повторяется несколько раз, в отчёт идёт минимальное время —
оно меньше всего зависит от случайной нагрузки на компьютер.
Результат пишется в performance.txt.
Запуск:  python performance_bench.py
"""

import platform
import sys
import timeit
from collections import Counter, deque

import etl_import
import review_queue

BASE_DIR = etl_import.BASE_DIR
REPORT = BASE_DIR / "performance.txt"

REPEAT = 5


def measure(function, number: int) -> float:
    """Возвращает минимальное время одного вызова в миллисекундах."""
    timer = timeit.Timer(function)
    best = min(timer.repeat(repeat=REPEAT, number=number))
    return best / number * 1000


def bench_pipelines(raw_rows: list[tuple], context: dict) -> dict:
    """Сравнивает две эквивалентные реализации очереди проверки."""
    comprehension = measure(
        lambda: review_queue.pipeline_comprehension(raw_rows, context), number=500
    )
    filter_map = measure(
        lambda: review_queue.pipeline_filter_map(raw_rows, context), number=500
    )
    return {
        "comprehension_ms": comprehension,
        "filter_map_ms": filter_map,
        "ratio": filter_map / comprehension if comprehension else 0.0,
    }


def bench_counters(context: dict) -> dict:
    """Сравнивает Counter и ручной подсчёт кодов ошибок."""
    codes = []
    for errors in context["issues"].values():
        codes.extend(errors or ["status_review"])

    def with_counter():
        """Подсчёт через Counter."""
        return Counter(codes)

    def with_dict():
        """Ручной подсчёт через dict.get."""
        result = {}
        for code in codes:
            result[code] = result.get(code, 0) + 1
        return result

    return {
        "counter_ms": measure(with_counter, number=2000),
        "dict_ms": measure(with_dict, number=2000),
        "equal": with_counter() == with_dict(),
    }


def bench_queues(size: int = 1000) -> dict:
    """Сравнивает popleft у deque и pop(0) у списка."""
    items = [{"id": index} for index in range(size)]

    def with_deque():
        """Снятие с головы очереди через deque.popleft()."""
        queue = deque(items)
        while queue:
            queue.popleft()

    def with_list():
        """Снятие с головы очереди через list.pop(0)."""
        queue = list(items)
        while queue:
            queue.pop(0)

    return {
        "deque_ms": measure(with_deque, number=50),
        "list_ms": measure(with_list, number=50),
        "size": size,
    }


def write_report(lines: list[str], path=REPORT) -> None:
    """Пишет протокол замеров в текстовый файл."""
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main() -> None:
    """Проводит три замера и формирует performance.txt."""
    students = etl_import.known_students()
    courses = etl_import.known_courses()
    _, raw_rows = etl_import.read_source()
    context = review_queue.prepare_context(raw_rows, students, courses)

    pipelines = bench_pipelines(raw_rows, context)
    counters = bench_counters(context)
    queues = bench_queues()

    lines = ["ПРОТОКОЛ ЗАМЕРОВ (timeit)", "=" * 60]
    lines.append(f"Python: {sys.version.split()[0]}")
    lines.append(f"Платформа: {platform.platform()}")
    lines.append(f"Повторов на замер: {REPEAT}, показано минимальное время")
    lines.append("")

    lines.append("1. Две реализации очереди проверки (11 заявок из 19 строк)")
    lines.append(f"   №1 list comprehension:      {pipelines['comprehension_ms']:.4f} мс")
    lines.append(f"   №2 filter + map + lambda:   {pipelines['filter_map_ms']:.4f} мс")
    lines.append(f"   отношение №2 / №1:          {pipelines['ratio']:.2f}")
    lines.append("   Вывод: разница незначительна; выбираем вариант по читаемости.")
    lines.append("")

    lines.append("2. Подсчёт кодов ошибок (Counter против dict.get)")
    lines.append(f"   Counter:                    {counters['counter_ms']:.4f} мс")
    lines.append(f"   ручной dict.get:            {counters['dict_ms']:.4f} мс")
    lines.append(f"   результаты совпадают:       {counters['equal']}")
    lines.append("   Вывод: Counter короче и не медленнее ручного подсчёта.")
    lines.append("")

    lines.append(f"3. Снятие {queues['size']} элементов с головы очереди")
    lines.append(f"   deque.popleft():            {queues['deque_ms']:.4f} мс")
    lines.append(f"   list.pop(0):                {queues['list_ms']:.4f} мс")
    speedup = queues["list_ms"] / queues["deque_ms"] if queues["deque_ms"] else 0
    lines.append(f"   list.pop(0) медленнее в:    {speedup:.1f} раза")
    lines.append("   Причина: pop(0) сдвигает все оставшиеся элементы, это O(n);")
    lines.append("   popleft у deque работает за O(1).")
    lines.append("")
    lines.append("Ограничение: на 19 строках разница мала; на тысячах заявок")
    lines.append("асимптотика deque и Counter становится заметной.")

    write_report(lines)
    print(f"\nФайл: {REPORT.name}")


if __name__ == "__main__":
    main()
