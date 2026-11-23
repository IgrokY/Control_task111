"""Валидация и нормализация входных данных платформы «НОРД-Класс».

Модуль используется ETL-конвейером (Этап 5) и тестами (Этап 7).
Все проверки построены на re.fullmatch и именованных группах, поэтому
регулярное выражение обязано покрыть строку целиком, а не только её начало.
"""

import re
import unicodedata
from datetime import datetime
from typing import Any

ENROLLMENT_ID_RE = re.compile(
    r"^(?P<prefix>EDU)-(?P<period>\d{6})-(?P<sequence>\d{4})$"
)
EMAIL_RE = re.compile(
    r"^(?P<local>[A-Za-z0-9._%+-]+)@"
    r"(?P<domain>[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*)"
    r"\.(?P<tld>[A-Za-z]{2,})$"
)
COURSE_CODE_RE = re.compile(r"^(?P<subject>[A-Z]{2})-(?P<level>\d{3})$")
DATE_RE = re.compile(r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})$")
QUOTED_RE = re.compile(r"(?P<quote>[\"'])\s*(?P<body>.*?)\s*(?P=quote)")
QUOTED_FRAGMENT_RE = re.compile(r'("[^"]*")')

VALID_STATUSES = {"new", "on_review", "enrolled", "completed", "cancelled"}
VALID_FORMATS = {"online", "offline"}
MIN_DURATION = 1.0
MAX_DURATION = 500.0
REQUIRED_FIELDS = (
    "enrollment_id",
    "student_email",
    "course_code",
    "status",
    "created_date",
    "duration_hours",
    "format",
)

REASON_MESSAGES = {
    "invalid_enrollment_id": "идентификатор не соответствует шаблону EDU-ГГГГММ-9999",
    "invalid_email": "e-mail не соответствует формату",
    "invalid_course_code": "код курса не соответствует шаблону AA-999",
    "unknown_student": "e-mail отсутствует в справочнике студентов",
    "unknown_course": "код курса отсутствует в справочнике курсов",
    "invalid_status": "недопустимый статус заявки",
    "invalid_date": "дата должна существовать и иметь формат ГГГГ-ММ-ДД",
    "invalid_duration": "длительность должна быть числом от 1 до 500 часов",
    "invalid_format": "формат должен быть online или offline",
    "period_date_mismatch": "период идентификатора не совпадает с датой создания",
    "duplicate_enrollment_id": "идентификатор заявки уже встречался в пакете",
    "missing_field": "отсутствует обязательное поле",
    "malformed_row": "число полей не совпадает с заголовком (неэкранированная запятая)",
}


