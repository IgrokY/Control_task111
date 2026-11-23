"""Этап 7. Тесты валидаторов и нормализации (>= 12 проверок).

Запуск:  python -m unittest test_validators -v
"""

import csv
import unittest
from pathlib import Path

import validators

DATA_DIR = Path(__file__).resolve().parent / "data" / "final"


def make_row(**overrides) -> dict:
    """Собирает корректную строку заявки и заменяет указанные поля."""
    row = {
        "enrollment_id": "EDU-202610-0001",
        "student_email": "ivanov@example.com",
        "course_code": "PY-100",
        "status": "enrolled",
        "created_date": "2026-10-01",
        "duration_hours": "36",
        "format": "online",
    }
    row.update(overrides)
    return row


class TestIdentifiers(unittest.TestCase):
    """Идентификатор заявки и код курса."""

    def test_enrollment_id_named_groups(self):
        match = validators.ENROLLMENT_ID_RE.fullmatch("EDU-202610-0042")
        self.assertIsNotNone(match)
        self.assertEqual(match.group("prefix"), "EDU")
        self.assertEqual(match.group("period"), "202610")
        self.assertEqual(match.group("sequence"), "0042")

    def test_enrollment_id_rejects_lowercase_and_short_sequence(self):
        self.assertEqual(
            validators.validate_enrollment_id("edu-202610-0015"),
            ["invalid_enrollment_id"],
        )
        self.assertEqual(
            validators.validate_enrollment_id("EDU-202609-004"),
            ["invalid_enrollment_id"],
        )
        self.assertEqual(
            validators.validate_enrollment_id("EDU-2026AA-0016"),
            ["invalid_enrollment_id"],
        )

    def test_course_code(self):
        self.assertEqual(validators.validate_course_code("PY-100"), [])
        self.assertEqual(
            validators.validate_course_code("PY100"), ["invalid_course_code"]
        )


class TestSimpleFields(unittest.TestCase):
    """E-mail, дата, длительность, статус и формат."""

    def test_email(self):
        self.assertEqual(validators.validate_email("Ivanov@Example.com".lower()), [])
        self.assertEqual(
            validators.validate_email("smirnova@example"), ["invalid_email"]
        )
        self.assertEqual(
            validators.validate_email("pavlova@example,com"), ["invalid_email"]
        )

    def test_date_format_and_calendar(self):
        self.assertEqual(validators.validate_date("2026-10-01"), [])
        self.assertEqual(validators.validate_date("2026-02-29"), ["invalid_date"])
        self.assertEqual(validators.validate_date("2028-02-29"), [])
        self.assertEqual(validators.validate_date("01.10.2026"), ["invalid_date"])

    def test_duration_boundaries(self):
        self.assertEqual(validators.validate_duration("1"), [])
        self.assertEqual(validators.validate_duration("500"), [])
        self.assertEqual(validators.validate_duration("0"), ["invalid_duration"])
        self.assertEqual(validators.validate_duration("501"), ["invalid_duration"])
        self.assertEqual(validators.validate_duration("-5"), ["invalid_duration"])
        self.assertEqual(validators.validate_duration("abc"), ["invalid_duration"])

    def test_status_and_format(self):
        self.assertEqual(validators.validate_status("on_review"), [])
        self.assertEqual(
            validators.validate_status("paused"), ["invalid_status"]
        )
        self.assertEqual(validators.validate_format("offline"), [])
        self.assertEqual(
            validators.validate_format("mixed"), ["invalid_format"]
        )


class TestNormalization(unittest.TestCase):
    """Нормализация текста журнала и строк заявок."""

    def test_spaces_collapse(self):
        self.assertEqual(
            validators.normalize_spaces("  INFO \t ,,   текст  "),
            "INFO ,, текст",
        )

    def test_separators_collapse(self):
        self.assertEqual(
            validators.normalize_separators("a||b;;c,,d"),
            "a| b; c, d",
        )

    def test_quote_backreference_replaces_pair(self):
        self.assertEqual(validators.normalize_audit_line("  '  Иванов  '  "), '"Иванов"')
        self.assertEqual(validators.normalize_quotes("'Иванов'"), '"Иванов"')

    def test_unbalanced_quote_is_not_changed(self):
        line = "заявка 'EDU-1 без закрывающей кавычки"
        self.assertEqual(validators.normalize_audit_line(line), line)
        self.assertTrue(validators.has_unbalanced_quotes(line))
        self.assertFalse(validators.has_unbalanced_quotes('заявка "EDU-1"'))

    def test_comma_inside_quotes_is_preserved(self):
        line = "адрес \"pavlova@example,com\" в заявке"
        self.assertEqual(validators.normalize_separators(line), line)

    def test_empty_and_whitespace_lines(self):
        self.assertEqual(validators.normalize_audit_line(""), "")
        self.assertEqual(validators.normalize_audit_line("   "), "")

    def test_full_audit_line(self):
        source = (
            "INFO  ,,  2026-10-01 09:14:03 ,  заявка 'EDU-202609-0001'  "
            "переведена в статус \"enrolled\"  оператором ivanov@example.com"
        )
        expected = (
            "INFO, 2026-10-01 09:14:03, заявка \"EDU-202609-0001\" "
            "переведена в статус \"enrolled\" оператором ivanov@example.com"
        )
        self.assertEqual(validators.normalize_audit_line(source), expected)


