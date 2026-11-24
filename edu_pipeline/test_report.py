"""Этап 7. Регрессионные тесты исправленного модуля отчётности.

Тесты разделены на две группы:

* TestFixedReport — проверяет исправленное поведение fixed_report.py;
* TestBuggyReportReproduction — воспроизводит дефекты исходного buggy_report.py,
  чтобы было видно, что тесты действительно ловят именно эти ошибки.

Исходный buggy_report.py не изменяется, он лежит в data/final/.
Запуск:  python -m unittest test_report -v
"""

import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fixed_report

BASE_DIR = Path(__file__).resolve().parent
BUGGY_PATH = BASE_DIR / "data" / "final" / "buggy_report.py"

ROWS_WITH_NULL = [
    ("EDU-001", "enrolled", 36.0),
    ("EDU-002", "completed", 48.0),
    ("EDU-003", "on_review", None),
]


def load_buggy_module():
    """Загружает buggy_report.py как модуль, не меняя файл и sys.path.

    Запись байт-кода на время загрузки отключена: иначе Python создал бы
    в data/final/ папку __pycache__, а исходная папка должна остаться нетронутой.
    """
    if not BUGGY_PATH.exists():
        return None
    spec = importlib.util.spec_from_file_location("buggy_report", BUGGY_PATH)
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


BUGGY = load_buggy_module()


class TestFixedReport(unittest.TestCase):
    """Исправленный модуль работает на реальных «неудобных» данных."""

    def test_average_skips_null(self):
        """NULL в длительности пропускается, среднее считается по остальным."""
        self.assertEqual(fixed_report.average_duration(ROWS_WITH_NULL), 42.0)

    def test_average_empty_returns_zero(self):
        """Пустой набор даёт 0.0, а не ZeroDivisionError."""
        self.assertEqual(fixed_report.average_duration([]), 0.0)

    def test_average_all_null_returns_zero(self):
        """Набор из одних NULL даёт 0.0."""
        rows = [("EDU-001", "new", None)]
        self.assertEqual(fixed_report.average_duration(rows), 0.0)

    def test_top_courses_is_descending(self):
        """Топ курсов идёт по убыванию числа заявок."""
        rows = [("PY",), ("PY",), ("DA",), ("WD",), ("PY",), ("DA",)]
        self.assertEqual(
            fixed_report.top_courses(rows, limit=2),
            [("PY", 3), ("DA", 2)],
        )

    def test_top_courses_tie_is_deterministic(self):
        """При равенстве числа заявок порядок задаёт код курса."""
        rows = [("WD",), ("DA",), ("PY",)]
        self.assertEqual(
            fixed_report.top_courses(rows),
            [("DA", 1), ("PY", 1), ("WD", 1)],
        )

    def test_find_by_status_does_not_mutate(self):
        """find_by_status не меняет порядок исходного списка."""
        rows = [("a", "new"), ("b", "closed"), ("c", "new")]
        before = list(rows)
        found = fixed_report.find_by_status(rows, "new")
        self.assertEqual(fixed_report.find_by_status(rows, "closed"),
                         [("b", "closed")])
        self.assertEqual(rows, before)
        self.assertEqual(found, [("a", "new"), ("c", "new")])

    def test_report_line_handles_numbers_and_none(self):
        """Число и None в идентификаторе не ломают строку отчёта."""
        self.assertEqual(
            fixed_report.report_line(12345, "new"), "Заявка 12345 в статусе new"
        )
        self.assertEqual(
            fixed_report.report_line(None, "new"), "Заявка None в статусе new"
        )

    def test_load_closes_connection(self):
        """Соединение с базой закрывается после чтения."""
        with mock.patch("fixed_report.sqlite3.connect") as connect:
            connection = connect.return_value
            connection.execute.return_value.fetchall.return_value = []
            rows = fixed_report.load_enrollments("any.db")
            self.assertEqual(rows, [])
            connection.close.assert_called_once()

    def test_load_closes_connection_on_error(self):
        """Соединение закрывается даже при ошибке запроса."""
        with mock.patch("fixed_report.sqlite3.connect") as connect:
            connection = connect.return_value
            connection.execute.side_effect = sqlite3.OperationalError("no such table")
            with self.assertRaises(sqlite3.OperationalError):
                fixed_report.load_enrollments("any.db")
            connection.close.assert_called_once()

    def test_load_enrollments_from_sqlite(self):
        """Чтение из настоящей временной базы SQLite."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "report.db"
            connection = sqlite3.connect(path)
            try:
                connection.execute(
                    "CREATE TABLE enrollments("
                    " enrollment_id TEXT, status TEXT, duration_hours REAL)"
                )
                connection.executemany(
                    "INSERT INTO enrollments VALUES (?, ?, ?)", ROWS_WITH_NULL
                )
                connection.commit()
            finally:
                connection.close()

            rows = fixed_report.load_enrollments(path)
            self.assertEqual(len(rows), 3)
            self.assertEqual(fixed_report.average_duration(rows), 42.0)


@unittest.skipIf(BUGGY is None, "buggy_report.py не найден")
class TestBuggyReportReproduction(unittest.TestCase):
    """Дефекты исходного модуля воспроизводятся — значит, тесты не «пустые»."""

    def test_bug_null_duration_breaks_average(self):
        """Дефект 1: исходный модуль падает на NULL (TypeError)."""
        with self.assertRaises(TypeError):
            BUGGY.average_duration(ROWS_WITH_NULL)

    def test_bug_empty_rows_break_average(self):
        """Дефект 2: исходный модуль делит на ноль на пустом наборе."""
        with self.assertRaises(ZeroDivisionError):
            BUGGY.average_duration([])

    def test_bug_top_courses_is_ascending(self):
        """Дефект 3: исходный top_courses возвращает худшие курсы."""
        rows = [("PY",), ("PY",), ("DA",), ("WD",)]
        result = BUGGY.top_courses(rows, limit=3)
        self.assertEqual(result[0][1], 1)   # наверху худший курс
        self.assertEqual(result[-1][1], 2)

    def test_bug_find_by_status_mutates_input(self):
        """Дефект 4: исходный find_by_status сортирует список вызывающего кода."""
        rows = [("a", "new"), ("b", "closed")]
        before = list(rows)
        BUGGY.find_by_status(rows, "new")
        self.assertNotEqual(rows, before)

    def test_bug_report_line_fails_on_non_string(self):
        """Дефект 5: исходный report_line падает на не-строке."""
        with self.assertRaises(TypeError):
            BUGGY.report_line(None, "new")

    def test_bug_load_enrollments_never_closes_connection(self):
        """Дефект 6: исходный load_enrollments не закрывает соединение."""
        with mock.patch.object(BUGGY.sqlite3, "connect") as connect:
            connection = connect.return_value
            connection.execute.return_value.fetchall.return_value = []
            BUGGY.load_enrollments("any.db")
            connection.close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
