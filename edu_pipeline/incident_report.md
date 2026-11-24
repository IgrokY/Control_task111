# Протокол разбора дефектов модуля отчётности

## 0. Исходные условия

* Модуль: `data/final/buggy_report.py` (передан другим разработчиком).
* Файл **не изменялся**: это требование задания.
* Исправленная версия: `fixed_report.py`.
* Регрессионные тесты: `test_report.py`.
* Цикл для каждого дефекта: **воспроизведение → причина → исправление → тест**.

Сообщение автора модуля: «на части реальных данных возникают странные ошибки».
«Странность» объясняется тем, что модуль писался и проверялся на «удобных»
данных. Ошибки проявляются на пустых выборках, на данных других систем с `NULL`
в `duration_hours` и на нестроковых идентификаторах из внешнего файла.

Важное уточнение: в нашей `edu.db` колонка `duration_hours` объявлена
`NOT NULL CHECK (duration_hours > 0)`, поэтому `NULL` в ней появиться не может.
Модуль отчётности при этом читает любую таблицу `enrollments` (выгрузка из
старой системы, результат `LEFT JOIN`), а там `NULL` допустим. Поэтому каждый
дефект ниже воспроизведён либо на реальной `edu.db`, либо на специально
созданной базе без ограничений — это указано явно.

## 1. Дефект №1. `average_duration` падает на NULL

### Воспроизведение

```python
rows = [("EDU-001", "enrolled", 36.0),
        ("EDU-002", "completed", 48.0),
        ("EDU-003", "on_review", None)]
buggy_report.average_duration(rows)
```

Фактический результат:

```
TypeError: unsupported operand type(s) for +: 'float' and 'NoneType'
```

Ожидаемый результат: `42.0` — среднее по двум заполненным строкам.

То же самое при чтении из базы без ограничений `NOT NULL` (таблица
`enrollments` из старой системы, созданная без ограничений):

```
buggy_report.load_enrollments(...)  ->  [('EDU-1', 'enrolled', 36.0), ('EDU-2', 'completed', 48.0), ('EDU-3', 'on_review', None)]
buggy_report.average_duration(rows) ->  TypeError: unsupported operand type(s) for +: 'float' and 'NoneType'
```

### Причина

`total = total + hours` не проверяет `hours is None`. В схеме `edu.db`
`NULL` запрещён, но модуль не привязан к ней: в других источниках заявка может
быть записана до согласования длительности. На «чистых» данных `edu.db` ошибка
не видна, поэтому её и назвали «странной».

### Исправление

```python
hours = []
for _, _, value in rows:
    if value is None:
        continue
    number = float(value)
    if number >= 0:
        hours.append(number)
return sum(hours) / len(hours) if hours else 0.0
```

Нечисловые значения тоже пропускаются: отчёт не должен падать из-за одной строки.

### Регрессионный тест

`test_report.TestFixedReport.test_average_skips_null` — ожидает `42.0`.
`test_report.TestBuggyReportReproduction.test_bug_null_duration_breaks_average`
подтверждает, что исходный модуль действительно падает.

## 2. Дефект №2. Деление на ноль на пустой выборке

### Воспроизведение

Воспроизведение на реальной `edu.db` (заявок со статусом `paused` в базе нет,
потому что ETL отклонил такую строку):

```python
rows = buggy_report.load_enrollments("edu.db")            # 10 строк
paused = buggy_report.find_by_status(rows, "paused")      # []
buggy_report.average_duration(paused)
```

```
ZeroDivisionError: division by zero
```

Ожидаемый результат: `0.0` — отчёт по статусу без заявок должен строиться.

### Причина

`total / len(rows)` без проверки длины. Пустая выборка — штатная ситуация:
фильтр по статусу, по которому пока нет ни одной заявки.

### Исправление

Возврат `0.0` при пустом списке `hours`.

### Регрессионный тест

`test_average_empty_returns_zero`, `test_average_all_null_returns_zero`.
Тест исходного модуля: `test_bug_empty_rows_break_average`.

## 3. Дефект №3. `top_courses` возвращает худшие курсы

### Воспроизведение

```python
rows = [("PY",), ("PY",), ("DA",), ("WD",)]
buggy_report.top_courses(rows, limit=3)
```

Фактический результат:

```
[('DA', 1), ('WD', 1), ('PY', 2)]
```

Ожидаемый результат:

```
[('PY', 2), ('DA', 1), ('WD', 1)]
```

На реальных данных `edu.db` (коды курсов всех 10 заявок, как требует docstring):

```
buggy_report.top_courses(courses, 3) -> [('QA-150', 1), ('DA-200', 2), ('WD-300', 2)]
fixed_report.top_courses(courses, 3) -> [('PY-100', 5), ('DA-200', 2), ('WD-300', 2)]
```

В «топе» исходного модуля на первом месте курс с одной заявкой, а самый
популярный курс `PY-100` (5 заявок) вообще пропал из списка.

