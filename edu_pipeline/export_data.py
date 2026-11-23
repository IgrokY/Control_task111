"""Этап 5. Экспорт агрегатов в JSON и XML и безопасная обработка внешних ответов.

Один SQL-агрегат приводится к внутренней модели — списку словарей, — а затем
выгружается в два формата:

* report.json — для системы, которая принимает JSON;
* report.xml  — для системы, которая принимает XML.

Оба файла читаются обратно и приводятся к той же внутренней модели, поэтому
эквивалентность проверяется сравнением, а не «на глаз».

Отдельная задача — ответ внешней системы. Он может оказаться пустым, битым
JSON или HTML-страницей ошибки. Поэтому текст проверяется ДО json.loads:
пустой ответ и разметка отсекаются, обязательные поля проверяются явно.

Запуск:  python export_data.py   (после create_db.py и etl_import.py)
"""

import json
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "edu.db"
DATA_DIR = BASE_DIR / "data" / "final"
JSON_PATH = BASE_DIR / "report.json"
XML_PATH = BASE_DIR / "report.xml"
EXTERNAL_ERROR = DATA_DIR / "api_response_error.html"

REPORT_NAME = "enrollments_by_course_status"
PAID_STATUSES = ("enrolled", "completed")
REQUIRED_EXTERNAL_FIELDS = ("status", "rows_received")
NUMERIC_FIELDS = {"enrollments": int, "hours": float, "revenue": int}

AGGREGATE_SQL = """
    SELECT c.course_code,
           e.status,
           COUNT(*)                AS enrollments,
           ROUND(SUM(e.duration_hours), 1) AS hours,
           SUM(CASE WHEN e.status IN (?, ?) THEN c.price_rub ELSE 0 END) AS revenue
    FROM enrollments e
    JOIN courses c ON c.course_code = e.course_code
    GROUP BY c.course_code, e.status
    ORDER BY c.course_code, e.status
"""


def load_internal(db_path: Path = DB_PATH) -> list[dict]:
    """Возвращает внутреннюю модель: агрегат по парам «курс + статус»."""
    if not db_path.exists():
        raise FileNotFoundError(
            f"Нет файла {db_path.name}. Сначала выполните etl_import.py"
        )
    connection = sqlite3.connect(db_path)
    try:
        cursor = connection.execute(AGGREGATE_SQL, PAID_STATUSES)
        columns = [description[0] for description in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        connection.close()


def export_json(rows: list[dict], path: Path = JSON_PATH) -> None:
    """Пишет report.json в UTF-8 без экранирования кириллицы."""
    payload = {"report": REPORT_NAME, "rows": rows}
    with path.open("w", encoding="utf-8") as target:
        json.dump(payload, target, ensure_ascii=False, indent=2)


def export_xml(rows: list[dict], path: Path = XML_PATH) -> None:
    """Пишет report.xml с объявлением кодировки и отступами."""
    root = ET.Element("report", name=REPORT_NAME)
    for row in rows:
        node = ET.SubElement(root, "row")
        for key, value in row.items():
            ET.SubElement(node, key).text = str(value)
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def read_json(path: Path = JSON_PATH) -> list[dict]:
    """Читает report.json и возвращает список строк."""
    with path.open(encoding="utf-8") as source:
        return json.load(source)["rows"]


def read_xml(path: Path = XML_PATH) -> list[dict]:
    """Читает report.xml и приводит текст обратно к числам.

    XML не хранит типы: всё, что записано, читается строкой. Поэтому
    числовые поля восстанавливаются по словарю NUMERIC_FIELDS.
    """
    root = ET.parse(path).getroot()
    rows = []
    for node in root.findall("row"):
        row = {}
        for child in node:
            converter = NUMERIC_FIELDS.get(child.tag, str)
            row[child.tag] = converter(child.text)
        rows.append(row)
    return rows


def safe_parse_external(text: str) -> dict:
    """Разбирает ответ внешней системы, не доверяя ему.

    Возвращает словарь одного из двух видов:
    * {"status": "ok", "data": {...}} — ответ пригоден к работе;
    * {"status": "error", "error": "код", ...} — ответ отклонён с причиной.

    Проверки «пусто» и «HTML» выполняются до json.loads: json.loads на HTML
    выдал бы невнятную ошибку разбора, а нам нужна понятная причина.
    """
    if not text or not text.strip():
        return {"status": "error", "error": "empty_response"}

    stripped = text.lstrip()
    if stripped.startswith("<"):
        return {
            "status": "error",
            "error": "html_response",
            "preview": stripped[:80].replace("\n", " "),
        }

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return {"status": "error", "error": "invalid_json", "detail": str(exc)}

    if not isinstance(data, dict):
        return {"status": "error", "error": "unexpected_type",
                "detail": type(data).__name__}

    for field in REQUIRED_EXTERNAL_FIELDS:
        if field not in data:
            return {"status": "error", "error": "missing_field", "field": field}

    return {"status": "ok", "data": data}


def read_external_file(path: Path = EXTERNAL_ERROR) -> str:
    """Читает пример внешнего ответа в UTF-8 (файл с BOM)."""
    return path.read_text(encoding="utf-8-sig")


def describe_result(title: str, result: dict) -> str:
    """Короткая строка для печати результата проверки внешнего ответа."""
    if result["status"] == "ok":
        return f"{title}: принято {result['data']}"
    detail = result.get("field") or result.get("detail") or result.get("preview") or ""
    return f"{title}: отклонено ({result['error']}) {detail}"


def main() -> None:
    """Выгружает агрегат, проверяет обратимость и разбирает внешние ответы."""
    internal = load_internal()
    export_json(internal)
    export_xml(internal)

    from_json = read_json()
    from_xml = read_xml()

    print(f"Строк во внутренней модели: {len(internal)}")
    print(f"report.json прочитан обратно: {len(from_json)} строк")
    print(f"report.xml  прочитан обратно: {len(from_xml)} строк")
    print(f"JSON совпадает с моделью:    {from_json == internal}")
    print(f"XML  совпадает с моделью:    {from_xml == internal}")
    print(f"JSON и XML эквивалентны:     {from_json == from_xml}")

    total_revenue = sum(row["revenue"] for row in internal)
    total_hours = sum(row["hours"] for row in internal)
    print(f"Контроль: выручка {total_revenue} руб., часы {total_hours:g}")

    assert from_json == internal == from_xml, "Выгрузки не совпали с моделью"
    assert total_revenue == 332_000, "Выручка в агрегате не совпала"

    print("\nПроверка внешних ответов (до json.loads):")
    cases = [
        ("валидный JSON", '{"status": "ok", "rows_received": 20}'),
        ("пустой ответ", ""),
        ("HTML из файла", read_external_file()),
        ("нет обязательного поля", '{"status": "ok"}'),
        ("битый JSON", '{"status": '),
        ("JSON-массив", '[1, 2, 3]'),
    ]
    for title, text in cases:
        result = safe_parse_external(text)
        print(" ", describe_result(title, result))
        if title != "валидный JSON":
            assert result["status"] == "error", f"{title}: ошибка не обнаружена"

    print(f"\nJSON: {JSON_PATH.name}, XML: {XML_PATH.name}")


if __name__ == "__main__":
    main()
