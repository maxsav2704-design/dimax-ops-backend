from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import re
import uuid
import zipfile
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - handled at runtime with validation error
    PdfReader = None
try:
    from pdf2image import convert_from_bytes
except Exception:  # pragma: no cover - optional runtime dependency
    convert_from_bytes = None
try:
    import pytesseract
except Exception:  # pragma: no cover - optional runtime dependency
    pytesseract = None

from app.modules.door_types.infrastructure.models import DoorTypeORM
from app.modules.projects.application.use_cases import ProjectUseCases
from app.modules.projects.infrastructure.models import ProjectImportRunORM
from app.shared.domain.errors import NotFound


def _normalize_token(value: str) -> str:
    text = value.strip().casefold()
    chars: list[str] = []
    for ch in text:
        if ch.isalnum():
            chars.append(ch)
            continue
        if ch in {" ", "-", "_", "/", "\\", "."}:
            chars.append("_")
    token = "".join(chars)
    token = re.sub(r"_+", "_", token).strip("_")
    return token


def _alias_set(*values: str) -> set[str]:
    return {_normalize_token(v) for v in values if v and _normalize_token(v)}


def _clean_text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _first_value(row: dict[str, str], aliases: set[str]) -> str | None:
    for key, value in row.items():
        if _normalize_token(str(key)) in aliases:
            return _clean_text(value)
    return None


HOUSE_KEYS = {
    "house",
    "building",
    "house_number",
    "house_no",
    "building_no",
}
FLOOR_KEYS = {"floor", "floor_label", "level"}
APARTMENT_KEYS = {
    "apartment",
    "apartment_number",
    "apt",
    "unit",
    "flat",
}
LOCATION_KEYS = {
    "location",
    "location_code",
    "zone",
    "zone_type",
    "area",
    "placement",
}
MARKING_KEYS = {
    "marking",
    "door_marking",
    "mark",
    "label",
    "designation",
}
DOOR_TYPE_CODE_KEYS = {
    "door_type",
    "door_type_code",
    "type_code",
    "model",
}
DOOR_TYPE_ID_KEYS = {"door_type_id"}
QTY_KEYS = {"qty", "quantity", "count", "amount"}
PRICE_KEYS = {"price", "our_price", "cost"}
UNIT_LABEL_KEYS = {"unit_label", "position_label"}
ORDER_NUMBER_KEYS = {"order_number", "order_no", "order_id", "po_number"}


LOCATION_VALUE_MAP = {
    "dira": "dira",
    "mamad": "mamad",
    "madregot": "madregot",
    "mahzan": "mahzan",
    "machsan": "mahzan",
    "mahsan": "mahzan",
    "hederashpa": "heder_ashpa",
    "lobbymaalit": "lobby_maalit",
}


def _normalize_location_code(value: str | None) -> str | None:
    raw = _clean_text(value)
    if raw is None:
        return None
    raw_low = raw.lower()
    ru_map = {
        "дира": "dira",
        "мамад": "mamad",
        "мадрегот": "madregot",
        "махсан": "mahzan",
        "махзан": "mahzan",
        "хедерашпа": "heder_ashpa",
        "хедэр ашпа": "heder_ashpa",
        "лобимаалит": "lobby_maalit",
        "лоби маалит": "lobby_maalit",
    }
    ru_key = re.sub(r"[^0-9a-zа-я]+", "", raw_low)
    if ru_key in ru_map:
        return ru_map[ru_key]
    token = _normalize_token(raw)
    return LOCATION_VALUE_MAP.get(token, token)


# Override alias dictionaries and location normalization with multi-language support
HOUSE_KEYS = _alias_set(
    "\u05d1\u05e0\u05d9\u05d9\u05df",
    "house",
    "building",
    "house_number",
    "house_no",
    "building_no",
    "дом",
    "номер дома",
    "корпус",
    "здание",
    "בית",
    "מספר בית",
    "בניין",
)
FLOOR_KEYS = _alias_set(
    "\u05e7\u05d5\u05de\u05d4",
    "floor",
    "floor_label",
    "level",
    "этаж",
    "уровень",
    "קומה",
    "מפלס",
)
APARTMENT_KEYS = _alias_set(
    "\u05d3\u05d9\u05e8\u05d4",
    "apartment",
    "apartment_number",
    "apt",
    "unit",
    "flat",
    "квартира",
    "номер квартиры",
    "юнит",
    "דירה",
    "מספר דירה",
    "יחידה",
)
LOCATION_KEYS = _alias_set(
    "location",
    "location_code",
    "zone",
    "zone_type",
    "area",
    "placement",
    "локация",
    "зона",
    "тип помещения",
    "назначение",
    "מיקום",
    "אזור",
    "סוג מיקום",
)
MARKING_KEYS = _alias_set(
    "\u05d3\u05d2\u05dd \u05db\u05e0\u05e3",
    "\u05d3\u05d2\u05dd-\u05db\u05e0\u05e3",
    "marking",
    "door_marking",
    "mark",
    "label",
    "designation",
    "маркировка",
    "метка",
    "обозначение",
    "סימון",
    "תוית",
)
DOOR_TYPE_CODE_KEYS = _alias_set(
    "door_type",
    "door_type_code",
    "type_code",
    "model",
    "тип двери",
    "код типа",
    "מודל",
    "סוג דלת",
)
DOOR_TYPE_ID_KEYS = _alias_set("door_type_id")
QTY_KEYS = _alias_set("qty", "quantity", "count", "amount", "количество", "כמות")
PRICE_KEYS = _alias_set("price", "our_price", "cost", "цена", "стоимость", "מחיר")
UNIT_LABEL_KEYS = _alias_set(
    "unit_label",
    "position_label",
    "позиция",
    "метка позиции",
    "позиция двери",
    "מזהה",
    "מזהה דלת",
)