class TestEnrollmentValidation(unittest.TestCase):
    """Комплексная проверка строки заявки."""

    def test_valid_row_normalizes_values(self):
        row, errors = validators.normalize_enrollment(make_row(
            student_email="  IVANOV@example.com ", course_code="py-100"
        ))
        self.assertEqual(errors, [])
        self.assertEqual(row["student_email"], "ivanov@example.com")
        self.assertEqual(row["course_code"], "PY-100")
        self.assertEqual(row["duration_hours"], 36.0)

    def test_missing_field(self):
        row, errors = validators.normalize_enrollment(
            make_row(student_email="")
        )
        self.assertIn("missing_field:student_email", errors)
        self.assertEqual(row["student_email"], "")

    def test_unknown_references(self):
        students = {"ivanov@example.com"}
        courses = {"PY-100"}
        _, errors = validators.normalize_enrollment(
            make_row(student_email="nobody@example.com", course_code="XX-999"),
            students,
            courses,
        )
        self.assertIn("unknown_student", errors)
        self.assertIn("unknown_course", errors)

    def test_period_date_mismatch(self):
        _, errors = validators.normalize_enrollment(
            make_row(enrollment_id="EDU-202609-0001", created_date="2026-10-01")
        )
        self.assertIn("period_date_mismatch", errors)

    def test_all_errors_collected_not_only_first(self):
        _, errors = validators.normalize_enrollment(make_row(
            enrollment_id="BAD",
            student_email="bad",
            course_code="bad",
            status="paused",
            created_date="2026-13-40",
            duration_hours="-1",
            format="mixed",
        ))
        self.assertGreaterEqual(len(errors), 7)
        for code in ("invalid_enrollment_id", "invalid_email", "invalid_course_code",
                     "invalid_status", "invalid_date", "invalid_duration",
                     "invalid_format"):
            self.assertIn(code, errors)

    def test_reason_messages_are_human_readable(self):
        text = validators.describe_reasons(
            ["invalid_email", "missing_field:student_email"]
        )
        self.assertIn("e-mail", text)
        self.assertIn("student_email", text)

    def test_malformed_row_has_reason_message(self):
        self.assertIn(
            "заголовк",
            validators.describe_reasons(["malformed_row"]),
        )


class TestRealFiles(unittest.TestCase):
    """Проверка на реальном файле из data/final (файл не изменяется)."""

    def test_reference_files_are_readable(self):
        with (DATA_DIR / "students.csv").open(encoding="utf-8-sig", newline="") as source:
            students = {row["student_email"] for row in csv.DictReader(source)}
        with (DATA_DIR / "courses.csv").open(encoding="utf-8-sig", newline="") as source:
            courses = {row["course_code"] for row in csv.DictReader(source)}
        self.assertEqual(len(students), 16)
        self.assertEqual(len(courses), 5)

    def test_real_batch_gives_ten_unique_valid_rows(self):
        with (DATA_DIR / "students.csv").open(encoding="utf-8-sig", newline="") as source:
            students = {row["student_email"] for row in csv.DictReader(source)}
        with (DATA_DIR / "courses.csv").open(encoding="utf-8-sig", newline="") as source:
            courses = {row["course_code"] for row in csv.DictReader(source)}

        valid_ids = set()
        with (DATA_DIR / "enrollments_raw.csv").open(
            encoding="utf-8-sig", newline=""
        ) as source:
            reader = csv.DictReader(source)
            for row in reader:
                if row.get(None):  # неэкранированная запятая
                    continue
                normalized, errors = validators.normalize_enrollment(
                    row, students, courses
                )
                if not errors:
                    valid_ids.add(normalized["enrollment_id"])
        self.assertEqual(len(valid_ids), 10)


if __name__ == "__main__":
    unittest.main()
