"""Этап 7. Диагностика кодировок CP1251 и UTF-8.

Дано два файла с одним и тем же списком имён:

* names_utf8.txt   — эталон в UTF-8 (с BOM);
* names_cp1251.txt — тот же список в CP1251 (без BOM).

Скрипт не «угадывает» кодировку, а проверяет гипотезы по байтам:
пробует декодировать каждый файл как UTF-8 и как CP1251, фиксирует BOM,
сравнивает результат с эталоном и складывает всё в diagnostic_table.csv.

Дополнительно показывается, как возникает «кракозябра» (mojibake) и как
её исправить обратным преобразованием.

Запуск:  python unicode_diagnostics.py
"""

import csv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "final"
CP1251_FILE = DATA_DIR / "names_cp1251.txt"
UTF8_FILE = DATA_DIR / "names_utf8.txt"
TABLE = BASE_DIR / "diagnostic_table.csv"

TABLE_COLUMNS = [
    "file", "size_bytes", "has_bom", "utf8_decodes", "cp1251_decodes",
    "chosen_encoding", "equals_reference", "note",
]


def read_bytes(path: Path) -> bytes:
    """Читает файл в бинарном виде: кодировку определяем по байтам."""
    return path.read_bytes()


def detect_bom(data: bytes) -> str:
    """Возвращает имя BOM или пустую строку, если BOM нет."""
    if data.startswith(b"\xef\xbb\xbf"):
        return "UTF-8 BOM"
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "UTF-16 BOM"
    return ""


def try_decode(data: bytes, encoding: str) -> tuple[bool, str]:
    """Пробует декодировать байты; возвращает (успех, текст или сообщение ошибки)."""
    try:
        return True, data.decode(encoding)
    except UnicodeDecodeError as exc:
        return False, f"{exc.reason} на позиции {exc.start}"


def choose_encoding(data: bytes) -> tuple[str, bool]:
    """Выбирает кодировку по факту успешного декодирования.

    BOM — самый надёжный признак UTF-8, поэтому он проверяется первым.
    CP1251 проверяется вторым: он «всеядный» и декодирует почти любые байты,
    поэтому одного успеха CP1251 недостаточно — нужна проверка с эталоном.
    """
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig", True
    utf8_ok, _ = try_decode(data, "utf-8")
    if utf8_ok:
        return "utf-8", True
    cp_ok, _ = try_decode(data, "cp1251")
    return ("cp1251", cp_ok)


def normalize_text(text: str) -> str:
    """Убирает BOM и приводит переводы строк к \\n для честного сравнения."""
    return text.lstrip("\ufeff").replace("\r\n", "\n").strip()


def reference_text() -> str:
    """Читает эталон в UTF-8 и нормализует переводы строк."""
    return normalize_text(UTF8_FILE.read_bytes().decode("utf-8-sig"))


def diagnose_file(path: Path, reference: str) -> dict:
    """Собирает строку диагностики для одного файла."""
    data = read_bytes(path)
    utf8_ok, utf8_text = try_decode(data, "utf-8")
    cp_ok, cp_text = try_decode(data, "cp1251")
    encoding, _ = choose_encoding(data)
    try:
        decoded = data.decode(encoding)
    except UnicodeDecodeError:
        decoded = ""

    return {
        "file": path.name,
        "size_bytes": len(data),
        "has_bom": detect_bom(data) or "нет",
        "utf8_decodes": "да" if utf8_ok else f"нет ({utf8_text})",
        "cp1251_decodes": "да" if cp_ok else f"нет ({cp_text})",
        "chosen_encoding": encoding,
        "equals_reference": normalize_text(decoded) == reference,
        "note": "эталон" if path == UTF8_FILE else "кандидат на сверку",
    }


