"""Демонстрация работы класса Enrollment (Этап 6).

Сценарий показывает наследование, разрешённые и запрещённые переходы,
запись истории и защиту журнала от внешнего изменения.
Запуск:  python demo.py
"""

from enrollment import Enrollment, TrackedEntity


def show_history(enrollment: Enrollment) -> None:
    """Печатает журнал заявки по строкам."""
    for record in enrollment.history():
        print(
            f"  {record['at']}  {record['field']}: "
            f"{record['old']!r} -> {record['new']!r}"
        )


def main() -> None:
    """Проводит демонстрацию по шагам."""
    enrollment = Enrollment(
        "EDU-202610-0001", "ivanov@example.com", "PY-100", duration_hours=36
    )

    print("1. Наследование и начальное состояние")
    print("  Enrollment наследует TrackedEntity:", issubclass(Enrollment, TrackedEntity))
    print("  объект является TrackedEntity:      ", isinstance(enrollment, TrackedEntity))
    print("  идентификатор из базового класса:   ", enrollment.enrollment_id)
    print("  статус:                             ", enrollment.status)
    print("  длительность:                       ", enrollment.duration_hours)
    print("  журнал пока пуст:                   ", enrollment.history())

    print("\n2. Разрешённая цепочка переходов new -> on_review -> enrolled -> completed")
    enrollment.status = "on_review"
    enrollment.status = "enrolled"
    enrollment.status = "completed"
    print("  текущий статус:", enrollment.status)
    show_history(enrollment)

    print("\n3. Запрещённый переход из терминального статуса")
    try:
        enrollment.status = "enrolled"
    except ValueError as exc:
        print("  ожидаемая ошибка:", exc)
    print("  статус не изменился:", enrollment.status)
    print("  записей в журнале:", len(enrollment.history()))

    print("\n4. Неизвестный статус")
    try:
        enrollment.status = "deleted"
    except ValueError as exc:
        print("  ожидаемая ошибка:", exc)

    print("\n5. Повтор того же статуса не создаёт запись")
    enrollment.status = "completed"
    print("  записей в журнале:", len(enrollment.history()))

    print("\n6. Изменение длительности с проверкой диапазона")
    enrollment.duration_hours = 40
    try:
        enrollment.duration_hours = -5
    except ValueError as exc:
        print("  ожидаемая ошибка:", exc)
    print("  длительность сейчас:", enrollment.duration_hours)
    print("  последняя запись журнала:", enrollment.history()[-1])

    print("\n7. history() возвращает копию")
    copy = enrollment.history()
    copy.clear()
    copy.append({"at": "подделка", "field": "status", "old": "x", "new": "y"})
    print("  записей в настоящем журнале:", len(enrollment.history()))
    print("  первая запись не испорчена:", enrollment.history()[0]["old"])

    print("\n8. Идентификатор и e-mail нельзя заменить напрямую")
    for field in ("enrollment_id", "student_email"):
        try:
            setattr(enrollment, field, "FAKE")
        except AttributeError as exc:
            print(f"  {field}: {exc}")
    print("  значения:", enrollment.enrollment_id, enrollment.student_email)

    print("\n9. У каждой заявки свой журнал")
    other = Enrollment("EDU-202610-0002", "petrova@example.com", "DA-200", 48)
    other.status = "on_review"
    print("  записей у первой:", len(enrollment.history()))
    print("  записей у второй:", len(other.history()))

    print("\n10. Заявка словарём:")
    print(" ", enrollment.to_dict())


if __name__ == "__main__":
    main()