ORDER_NUMBER_KEYS = _alias_set(
    "\u05de\u05e1\u05e4\u05e8 \u05d4\u05d6\u05de\u05e0\u05d4",
    "\u05de\u05e1\u05e4\u05e8-\u05d4\u05d6\u05de\u05e0\u05d4",
    "order_number",
    "order_no",
    "order_id",
    "po_number",
    "purchase_order",
)

LOCATION_ALIAS_MAP = {
    _normalize_token("dira"): "dira",
    _normalize_token("apartment"): "dira",
    _normalize_token("flat"): "dira",
    _normalize_token("unit"): "dira",
    _normalize_token("дира"): "dira",
    _normalize_token("квартира"): "dira",
    _normalize_token("דירה"): "dira",
    _normalize_token("mamad"): "mamad",
    _normalize_token("safe room"): "mamad",
    _normalize_token("мамад"): "mamad",
    _normalize_token("ממד"): "mamad",
    _normalize_token("madregot"): "madregot",
    _normalize_token("stairs"): "madregot",
    _normalize_token("staircase"): "madregot",
    _normalize_token("лестница"): "madregot",
    _normalize_token("лестничная"): "madregot",
    _normalize_token("מדרגות"): "madregot",
    _normalize_token("mahzan"): "mahzan",
    _normalize_token("machsan"): "mahzan",
    _normalize_token("mahsan"): "mahzan",
    _normalize_token("storage"): "mahzan",
    _normalize_token("кладовка"): "mahzan",
    _normalize_token("склад"): "mahzan",
    _normalize_token("махсан"): "mahzan",
    _normalize_token("מחסן"): "mahzan",
    _normalize_token("heder ashpa"): "heder_ashpa",
    _normalize_token("trash room"): "heder_ashpa",
    _normalize_token("garbage"): "heder_ashpa",
    _normalize_token("мусорка"): "heder_ashpa",
    _normalize_token("хедер ашпа"): "heder_ashpa",
    _normalize_token("חדר אשפה"): "heder_ashpa",
    _normalize_token("lobby maalit"): "lobby_maalit",
    _normalize_token("elevator lobby"): "lobby_maalit",
    _normalize_token("лобби лифта"): "lobby_maalit",
    _normalize_token("לובי מעלית"): "lobby_maalit",
}


def _normalize_location_code(
    value: str | None,
    *,
    aliases_only: bool = False,
) -> str | None:
    raw = _clean_text(value)
    if raw is None:
        return None
    token = _normalize_token(raw)
    if not token:
        return None
    mapped = LOCATION_ALIAS_MAP.get(token)
    if mapped is not None:
        return mapped
    if aliases_only:
        return None
    token_ascii = re.sub(r"[^0-9a-z_]+", "", token)
    if token_ascii:
        return token_ascii[:80]
    return None


def _normalize_marking(value: str | None) -> str | None:
    raw = _clean_text(value)
    if raw is None:
        return None
    return raw[:120]


def _normalize_optional_value(value: str | None, *, max_len: int) -> str | None:
    raw = _clean_text(value)
    if raw is None:
        return None
    return raw[:max_len]


def _decode_text(content: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1251", "windows-1255", "latin-1"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="ignore")


def _parse_delimited_rows(content: bytes, delimiter: str | None) -> list[dict[str, str]]:
    text = _decode_text(content)
    sniff_delimiter = delimiter
    if sniff_delimiter is None:
        sample = text[:2048]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            sniff_delimiter = dialect.delimiter
        except Exception:
            sniff_delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=sniff_delimiter)
    return [dict(row) for row in reader]


def _parse_json_rows(content: bytes) -> list[dict[str, str]]:
    data = json.loads(_decode_text(content))
    if isinstance(data, dict):
        data = data.get("rows", [])
    if not isinstance(data, list):
        raise HTTPException(status_code=422, detail="json must contain list of rows")
    rows: list[dict[str, str]] = []
    for item in data:
        if isinstance(item, dict):
            rows.append({str(k): "" if v is None else str(v) for k, v in item.items()})
    return rows


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _parse_xml_rows(content: bytes) -> list[dict[str, str]]:
    root = ET.fromstring(content)
    rows: list[dict[str, str]] = []
    for node in list(root):
        row: dict[str, str] = {}
        for child in list(node):
            row[_strip_ns(child.tag)] = (child.text or "").strip()
        if row:
            rows.append(row)
    return rows


