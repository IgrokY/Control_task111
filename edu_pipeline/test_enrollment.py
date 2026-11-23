"""Этап 7. Тесты класса Enrollment (>= 12 проверок).

Запуск:  python -m unittest test_enrollment -v
"""

import unittest

from enrollment import ALLOWED_TRANSITIONS, Enrollment, TrackedEntity


def make_enrollment(**overrides) -> Enrollment:
    """Создаёт корректную заявку для теста."""
    params = {
        "enrollment_id": "EDU-202610-0001",
        "student_email": "ivanov@example.com",
        "course_code": "PY-100",
        "duration_hours": 36,
        "status": "new",
    }
    params.update(overrides)
    return Enrollment(**params)


class TestInitialization(unittest.TestCase):
    """Создание объекта и проверка начальных значений."""

    def test_inheritance(self):
        enrollment = make_enrollment()
        self.assertIsInstance(enrollment, TrackedEntity)
        self.assertTrue(issubclass(Enrollment, TrackedEntity))

    def test_initial_state(self):
        enrollment = make_enrollment()
        self.assertEqual(enrollment.enrollment_id, "EDU-202610-0001")
        self.assertEqual(enrollment.status, "new")
        self.assertEqual(enrollment.duration_hours, 36.0)
        self.assertEqual(enrollment.history(), [])

    def test_values_are_normalized(self):
        enrollment = make_enrollment(
            student_email=" IVANOV@Example.com ", course_code="py-100"
        )
        self.assertEqual(enrollment.student_email, "ivanov@example.com")
        self.assertEqual(enrollment.course_code, "PY-100")

    def test_bad_initial_values_raise(self):
        with self.assertRaises(ValueError):
            make_enrollment(status="unknown")
        with self.assertRaises(ValueError):
            make_enrollment(student_email="bad")
        with self.assertRaises(ValueError):
            make_enrollment(course_code="bad")
        with self.assertRaises(ValueError):
            make_enrollment(duration_hours=0)

    def test_empty_identifier_raises(self):
        with self.assertRaises(ValueError):
            make_enrollment(enrollment_id="")


class TestStatusTransitions(unittest.TestCase):
    """Схема переходов статуса."""

    def test_allowed_chain(self):
        enrollment = make_enrollment()
        enrollment.status = "on_review"
        enrollment.status = "enrolled"
        enrollment.status = "completed"
        self.assertEqual(enrollment.status, "completed")
        self.assertEqual(len(enrollment.history()), 3)

    def test_skip_status_is_forbidden(self):
        enrollment = make_enrollment()
        with self.assertRaises(ValueError):
            enrollment.status = "completed"
        self.assertEqual(enrollment.status, "new")

    def test_terminal_status_is_final(self):
        enrollment = make_enrollment(status="cancelled")
        self.assertEqual(ALLOWED_TRANSITIONS["cancelled"], frozenset())
        with self.assertRaises(ValueError):
            enrollment.status = "new"
        self.assertEqual(enrollment.status, "cancelled")

    def test_unknown_status_raises(self):
        enrollment = make_enrollment()
        with self.assertRaises(ValueError):
            enrollment.status = "deleted"

    def test_same_status_does_not_add_record(self):
        enrollment = make_enrollment(status="on_review")
        enrollment.status = "on_review"
        self.assertEqual(enrollment.history(), [])


class TestHistory(unittest.TestCase):
    """Содержимое журнала и защита копией."""

    def test_record_fields(self):
        enrollment = make_enrollment(status="on_review")
        enrollment.status = "enrolled"
        record = enrollment.history()[0]
        self.assertEqual(set(record), {"at", "field", "old", "new"})
        self.assertEqual(record["field"], "status")
        self.assertEqual(record["old"], "on_review")
        self.assertEqual(record["new"], "enrolled")
        self.assertIsInstance(record["at"], str)

    def test_history_returns_copy(self):
        enrollment = make_enrollment(status="on_review")
        enrollment.status = "enrolled"
        copy = enrollment.history()
        copy.clear()
        copy.append({"at": "fake", "field": "status", "old": "x", "new": "y"})
        self.assertEqual(len(enrollment.history()), 1)
        self.assertEqual(enrollment.history()[0]["new"], "enrolled")

    def test_history_records_are_independent(self):
        enrollment = make_enrollment(status="on_review")
        enrollment.status = "enrolled"
        copy = enrollment.history()
        copy[0]["new"] = "hacked"
        self.assertEqual(enrollment.history()[0]["new"], "enrolled")

    def test_each_object_has_own_history(self):
        first = make_enrollment(status="on_review")
        second = make_enrollment(
            enrollment_id="EDU-202610-0002",
            student_email="petrova@example.com",
            course_code="DA-200",
            status="on_review",
        )
        first.status = "enrolled"
        self.assertEqual(len(first.history()), 1)
        self.assertEqual(second.history(), [])


class TestDurationAndReadOnly(unittest.TestCase):
    """Изменение длительности и защита идентификатора."""

    def test_duration_change_is_logged(self):
        enrollment = make_enrollment()
        enrollment.duration_hours = 40
        self.assertEqual(enrollment.duration_hours, 40.0)
        record = enrollment.history()[0]
        self.assertEqual(record["field"], "duration_hours")
        self.assertEqual(record["old"], 36.0)
        self.assertEqual(record["new"], 40.0)

    def test_bad_duration_raises(self):
        enrollment = make_enrollment()
        for value in (0, -1, 501, "abc", None):
            with self.assertRaises(ValueError):
                enrollment.duration_hours = value
        self.assertEqual(enrollment.duration_hours, 36.0)

    def test_identifier_and_email_are_read_only(self):
        enrollment = make_enrollment()
        with self.assertRaises(AttributeError):
            enrollment.enrollment_id = "FAKE"
        with self.assertRaises(AttributeError):
            enrollment.student_email = "fake@example.com"

    def test_to_dict(self):
        enrollment = make_enrollment(status="on_review")
        self.assertEqual(
            enrollment.to_dict(),
            {
                "enrollment_id": "EDU-202610-0001",
                "student_email": "ivanov@example.com",
                "course_code": "PY-100",
                "duration_hours": 36.0,
                "status": "on_review",
            },
        )


if __name__ == "__main__":
    unittest.main()