### Причина

`sorted(counts.items(), key=lambda kv: kv[1])` сортирует по возрастанию, а
`[:limit]` берёт начало списка, то есть самые редкие курсы. Отчёт назывался
«топ», а показывал антитоп — ошибка не падает, поэтому её легко не заметить.

### Исправление

```python
ordered = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
```

Минус даёт убывание; второй ключ (код курса) делает порядок детерминированным
при равном количестве заявок.

### Регрессионный тест

`test_top_courses_is_descending`, `test_top_courses_tie_is_deterministic`.
Тест исходного модуля: `test_bug_top_courses_is_ascending`.

## 4. Дефект №4. `find_by_status` меняет список вызывающего кода

### Воспроизведение

```python
rows = [("a", "new"), ("b", "closed")]
buggy_report.find_by_status(rows, "new")
print(rows)
```

Фактический результат:

```
[('b', 'closed'), ('a', 'new')]
```

Ожидаемый результат: порядок исходного списка не изменился, а функция вернула
`[('a', 'new')]`.

### Причина

`rows.sort(...)` сортирует список **на месте**. Вызывающий код не ожидает, что
чтение отчёта переставит его данные; в отчёте это приводит к «плавающему»
порядку строк между вызовами.

### Исправление

```python
return [row for row in rows if row[1] == status]
```

Новый список, исходный не изменяется.

### Регрессионный тест

`test_find_by_status_does_not_mutate` сравнивает список до и после вызова.
Тест исходного модуля: `test_bug_find_by_status_mutates_input`.

## 5. Дефект №5. `report_line` падает на не-строке

### Воспроизведение

```python
buggy_report.report_line(None, "new")
buggy_report.report_line(12345, "new")
```

```
TypeError: can only concatenate str (not "NoneType") to str
TypeError: can only concatenate str (not "int") to str
```

### Причина

Конкатенация `"Заявка " + enrollment_id` требует строку. Идентификатор приходит
из внешнего файла; при сбое импорта там может оказаться число или `None`.

### Исправление

```python
return f"Заявка {enrollment_id} в статусе {status}"
```

f-string сам вызывает `str()` и не падает на числах и `None`.

### Регрессионный тест

`test_report_line_handles_numbers_and_none`.
Тест исходного модуля: `test_bug_report_line_fails_on_non_string`.

## 6. Дефект №6. `load_enrollments` не закрывает соединение

### Воспроизведение

```python
buggy_report.load_enrollments("edu.db")
```

Python 3.13 сообщает об утечке сам:

```
ResourceWarning: unclosed database in <sqlite3.Connection object at 0x...>
```

Каждый вызов оставляет одно незакрытое соединение. Регрессионный тест
`test_bug_load_enrollments_never_closes_connection` подтверждает, что в исходном
модуле `close()` не вызывается ни разу.

### Причина

`conn = sqlite3.connect(...)` и `return` без `close()`. При исключении в запросе
соединение остаётся открытым; на Windows файл базы может остаться заблокированным.

### Исправление

```python
connection = sqlite3.connect(db_path)
try:
    return connection.execute(...).fetchall()
finally:
    connection.close()
```

### Регрессионный тест

`test_load_closes_connection` подменяет `sqlite3.connect` мок-объектом и
проверяет, что `close()` вызван ровно один раз;
`test_load_closes_connection_on_error` проверяет то же при исключении в запросе
(именно ради этого случая нужен `try/finally`).

## 7. Итоговая таблица

| № | Дефект | Было | Стало | Тест |
|---|---|---|---|---|
| 1 | NULL в длительности | `TypeError` | строка пропускается | `test_average_skips_null` |
| 2 | Пустая выборка | `ZeroDivisionError` | `0.0` | `test_average_empty_returns_zero` |
| 3 | Топ курсов | по возрастанию | по убыванию | `test_top_courses_is_descending` |
| 4 | Мутация списка | `sort` на месте | новый список | `test_find_by_status_does_not_mutate` |
| 5 | Конкатенация | `TypeError` | f-string | `test_report_line_handles_numbers_and_none` |
| 6 | Утечка соединения | без `close` | `try/finally` | `test_load_closes_connection` |

## 8. Полный цикл на одном примере

1. **Воспроизведение.** Взять реальные строки с `NULL` из `edu.db` и вызвать
   `average_duration` — получить `TypeError`.
2. **Локализация.** Строка `total = total + hours`; источник `None` — поле
   `duration_hours` в БД.
3. **Исправление.** Пропускать `None`, обрабатывать пустой список.
4. **Регрессия.** Добавить тест на NULL и на пустой список; прогнать весь набор
   `python -m unittest -v`, убедиться, что старые тесты не сломались.
5. **Документирование.** Зафиксировать причину и решение в этом протоколе.

Такой цикл повторён для всех шести дефектов; исходный `buggy_report.py` остаётся
в `data/final/` в неизменном виде как доказательство условия задачи.
