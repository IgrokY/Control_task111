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
    """Загружает buggy_report.py как модуль, не меняя файл и sys.path."""
    if not BUGGY_PATH.exists():
        return None
    spec = importlib.util.spec_from_file_location("buggy_report", BUGGY_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUGGY = load_buggy_module()


class TestFixedReport(unittest.TestCase):
    """Исправленный модуль работает на реальных «неудобных» данных."""

    def test_average_skips_null(self):
        self.assertEqual(fixed_report.average_duration(ROWS_WITH_NULL), 42.0)

    def test_average_empty_returns_zero(self):
        self.assertEqual(fixed_report.average_duration([]), 0.0)

    def test_average_all_null_returns_zero(self):
        rows = [("EDU-001", "new", None)]
        self.assertEqual(fixed_report.average_duration(rows), 0.0)

    def test_top_courses_is_descending(self):
        rows = [("PY",), ("PY",), ("DA",), ("WD",), ("PY",), ("DA",)]
        self.assertEqual(
            fixed_report.top_courses(rows, limit=2),
            [("PY", 3), ("DA", 2)],
        )

    def test_top_courses_tie_is_deterministic(self):
        rows = [("WD",), ("DA",), ("PY",)]
        self.assertEqual(
            fixed_report.top_courses(rows),
            [("DA", 1), ("PY", 1), ("WD", 1)],
        )

    def test_find_by_status_does_not_mutate(self):
        rows = [("a", "new"), ("b", "closed"), ("c", "new")]
        before = list(rows)
        found = fixed_report.find_by_status(rows, "new")
        self.assertEqual(fixed_report.find_by_status(rows, "closed"),
                         [("b", "closed")])
        self.assertEqual(rows, before)
        self.assertEqual(found, [("a", "new"), ("c", "new")])

    def test_report_line_handles_numbers_and_none(self):
        self.assertEqual(
            fixed_report.report_line(12345, "new"), "Заявка 12345 в статусе new"
        )
        self.assertEqual(
            fixed_report.report_line(None, "new"), "Заявка None в статусе new"
        )

    def test_load_closes_connection(self):
        with mock.patch("fixed_report.sqlite3.connect") as connect:
            connection = connect.return_value
            connection.execute.return_value.fetchall.return_value = []
            rows = fixed_report.load_enrollments("any.db")
            self.assertEqual(rows, [])
            connection.close.assert_called_once()

    def test_load_enrollments_from_sqlite(self):
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
        with self.assertRaises(TypeError):
            BUGGY.average_duration(ROWS_WITH_NULL)

    def test_bug_empty_rows_break_average(self):
        with self.assertRaises(ZeroDivisionError):
            BUGGY.average_duration([])

    def test_bug_top_courses_is_ascending(self):
        rows = [("PY",), ("PY",), ("DA",), ("WD",)]
        result = BUGGY.top_courses(rows, limit=3)
        self.assertEqual(result[0][1], 1)   # наверху худший курс
        self.assertEqual(result[-1][1], 2)

    def test_bug_find_by_status_mutates_input(self):
        rows = [("a", "new"), ("b", "closed")]
        before = list(rows)
        BUGGY.find_by_status(rows, "new")
        self.assertNotEqual(rows, before)

    def test_bug_report_line_fails_on_non_string(self):
        with self.assertRaises(TypeError):
            BUGGY.report_line(None, "new")


if __name__ == "__main__":
    unittest.main()