def _xlsx_col_to_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha()).upper()
    if not letters:
        return 0
    result = 0
    for ch in letters:
        result = result * 26 + (ord(ch) - ord("A") + 1)
    return result


def _parse_xlsx_rows(content: bytes) -> list[dict[str, str]]:
    ns_main = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    ns_pkg = {"p": "http://schemas.openxmlformats.org/package/2006/relationships"}

    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            shared_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in shared_root.findall(".//x:si", ns_main):
                parts = [t.text or "" for t in si.findall(".//x:t", ns_main)]
                shared_strings.append("".join(parts))

        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        first_sheet = workbook.find(".//x:sheets/x:sheet", ns_main)
        if first_sheet is None:
            return []
        rid = first_sheet.attrib.get(
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        )
        if not rid:
            return []

        rels_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        sheet_target = None
        for rel in rels_root.findall("p:Relationship", ns_pkg):
            if rel.attrib.get("Id") == rid:
                sheet_target = rel.attrib.get("Target")
                break
        if not sheet_target:
            return []
        if not sheet_target.startswith("xl/"):
            sheet_target = f"xl/{sheet_target.lstrip('/')}"

        sheet = ET.fromstring(zf.read(sheet_target))
        header_by_col: dict[int, str] = {}
        rows: list[dict[str, str]] = []
        for row_node in sheet.findall(".//x:sheetData/x:row", ns_main):
            values_by_col: dict[int, str] = {}
            for cell in row_node.findall("x:c", ns_main):
                col_idx = _xlsx_col_to_index(cell.attrib.get("r", ""))
                cell_type = cell.attrib.get("t")
                value = ""
                if cell_type == "inlineStr":
                    txt = cell.find(".//x:t", ns_main)
                    value = txt.text if txt is not None and txt.text is not None else ""
                else:
                    raw = cell.find("x:v", ns_main)
                    if raw is not None and raw.text is not None:
                        if cell_type == "s":
                            try:
                                value = shared_strings[int(raw.text)]
                            except Exception:
                                value = raw.text
                        else:
                            value = raw.text
                values_by_col[col_idx] = value

            if not header_by_col:
                for col_idx, value in values_by_col.items():
                    header_by_col[col_idx] = value.strip()
                continue

            row: dict[str, str] = {}
            for col_idx, header in header_by_col.items():
                if header:
                    row[header] = values_by_col.get(col_idx, "").strip()
            if any(v for v in row.values()):
                rows.append(row)
        return rows


def _split_tabular_line(
    line: str,
    *,
    delimiter: str | None = None,
    preferred_separator: str | None = None,
) -> tuple[list[str], str | None]:
    text = line.strip()
    if not text:
        return [], None

    separators: list[str | None] = []
    if delimiter:
        separators.append(delimiter)
    if preferred_separator:
        separators.append(preferred_separator)
    separators.extend(["\t", "|", ";", ","])

    for sep in separators:
        if sep is None:
            continue
        if sep in text:
            cells = [cell.strip() for cell in text.split(sep)]
            if len(cells) >= 2:
                return cells, sep

    cells = [cell.strip() for cell in re.split(r"\s{2,}", text) if cell.strip()]
    if len(cells) >= 2:
        return cells, "__space__"

    return [text], None


VALID_MAPPING_PROFILES = {
    "auto_v1",
    "factory_he_v1",
    "factory_ru_v1",
    "generic_en_v1",
}


def _normalize_mapping_profile(value: str | None) -> str:
    profile = (value or "auto_v1").strip().lower()
    if profile not in VALID_MAPPING_PROFILES:
        raise HTTPException(status_code=422, detail=f"unknown mapping_profile: {value}")
    return profile


def _profile_preferred_delimiter(profile: str) -> str | None:
    if profile in {"factory_he_v1", "factory_ru_v1"}:
        return ";"
    if profile == "generic_en_v1":
        return ","
    return None


def _default_strict_required_fields(profile: str) -> bool:
    return profile in {"factory_he_v1", "factory_ru_v1"}


def _build_alias_groups(profile: str) -> dict[str, set[str]]:
    # Profiles currently share the same alias vocabulary but differ in delimiter preference.
    # Keeping explicit function allows gradual profile-specific evolution without API break.
    del profile
    return {
        "house": HOUSE_KEYS,
        "floor": FLOOR_KEYS,
        "apartment": APARTMENT_KEYS,
        "marking": MARKING_KEYS,
        "location": LOCATION_KEYS,
        "door_type_code": DOOR_TYPE_CODE_KEYS,
        "door_type_id": DOOR_TYPE_ID_KEYS,
        "qty": QTY_KEYS,
        "price": PRICE_KEYS,
        "unit_label": UNIT_LABEL_KEYS,
        "order_number": ORDER_NUMBER_KEYS,
    }


def _factory_profile_door_type_code_fallback(
    *,
    profile_code: str,
    door_marking: str | None,
    source: dict[str, str],
    alias_groups: dict[str, set[str]],
) -> str | None:
    if profile_code not in {"factory_he_v1", "factory_ru_v1"}:
        return None
    if _first_value(source, alias_groups["door_type_code"]):
        return None
    if _first_value(source, alias_groups["door_type_id"]):
        return None
    return door_marking