def mojibake_demo() -> list[dict]:
    """Показывает типичную ошибку «прочитали CP1251 как Latin-1»."""
    data = read_bytes(CP1251_FILE)
    reference = reference_text()

    _, wrong_text = try_decode(data, "latin-1")
    broken = normalize_text(wrong_text)
    fixed = broken.encode("latin-1").decode("cp1251")
    _, utf8_error = try_decode(data, "utf-8")

    print("\nДемонстрация mojibake")
    print("  CP1251 как UTF-8:  ", "ошибка —", utf8_error)
    print("  CP1251 как Latin-1:", broken.splitlines()[0])
    print("  обратное исправление:", fixed.splitlines()[0])
    print("  совпало с эталоном:", normalize_text(fixed) == reference)
    assert normalize_text(fixed) == reference, "Обратное исправление mojibake не сработало"

    return [
        {
            "file": "names_cp1251.txt (прочитан как latin-1)",
            "size_bytes": len(data),
            "has_bom": detect_bom(data) or "нет",
            "utf8_decodes": "нет",
            "cp1251_decodes": "да",
            "chosen_encoding": "latin-1 (ошибочно)",
            "equals_reference": broken == reference,
            "note": "mojibake; обратное latin-1 -> cp1251 восстанавливает текст",
        },
        {
            "file": "names_cp1251.txt (прочитан как utf-8)",
            "size_bytes": len(data),
            "has_bom": detect_bom(data) or "нет",
            "utf8_decodes": f"нет ({utf8_error})",
            "cp1251_decodes": "да",
            "chosen_encoding": "utf-8 (ошибочно)",
            "equals_reference": False,
            "note": "UnicodeDecodeError — файл не читается совсем",
        },
    ]


def bom_demo() -> dict:
    """Показывает ловушку BOM: чтение как utf-8 (не utf-8-sig) оставляет U+FEFF.

    Сравнение «в лоб» с эталоном даёт False, хотя имена те же: невидимый символ
    в начале строки портит и сравнение, и заголовок CSV.
    """
    data = read_bytes(UTF8_FILE)
    raw_text = data.decode("utf-8")  # намеренно не utf-8-sig
    return {
        "file": "names_utf8.txt (прочитан как utf-8, не utf-8-sig)",
        "size_bytes": len(data),
        "has_bom": detect_bom(data) or "нет",
        "utf8_decodes": "да",
        "cp1251_decodes": "нет",
        "chosen_encoding": "utf-8 (BOM остался в тексте)",
        "equals_reference": raw_text == reference_text(),
        "note": f"первый символ {raw_text[0]!r}: невидимый BOM ломает сравнение",
    }


def write_table(rows: list[dict], path: Path = TABLE) -> None:
    """Пишет диагностическую таблицу в CSV."""
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=TABLE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def print_table(rows: list[dict]) -> None:
    """Печатает таблицу в консоль в сокращённом виде."""
    print(f"\n{'файл':<52}{'байт':>5} {'BOM':<11}{'кодировка':<30}совпало")
    for row in rows:
        print(f"{row['file']:<52}{row['size_bytes']:>5} {row['has_bom']:<11}"
              f"{row['chosen_encoding']:<30}{row['equals_reference']}")


def main() -> None:
    """Диагностирует оба файла, показывает mojibake и пишет таблицу."""
    reference = reference_text()
    rows = [
        diagnose_file(UTF8_FILE, reference),
        diagnose_file(CP1251_FILE, reference),
    ]
    rows.extend(mojibake_demo())
    rows.append(bom_demo())

    print_table(rows)
    write_table(rows)

    cp_row = rows[1]
    print("\nВывод")
    print(f"  names_cp1251.txt декодируется как CP1251: {cp_row['cp1251_decodes']}")
    print(f"  после декодирования совпадает с эталоном: {cp_row['equals_reference']}")
    print(f"  BOM есть только в names_utf8.txt: {rows[0]['has_bom']}")
    print(f"\nТаблица сохранена: {TABLE.name}")

    assert rows[0]["equals_reference"] is True, "UTF-8 эталон прочитан неверно"
    assert cp_row["equals_reference"] is True, "CP1251 не совпал с эталоном"
    assert cp_row["has_bom"] == "нет", "В CP1251 файле не должно быть BOM"
    assert rows[2]["equals_reference"] is False, "Ошибочное чтение не должно совпадать"
    assert rows[3]["equals_reference"] is False, "Чтение CP1251 как UTF-8 должно ломаться"
    assert rows[4]["equals_reference"] is False, "BOM в тексте должен ломать сравнение"


if __name__ == "__main__":
    main()