def clean_text(value: Any) -> str:
    """Убирает краевые пробелы и приводит текст Unicode к форме NFC."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFC", str(value))
    return text.replace("\u00a0", " ").replace("\ufeff", "").strip()


def normalize_email(value: Any) -> str:
    """Приводит e-mail к нижнему регистру и убирает пробелы."""
    return clean_text(value).lower()


def normalize_status(value: Any) -> str:
    """Приводит статус к нижнему регистру."""
    return clean_text(value).lower()


def normalize_format(value: Any) -> str:
    """Приводит формат обучения к нижнему регистру."""
    return clean_text(value).lower()


def normalize_course_code(value: Any) -> str:
    """Приводит код курса к верхнему регистру."""
    return clean_text(value).upper()


def normalize_spaces(line: str) -> str:
    """Схлопывает любые последовательности пробельных символов в один пробел."""
    return re.sub(r"\s+", " ", line).strip()


def normalize_quotes(line: str) -> str:
    """Заменяет парные кавычки на двойные и убирает пробелы внутри них.

    Обратная ссылка (?P=quote) гарантирует, что открывающая и закрывающая
    кавычки относятся к одному типу. Незакрытая кавычка не совпадает
    с шаблоном и остаётся без изменений.
    """
    return QUOTED_RE.sub(lambda m: f'"{m.group("body")}"', line)


def has_unbalanced_quotes(line: str) -> bool:
    """Проверяет, что число открывающих и закрывающих кавычек каждого типа чётно."""
    return any(line.count(quote) % 2 for quote in ('"', "'"))


def _normalize_separator_segment(segment: str) -> str:
    """Убирает повторные разделители и лишние пробелы вокруг них."""
    segment = re.sub(r"([,;|])(?:\s*\1)+", r"\1", segment)
    segment = re.sub(r"\s*([,;|])\s*", r"\1 ", segment)
    return segment


def _apply_outside_quotes(line: str, func) -> str:
    """Применяет функцию только к фрагментам вне двойных кавычек."""
    parts = QUOTED_FRAGMENT_RE.split(line)
    return "".join(
        func(part) if index % 2 == 0 else part
        for index, part in enumerate(parts)
    )


def normalize_separators(line: str) -> str:
    """Нормализует разделители, не затрагивая их внутри кавычек."""
    return _apply_outside_quotes(line, _normalize_separator_segment)


def normalize_audit_line(line: str) -> str:
    """Нормализует строку журнала операторов.

    Порядок правил важен:
    1) Unicode NFC и замена неразрывного пробела;
    2) кавычки — пока границы фрагментов ещё видны;
    3) пробелы — чтобы разделители стояли рядом с соседними токенами;
    4) разделители — только вне кавычек, чтобы не испортить,
       например, адрес "pavlova@example,com";
    5) финальное схлопывание пробелов и strip.
    """
    if not line:
        return ""
    text = unicodedata.normalize("NFC", line).replace("\u00a0", " ")
    text = text.replace("\ufeff", "").strip()
    text = normalize_quotes(text)
    text = normalize_spaces(text)
    text = normalize_separators(text)
    text = normalize_spaces(text)
    return text.strip()


def validate_enrollment_id(value: str) -> list[str]:
    """Проверяет идентификатор заявки по шаблону с именованными группами."""
    if not ENROLLMENT_ID_RE.fullmatch(value or ""):
        return ["invalid_enrollment_id"]
    return []


def validate_email(value: str) -> list[str]:
    """Проверяет e-mail; домен и TLD выделены в именованные группы."""
    if not EMAIL_RE.fullmatch(value or ""):
        return ["invalid_email"]
    return []


def validate_course_code(value: str) -> list[str]:
    """Проверяет код курса вида PY-100."""
    if not COURSE_CODE_RE.fullmatch(value or ""):
        return ["invalid_course_code"]
    return []


def validate_date(value: str) -> list[str]:
    """Проверяет дату: шаблон ГГГГ-ММ-ДД и существование даты в календаре."""
    match = DATE_RE.fullmatch(value or "")
    if not match:
        return ["invalid_date"]
    try:
        datetime(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )
    except ValueError:
        return ["invalid_date"]
    return []


def validate_duration(value: Any) -> list[str]:
    """Проверяет, что длительность — число в допустимом диапазоне."""
    try:
        hours = float(value)
    except (TypeError, ValueError):
        return ["invalid_duration"]
    if not MIN_DURATION <= hours <= MAX_DURATION:
        return ["invalid_duration"]
    return []


def validate_status(value: str) -> list[str]:
    """Проверяет статус заявки по белому списку."""
    if value not in VALID_STATUSES:
        return ["invalid_status"]
    return []


def validate_format(value: str) -> list[str]:
    """Проверяет формат обучения по белому списку."""
    if value not in VALID_FORMATS:
        return ["invalid_format"]
    return []


def _append_unique(errors: list[str], new_errors: list[str]) -> None:
    """Добавляет коды ошибок без дублей, сохраняя порядок обнаружения."""
    for error in new_errors:
        if error not in errors:
            errors.append(error)


def normalize_enrollment(
    raw: dict,
    known_students: set[str] | None = None,
    known_courses: set[str] | None = None,
) -> tuple[dict, list[str]]:
    """Нормализует строку заявки и возвращает копию строки со списком ошибок.

    Исходный словарь не изменяется. Проверяются все поля сразу, чтобы
    отправитель получил полную картину, а не только первую ошибку.
    """
    row = {key: clean_text(value) for key, value in raw.items()}
    errors: list[str] = []

    for field in REQUIRED_FIELDS:
        if not row.get(field):
            errors.append(f"missing_field:{field}")

    enrollment_id = row.get("enrollment_id", "")
    _append_unique(errors, validate_enrollment_id(enrollment_id))

    email = normalize_email(row.get("student_email", ""))
    row["student_email"] = email
    if email:
        _append_unique(errors, validate_email(email))
        if known_students is not None and email not in known_students:
            errors.append("unknown_student")

    course_code = normalize_course_code(row.get("course_code", ""))
    row["course_code"] = course_code
    if course_code:
        _append_unique(errors, validate_course_code(course_code))
        if known_courses is not None and course_code not in known_courses:
            errors.append("unknown_course")

    status = normalize_status(row.get("status", ""))
    row["status"] = status
    _append_unique(errors, validate_status(status))

    study_format = normalize_format(row.get("format", ""))
    row["format"] = study_format
    _append_unique(errors, validate_format(study_format))

    created_date = row.get("created_date", "")
    _append_unique(errors, validate_date(created_date))

    _append_unique(errors, validate_duration(row.get("duration_hours", "")))
    if "invalid_duration" not in errors:
        row["duration_hours"] = float(row["duration_hours"])

    id_match = ENROLLMENT_ID_RE.fullmatch(enrollment_id)
    date_match = DATE_RE.fullmatch(created_date)
    if id_match and date_match and "invalid_date" not in errors:
        period = id_match.group("period")
        expected_period = f"{date_match.group('year')}{date_match.group('month')}"
        if period != expected_period:
            errors.append("period_date_mismatch")

    return row, errors


def validate_enrollment(
    raw: dict,
    known_students: set[str] | None = None,
    known_courses: set[str] | None = None,
) -> list[str]:
    """Возвращает только список причин отказа для строки заявки."""
    _, errors = normalize_enrollment(raw, known_students, known_courses)
    return errors


def describe_reasons(errors: list[str]) -> str:
    """Превращает коды ошибок в понятную человеку строку."""
    messages = []
    for error in errors:
        if error.startswith("missing_field:"):
            field = error.split(":", 1)[1]
            messages.append(f"{REASON_MESSAGES['missing_field']}: {field}")
        else:
            messages.append(REASON_MESSAGES.get(error, error))
    return "; ".join(messages)