def _detect_header_categories(
    cells: list[str],
    alias_groups: dict[str, set[str]],
) -> set[str]:
    categories: set[str] = set()
    for cell in cells:
        token = _normalize_token(cell)
        if not token:
            continue
        for name, aliases in alias_groups.items():
            if token in aliases:
                categories.add(name)
    return categories


def _rows_from_tabular_lines(
    lines: list[str],
    delimiter: str | None,
    *,
    alias_groups: dict[str, set[str]],
) -> list[dict[str, str]]:
    if not lines:
        return []

    rows: list[dict[str, str]] = []
    headers: list[str] | None = None
    header_separator: str | None = None

    for line in lines:
        cells, used_separator = _split_tabular_line(
            line,
            delimiter=delimiter,
            preferred_separator=header_separator,
        )
        if not cells:
            continue

        categories = _detect_header_categories(cells, alias_groups)
        if len(categories) >= 2:
            headers = cells
            header_separator = used_separator
            continue

        if headers is None:
            # Fallback: parse data-only tabular lines as house/floor/apartment/marking.
            if len(cells) >= 4:
                row = {
                    "house": cells[0],
                    "floor": cells[1],
                    "apartment": cells[2],
                    "marking": cells[3],
                }
                if len(cells) >= 5:
                    row["door_type"] = cells[4]
                if len(cells) >= 6:
                    row["qty"] = cells[5]
                rows.append(row)
            continue

        if len(cells) < len(headers):
            cells = cells + [""] * (len(headers) - len(cells))
        elif len(cells) > len(headers):
            cells = cells[: len(headers) - 1] + [" ".join(cells[len(headers) - 1 :])]

        row = {headers[idx]: cells[idx] for idx in range(len(headers))}
        if any(_clean_text(value) for value in row.values()):
            rows.append(row)

    return rows


def _extract_pdf_text_lines(content: bytes) -> list[str]:
    if PdfReader is None:
        raise HTTPException(status_code=422, detail="pdf parsing is unavailable on this server")

    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(status_code=422, detail="invalid pdf file") from e

    lines: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        for line in text.splitlines():
            clean = line.strip()
            if clean:
                lines.append(clean)
    return lines


def _ocr_pdf_lines(content: bytes) -> list[str]:
    if convert_from_bytes is None or pytesseract is None:
        return []

    try:
        images = convert_from_bytes(content, dpi=250)
    except Exception:
        return []

    lines: list[str] = []
    for image in images:
        page_text = ""
        for lang in ("heb+eng+rus", "eng"):
            try:
                page_text = pytesseract.image_to_string(
                    image,
                    lang=lang,
                    config="--oem 1 --psm 6",
                )
                if page_text.strip():
                    break
            except Exception:
                continue
        if not page_text.strip():
            continue

        for line in page_text.splitlines():
            clean = line.strip()
            if clean:
                lines.append(clean)

    return lines


def _parse_pdf_rows(
    content: bytes,
    delimiter: str | None,
    *,
    alias_groups: dict[str, set[str]],
) -> list[dict[str, str]]:
    lines = _extract_pdf_text_lines(content)
    rows = _rows_from_tabular_lines(lines, delimiter, alias_groups=alias_groups)
    if rows:
        return rows

    # Fallback for image-only/scanned PDFs.
    ocr_lines = _ocr_pdf_lines(content)
    if not ocr_lines:
        return rows
    rows = _rows_from_tabular_lines(ocr_lines, delimiter, alias_groups=alias_groups)
    return rows


def _parse_rows_by_filename(
    *,
    filename: str,
    content: bytes,
    delimiter: str | None,
    alias_groups: dict[str, set[str]],
) -> list[dict[str, str]]:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in {"csv", "txt", "tsv"}:
        return _parse_delimited_rows(content, delimiter if ext != "tsv" else "\t")
    if ext == "json":
        return _parse_json_rows(content)
    if ext == "xml":
        return _parse_xml_rows(content)
    if ext == "xlsx":
        return _parse_xlsx_rows(content)
    if ext == "pdf":
        return _parse_pdf_rows(content, delimiter, alias_groups=alias_groups)
    raise HTTPException(status_code=422, detail=f"unsupported file format: .{ext or 'unknown'}")


REQUIRED_IMPORT_FIELDS: list[tuple[str, str, set[str]]] = [
    ("house_number", "בניין", HOUSE_KEYS),
    ("floor_label", "קומה", FLOOR_KEYS),
    ("apartment_number", "דירה", APARTMENT_KEYS),
    ("door_marking", "דגם כנף", MARKING_KEYS),
]


REQUIRED_IMPORT_FIELDS.append(
    ("order_number", "\u05de\u05e1\u05e4\u05e8 \u05d4\u05d6\u05de\u05e0\u05d4", ORDER_NUMBER_KEYS)
)


