"""Этап 6. Класс заявки на обучение с инкапсуляцией состояния и историей.

Требование кейса: внешний код читает состояние, но не может произвольно
испортить внутренний журнал. Поэтому журнал хранится в закрытом атрибуте
базового класса и выдаётся наружу только копией.

Класс Enrollment расширяет TrackedEntity:

* свойства status и duration_hours проверяют значения в setter;
* статус меняется только по разрешённой схеме переходов;
* каждое успешное изменение пишется в журнал: поле, старое и новое значение,
  время изменения;
* history() возвращает копию журнала, поэтому clear() снаружи ничего не ломает.
"""

from datetime import datetime
from typing import Any

import validators

VALID_STATUSES = frozenset(
    {"new", "on_review", "enrolled", "completed", "cancelled"}
)

# Схема допустимых переходов: из статуса -> во множество следующих статусов.
# Терминальные статусы completed и cancelled дальше не меняются.
ALLOWED_TRANSITIONS = {
    "new": frozenset({"on_review", "cancelled"}),
    "on_review": frozenset({"enrolled", "cancelled"}),
    "enrolled": frozenset({"completed", "cancelled"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
}


class TrackedEntity:
    """Базовый объект с идентификатором и внутренним журналом изменений.

    Журнал недоступен напрямую: снаружи его можно только прочитать копией
    через history(), а добавляет записи только наследник через _add_record().
    """

    def __init__(self, entity_id: str) -> None:
        """Создаёт объект с идентификатором и пустым журналом."""
        if not entity_id:
            raise ValueError("Идентификатор не может быть пустым")
        self.__entity_id = entity_id
        self.__history: list[dict[str, Any]] = []

    @property
    def entity_id(self) -> str:
        """Идентификатор объекта (только для чтения)."""
        return self.__entity_id

    def _add_record(self, field: str, old_value: Any, new_value: Any) -> None:
        """Добавляет запись об изменении. Вызывается только внутри классов."""
        self.__history.append(
            {
                "at": datetime.now().isoformat(timespec="seconds"),
                "field": field,
                "old": old_value,
                "new": new_value,
            }
        )

    def history(self) -> list[dict[str, Any]]:
        """Возвращает КОПИЮ журнала: изменения копии не затрагивают оригинал."""
        return [dict(record) for record in self.__history]


class Enrollment(TrackedEntity):
    """Заявка на обучение с проверяемым статусом и историей изменений."""

    def __init__(
        self,
        enrollment_id: str,
        student_email: str,
        course_code: str,
        duration_hours: float = 1.0,
        status: str = "new",
    ) -> None:
        """Создаёт заявку и проверяет все начальные значения.

        Идентификатор проверяется тем же шаблоном, что и в ETL (validators.py).
        Начальный статус проверяется по белому списку, но в журнал не пишется:
        журнал описывает изменения, а не исходное состояние.
        """
        if validators.validate_enrollment_id(enrollment_id):
            raise ValueError(f"Недопустимый идентификатор заявки: {enrollment_id!r}")
        super().__init__(enrollment_id)
        self._student_email = self._check_email(student_email)
        self._course_code = self._check_course_code(course_code)
        self._duration_hours = self._check_duration(duration_hours)
        self._check_status(status)
        self._status = status

    # ------------------------------------------------------------------
    # Проверки значений
    # ------------------------------------------------------------------
    @staticmethod
    def _check_email(value: str) -> str:
        """Проверяет e-mail регулярным выражением из validators.py."""
        email = validators.normalize_email(value)
        if not validators.EMAIL_RE.fullmatch(email):
            raise ValueError(f"Недопустимый e-mail: {value!r}")
        return email

    @staticmethod
    def _check_course_code(value: str) -> str:
        """Проверяет код курса вида PY-100."""
        code = validators.normalize_course_code(value)
        if not validators.COURSE_CODE_RE.fullmatch(code):
            raise ValueError(f"Недопустимый код курса: {value!r}")
        return code

    @staticmethod
    def _check_duration(value: float) -> float:
        """Приводит длительность к float и проверяет диапазон часов."""
        try:
            hours = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"Длительность должна быть числом: {value!r}") from None
        if not validators.MIN_DURATION <= hours <= validators.MAX_DURATION:
            raise ValueError(
                "Длительность должна быть от "
                f"{validators.MIN_DURATION:g} до {validators.MAX_DURATION:g} часов: {hours!r}"
            )
        return hours

    @staticmethod
    def _check_status(status: str) -> None:
        """Выбрасывает ValueError, если статус не из белого списка."""
        if status not in VALID_STATUSES:
            allowed = ", ".join(sorted(VALID_STATUSES))
            raise ValueError(f"Недопустимый статус {status!r}. Допустимые: {allowed}")

    # ------------------------------------------------------------------
    # Свойства только для чтения
    # ------------------------------------------------------------------
    @property
    def enrollment_id(self) -> str:
        """Идентификатор заявки (только для чтения, из базового класса)."""
        return self.entity_id

    @property
    def student_email(self) -> str:
        """E-mail студента (только для чтения)."""
        return self._student_email

    @property
    def course_code(self) -> str:
        """Код курса (только для чтения)."""
        return self._course_code

    # ------------------------------------------------------------------
    # Статус с проверкой переходов
    # ------------------------------------------------------------------
    @property
    def status(self) -> str:
        """Текущий статус заявки."""
        return self._status

    @status.setter
    def status(self, new_status: str) -> None:
        """Меняет статус только по разрешённому переходу и пишет запись в журнал."""
        self._check_status(new_status)
        if new_status == self._status:
            return
        allowed = ALLOWED_TRANSITIONS[self._status]
        if new_status not in allowed:
            allowed_text = ", ".join(sorted(allowed)) or "нет (терминальный статус)"
            raise ValueError(
                f"Переход {self._status!r} -> {new_status!r} запрещён. "
                f"Разрешено: {allowed_text}"
            )
        old_status = self._status
        self._status = new_status
        self._add_record("status", old_status, new_status)

    # ------------------------------------------------------------------
    # Длительность с проверкой диапазона
    # ------------------------------------------------------------------
    @property
    def duration_hours(self) -> float:
        """Текущая длительность обучения в часах."""
        return self._duration_hours

    @duration_hours.setter
    def duration_hours(self, value: float) -> None:
        """Меняет длительность, проверяя диапазон, и пишет запись в журнал."""
        hours = self._check_duration(value)
        if hours == self._duration_hours:
            return
        old_hours = self._duration_hours
        self._duration_hours = hours
        self._add_record("duration_hours", old_hours, hours)

    def to_dict(self) -> dict[str, Any]:
        """Представление заявки словарём — удобно для отчётов и тестов."""
        return {
            "enrollment_id": self.enrollment_id,
            "student_email": self.student_email,
            "course_code": self.course_code,
            "duration_hours": self.duration_hours,
            "status": self.status,
        }