def _collect_columns_diagnostics(
    parsed_rows: list[dict[str, str]],
    *,
    alias_groups: dict[str, set[str]],
    mapping_profile: str,
    strict_required_fields: bool,
) -> dict:
    source_columns: list[str] = []
    seen_columns: set[str] = set()
    for row in parsed_rows:
        for key in row.keys():
            label = str(key).strip()
            if not label:
                continue
            if label in seen_columns:
                continue
            seen_columns.add(label)
            source_columns.append(label)

    recognized_columns: list[str] = []
    unmapped_columns: list[str] = []
    for column in source_columns:
        token = _normalize_token(column)
        if any(token in aliases for aliases in alias_groups.values()):
            recognized_columns.append(column)
        else:
            unmapped_columns.append(column)

    required_fields: list[dict] = []
    missing_required_fields: list[str] = []
    for field_key, display_name, aliases in REQUIRED_IMPORT_FIELDS:
        matched = [col for col in source_columns if _normalize_token(col) in aliases]
        if not matched:
            missing_required_fields.append(field_key)
        required_fields.append(
            {
                "field_key": field_key,
                "display_name": display_name,
                "found": bool(matched),
                "matched_columns": matched,
            }
        )

    return {
        "required_fields": required_fields,
        "recognized_columns": recognized_columns,
        "unmapped_columns": unmapped_columns,
        "mapping_profile": mapping_profile,
        "strict_required_fields": strict_required_fields,
        "missing_required_fields": missing_required_fields,
    }


def _collect_data_summary(
    *,
    parsed_rows: list[dict[str, str]],
    prepared_rows: list[dict],
    errors: list[dict],
    skipped_duplicates_in_payload: int,
) -> dict:
    order_numbers = {
        str(x).strip()
        for x in (row.get("order_number") for row in prepared_rows)
        if str(x or "").strip()
    }
    house_numbers = {
        str(x).strip()
        for x in (row.get("house_number") for row in prepared_rows)
        if str(x or "").strip()
    }
    floor_labels = {
        str(x).strip()
        for x in (row.get("floor_label") for row in prepared_rows)
        if str(x or "").strip()
    }
    apartment_numbers = {
        str(x).strip()
        for x in (row.get("apartment_number") for row in prepared_rows)
        if str(x or "").strip()
    }
    location_codes = {
        str(x).strip()
        for x in (row.get("location_code") for row in prepared_rows)
        if str(x or "").strip()
    }
    door_markings = {
        str(x).strip()
        for x in (row.get("door_marking") for row in prepared_rows)
        if str(x or "").strip()
    }

    return {
        "source_rows": len(parsed_rows),
        "prepared_rows": len(prepared_rows),
        "rows_with_errors": len(errors),
        "duplicate_rows_skipped": skipped_duplicates_in_payload,
        "unique_order_numbers": len(order_numbers),
        "unique_houses": len(house_numbers),
        "unique_floors": len(floor_labels),
        "unique_apartments": len(apartment_numbers),
        "unique_locations": len(location_codes),
        "unique_markings": len(door_markings),
    }


def _collect_preview_groups(
    prepared_rows: list[dict],
    *,
    limit: int = 80,
) -> list[dict]:
    grouped: dict[tuple[str, str, str, str, str], dict] = {}
    for row in prepared_rows:
        order_number = _clean_text(row.get("order_number"))
        house_number = _clean_text(row.get("house_number"))
        floor_label = _clean_text(row.get("floor_label"))
        apartment_number = _clean_text(row.get("apartment_number"))
        door_marking = _clean_text(row.get("door_marking"))
        location_code = _clean_text(row.get("location_code"))
        key = (
            order_number or "",
            house_number or "",
            floor_label or "",
            apartment_number or "",
            door_marking or "",
        )
        bucket = grouped.get(key)
        if bucket is None:
            bucket = {
                "order_number": order_number,
                "house_number": house_number,
                "floor_label": floor_label,
                "apartment_number": apartment_number,
                "door_marking": door_marking,
                "door_count": 0,
                "location_codes": set(),
            }
            grouped[key] = bucket
        bucket["door_count"] += 1
        if location_code:
            bucket["location_codes"].add(location_code)

    rows = sorted(
        grouped.values(),
        key=lambda item: (
            str(item.get("order_number") or "").casefold(),
            str(item.get("house_number") or "").casefold(),
            str(item.get("floor_label") or "").casefold(),
            str(item.get("apartment_number") or "").casefold(),
            str(item.get("door_marking") or "").casefold(),
        ),
    )
    preview: list[dict] = []
    for item in rows[:limit]:
        preview.append(
            {
                "order_number": item.get("order_number"),
                "house_number": item.get("house_number"),
                "floor_label": item.get("floor_label"),
                "apartment_number": item.get("apartment_number"),
                "door_marking": item.get("door_marking"),
                "door_count": int(item.get("door_count") or 0),
                "location_codes": sorted(item.get("location_codes") or []),
            }
        )
    return preview


def _build_unit_label(
    *,
    raw_unit_label: str | None,
    house_number: str | None,
    floor_label: str | None,
    apartment_number: str | None,
    location_code: str | None,
    door_marking: str | None,
    quantity_index: int,
    quantity: int,
    row_number: int,
) -> str:
    if raw_unit_label:
        base = raw_unit_label
    else:
        parts = [house_number, floor_label, apartment_number, location_code, door_marking]
        parts = [x for x in parts if x]
        base = "-".join(parts) if parts else f"ROW-{row_number}"
    if quantity > 1:
        base = f"{base}/{quantity_index + 1}"
    return base[:120]


def _required_row_missing_fields(
    *,
    order_number: str | None,
    house_number: str | None,
    floor_label: str | None,
    apartment_number: str | None,
    door_marking: str | None,
) -> list[str]:
    missing: list[str] = []
    if order_number is None:
        missing.append("order_number")
    if house_number is None:
        missing.append("house_number")
    if floor_label is None:
        missing.append("floor_label")
    if apartment_number is None:
        missing.append("apartment_number")
    if door_marking is None:
        missing.append("door_marking")
    return missing


def _parse_quantity(value: str | None) -> int:
    if value is None:
        return 1
    text = value.strip()
    if not text:
        return 1
    try:
        qty = int(float(text.replace(",", ".")))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"invalid quantity: {value}") from e
    if qty < 1 or qty > 1000:
        raise HTTPException(status_code=422, detail=f"quantity out of range: {value}")
    return qty


def _parse_price(value: str | None, default_price: Decimal) -> Decimal:
    if value is None or not value.strip():
        return default_price
    try:
        price = Decimal(value.replace(",", ".").strip())
    except InvalidOperation as e:
        raise HTTPException(status_code=422, detail=f"invalid price: {value}") from e
    if price < 0:
        raise HTTPException(status_code=422, detail=f"price must be >= 0: {value}")
    return price


def _import_fingerprint(
    *,
    content: bytes,
    filename: str,
    default_door_type_id: uuid.UUID | None,
    default_our_price: Decimal,
    delimiter: str | None,
    mapping_profile: str,
    strict_required_fields: bool,
    create_missing_door_types: bool,
    analyze_only: bool,
) -> str:
    metadata = {
        "filename": filename,
        "default_door_type_id": str(default_door_type_id) if default_door_type_id else None,
        "default_our_price": str(default_our_price),
        "delimiter": delimiter,
        "mapping_profile": mapping_profile,
        "strict_required_fields": strict_required_fields,
        "create_missing_door_types": create_missing_door_types,
        "analyze_only": analyze_only,
    }
    digest = hashlib.sha256()
    digest.update(content)
    digest.update(
        json.dumps(metadata, sort_keys=True, ensure_ascii=False).encode("utf-8")
    )
    return digest.hexdigest()


def _serialize_prepared_rows(prepared_rows: list[dict]) -> list[dict]:
    serialized: list[dict] = []
    for row in prepared_rows:
        serialized.append(
            {
                "door_type_id": str(row.get("door_type_id") or ""),
                "unit_label": str(row.get("unit_label") or ""),
                "our_price": str(row.get("our_price") or "0"),
                "order_number": _clean_text(row.get("order_number")),
                "house_number": _clean_text(row.get("house_number")),
                "floor_label": _clean_text(row.get("floor_label")),
                "apartment_number": _clean_text(row.get("apartment_number")),
                "location_code": _clean_text(row.get("location_code")),
                "door_marking": _clean_text(row.get("door_marking")),
            }
        )
    return serialized


def _build_persist_payload(
    *,
    result: dict,
    prepared_rows: list[dict],
    filename: str,
    mapping_profile: str,
) -> dict:
    payload = dict(result)
    payload["_retry"] = {
        "filename": filename,
        "mapping_profile": mapping_profile,
        "prepared_rows": _serialize_prepared_rows(prepared_rows),
    }
    return payload


def _public_result_payload(payload: dict) -> dict:
    return {
        key: value
        for key, value in payload.items()
        if not str(key).startswith("_")
    }


def _save_import_run(
    uow,
    *,
    company_id: uuid.UUID,
    project_id: uuid.UUID,
    fingerprint: str,
    import_mode: str,
    source_filename: str,
    mapping_profile: str,
    result_payload: dict,
) -> None:
    run = ProjectImportRunORM(
        company_id=company_id,
        project_id=project_id,
        fingerprint=fingerprint,
        import_mode=import_mode,
        source_filename=source_filename,
        mapping_profile=mapping_profile,
        result_payload=result_payload,
    )
    uow.project_import_runs.save(run)
    uow.session.flush()


class ProjectFileImportService:
    @staticmethod
    def import_project_doors_from_file(
        uow,
        *,
        company_id: uuid.UUID,
        project_id: uuid.UUID,
        filename: str,
        content_base64: str,
        default_door_type_id: uuid.UUID | None,
        default_our_price: Decimal,
        delimiter: str | None,
        mapping_profile: str,
        strict_required_fields: bool | None,
        create_missing_door_types: bool,
        analyze_only: bool,
    ) -> dict:
        project = uow.projects.get(company_id=company_id, project_id=project_id)
        if project is None:
            raise NotFound("Project not found", details={"project_id": str(project_id)})

        try:
            content = base64.b64decode(content_base64, validate=True)
        except Exception as e:
            raise HTTPException(status_code=422, detail="invalid base64 content") from e

        profile_code = _normalize_mapping_profile(mapping_profile)
        strict_required = (
            _default_strict_required_fields(profile_code)
            if strict_required_fields is None
            else bool(strict_required_fields)
        )
        alias_groups = _build_alias_groups(profile_code)
        effective_delimiter = delimiter or _profile_preferred_delimiter(profile_code)
        import_mode = "analyze" if analyze_only else "import"
        fingerprint = _import_fingerprint(
            content=content,
            filename=filename,
            default_door_type_id=default_door_type_id,
            default_our_price=default_our_price,
            delimiter=effective_delimiter,
            mapping_profile=profile_code,
            strict_required_fields=strict_required,
            create_missing_door_types=create_missing_door_types,
            analyze_only=analyze_only,
        )

        existing_run = uow.project_import_runs.get_by_fingerprint(
            company_id=company_id,
            project_id=project_id,
            fingerprint=fingerprint,
            import_mode=import_mode,
        )
        if existing_run is not None and isinstance(existing_run.result_payload, dict):
            cached = _public_result_payload(existing_run.result_payload)
            cached["idempotency_hit"] = True
            return cached

        parsed_rows = _parse_rows_by_filename(
            filename=filename,
            content=content,
            delimiter=effective_delimiter,
            alias_groups=alias_groups,
        )
        if not parsed_rows:
            raise HTTPException(status_code=422, detail="no rows found in file")
        diagnostics = _collect_columns_diagnostics(
            parsed_rows,
            alias_groups=alias_groups,
            mapping_profile=profile_code,
            strict_required_fields=strict_required,
        )
        missing_required_columns = list(diagnostics.get("missing_required_fields") or [])
        if strict_required and missing_required_columns:
            raise HTTPException(
                status_code=422,
                detail=(
                    "missing required columns: "
                    + ", ".join(missing_required_columns)
                ),
            )

        prepared_rows: list[dict] = []
        errors: list[dict] = []
        payload_keys_seen: set[tuple[str, uuid.UUID]] = set()
        skipped_duplicates_in_payload = 0

        for idx, source in enumerate(parsed_rows, start=1):
            try:
                raw_unit_label = _first_value(source, alias_groups["unit_label"])
                order_number = _normalize_optional_value(
                    _first_value(source, alias_groups["order_number"]),
                    max_len=80,
                )
                house_number = _normalize_optional_value(
                    _first_value(source, alias_groups["house"]),
                    max_len=40,
                )
                floor_label = _normalize_optional_value(
                    _first_value(source, alias_groups["floor"]),
                    max_len=40,
                )
                apartment_number = _normalize_optional_value(
                    _first_value(source, alias_groups["apartment"]),
                    max_len=40,
                )
                location_raw = _first_value(source, alias_groups["location"])
                marking_raw = _first_value(source, alias_groups["marking"])
                location_code = _normalize_location_code(location_raw)
                if location_code is None:
                    location_code = _normalize_location_code(
                        marking_raw,
                        aliases_only=True,
                    )
                door_marking = _normalize_marking(marking_raw)
                if strict_required:
                    missing_required_values = _required_row_missing_fields(
                        order_number=order_number,
                        house_number=house_number,
                        floor_label=floor_label,
                        apartment_number=apartment_number,
                        door_marking=door_marking,
                    )
                    if missing_required_values:
                        raise HTTPException(
                            status_code=422,
                            detail=(
                                "missing required row values: "
                                + ", ".join(missing_required_values)
                            ),
                        )

                qty = _parse_quantity(_first_value(source, alias_groups["qty"]))
                price = _parse_price(
                    _first_value(source, alias_groups["price"]),
                    default_our_price,
                )

                door_type_id_raw = _first_value(source, alias_groups["door_type_id"])
                door_type_code = _first_value(source, alias_groups["door_type_code"])
                if not door_type_code:
                    door_type_code = _factory_profile_door_type_code_fallback(
                        profile_code=profile_code,
                        door_marking=door_marking,
                        source=source,
                        alias_groups=alias_groups,
                    )
                door_type_id: uuid.UUID | None = None

                if door_type_id_raw:
                    door_type_id = uuid.UUID(door_type_id_raw)
                elif door_type_code:
                    code = re.sub(r"[^a-z0-9_-]+", "-", door_type_code.strip().lower())
                    code = code.strip("-")[:64]
                    if len(code) < 2:
                        raise HTTPException(status_code=422, detail="door_type_code is invalid")

                    dt = uow.door_types.get_by_code(
                        company_id=company_id,
                        code=code,
                        include_deleted=True,
                    )
                    if dt is None and create_missing_door_types:
                        dt = DoorTypeORM(
                            company_id=company_id,
                            code=code,
                            name=door_type_code.strip()[:256],
                            is_active=True,
                            deleted_at=None,
                        )
                        uow.door_types.save(dt)
                        uow.session.flush()
                    if dt is not None:
                        door_type_id = dt.id

                if door_type_id is None:
                    door_type_id = default_door_type_id
                if door_type_id is None:
                    raise HTTPException(
                        status_code=422,
                        detail="door_type_id or door_type_code is required",
                    )

                for q_idx in range(qty):
                    unit_label = _build_unit_label(
                        raw_unit_label=raw_unit_label,
                        house_number=house_number,
                        floor_label=floor_label,
                        apartment_number=apartment_number,
                        location_code=location_code,
                        door_marking=door_marking,
                        quantity_index=q_idx,
                        quantity=qty,
                        row_number=idx,
                    )
                    key = (unit_label, door_type_id)
                    if key in payload_keys_seen:
                        skipped_duplicates_in_payload += 1
                        continue
                    payload_keys_seen.add(key)
                    prepared_rows.append(
                        {
                            "door_type_id": door_type_id,
                            "unit_label": unit_label,
                            "our_price": price,
                            "order_number": order_number,
                            "house_number": house_number,
                            "floor_label": floor_label,
                            "apartment_number": apartment_number,
                            "location_code": location_code,
                            "door_marking": door_marking,
                        }
                    )
            except Exception as e:
                message = str(e.detail) if isinstance(e, HTTPException) else str(e)
                errors.append({"row": idx, "message": message[:500]})

        if not prepared_rows:
            if errors:
                preview = "; ".join(
                    f"row {x.get('row')}: {x.get('message')}" for x in errors[:3]
                )
                raise HTTPException(
                    status_code=422,
                    detail=f"no valid rows to import ({preview})",
                )
            raise HTTPException(status_code=422, detail="no valid rows to import")

        diagnostics["data_summary"] = _collect_data_summary(
            parsed_rows=parsed_rows,
            prepared_rows=prepared_rows,
            errors=errors,
            skipped_duplicates_in_payload=skipped_duplicates_in_payload,
        )
        diagnostics["preview_groups"] = _collect_preview_groups(prepared_rows)

        if analyze_only:
            # Use nested transaction so all domain checks run but no rows are persisted.
            with uow.session.begin_nested() as preview_tx:
                would_import, skipped_existing = ProjectUseCases.import_doors(
                    uow,
                    company_id=company_id,
                    project_id=project_id,
                    rows=prepared_rows,
                    skip_existing=True,
                )
                preview_tx.rollback()
            would_skip = skipped_existing + skipped_duplicates_in_payload
            result = {
                "parsed_rows": len(parsed_rows),
                "prepared_rows": len(prepared_rows),
                "imported": 0,
                "skipped": would_skip,
                "errors": errors[:500],
                "diagnostics": diagnostics,
                "mode": "analyze",
                "would_import": would_import,
                "would_skip": would_skip,
                "idempotency_hit": False,
            }
            try:
                _save_import_run(
                    uow,
                    company_id=company_id,
                    project_id=project_id,
                    fingerprint=fingerprint,
                    import_mode="analyze",
                    source_filename=filename,
                    mapping_profile=profile_code,
                    result_payload=_build_persist_payload(
                        result=result,
                        prepared_rows=prepared_rows,
                        filename=filename,
                        mapping_profile=profile_code,
                    ),
                )
            except IntegrityError:
                uow.session.rollback()
                existing_run = uow.project_import_runs.get_by_fingerprint(
                    company_id=company_id,
                    project_id=project_id,
                    fingerprint=fingerprint,
                    import_mode="analyze",
                )
                if existing_run is not None and isinstance(existing_run.result_payload, dict):
                    cached = _public_result_payload(existing_run.result_payload)
                    cached["idempotency_hit"] = True
                    return cached
            return result

        imported, skipped_existing = ProjectUseCases.import_doors(
            uow,
            company_id=company_id,
            project_id=project_id,
            rows=prepared_rows,
            skip_existing=True,
        )
        would_skip = skipped_existing + skipped_duplicates_in_payload
        result = {
            "parsed_rows": len(parsed_rows),
            "prepared_rows": len(prepared_rows),
            "imported": imported,
            "skipped": would_skip,
            "errors": errors[:500],
            "diagnostics": diagnostics,
            "mode": "import",
            "would_import": imported,
            "would_skip": would_skip,
            "idempotency_hit": False,
        }
        try:
            _save_import_run(
                uow,
                company_id=company_id,
                project_id=project_id,
                fingerprint=fingerprint,
                import_mode="import",
                source_filename=filename,
                mapping_profile=profile_code,
                result_payload=_build_persist_payload(
                    result=result,
                    prepared_rows=prepared_rows,
                    filename=filename,
                    mapping_profile=profile_code,
                ),
            )
        except IntegrityError:
            uow.session.rollback()
            existing_run = uow.project_import_runs.get_by_fingerprint(
                company_id=company_id,
                project_id=project_id,
                fingerprint=fingerprint,
                import_mode="import",
            )
            if existing_run is not None and isinstance(existing_run.result_payload, dict):
                cached = _public_result_payload(existing_run.result_payload)
                cached["idempotency_hit"] = True
                return cached
        return result
