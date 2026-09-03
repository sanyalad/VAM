"""
Универсальный парсер документов и изображений для извлечения данных о приборах КИП.

Поддерживает:
  - Excel-файлы (.xlsx / .xls) — детерминистический парсер для графиков ППР +
    ИИ-парсер для нестандартных таблиц
  - Word-документы (.docx)
  - Текстовые файлы (.txt, .csv)
  - Изображения (.jpg, .jpeg, .png, .bmp, .tiff) — фото сертификатов поверки
  - PDF-файлы (.pdf)

Все извлечённые приборы привязываются ТОЛЬКО к 5 допустимым цехам:
  1. Цех 6 (Картэкс, 2-й)
  2. Цех 66 (66.2, Спецсталь)
  3. Печь 10 (Ижора, цех 66.1)
  4. Цех 92 (ИСМ)
  5. Цех 47 (Спецсталь)
"""

import os
import re
import json
import math
import base64
import traceback
from datetime import datetime, date

import requests

from ssz_config import CONFIG
from inventory_db import (
    get_workshops, get_workshop_by_name, add_workshop,
    get_location_by_name, add_location, smart_upsert_device, get_locations,
    get_unassigned_location, create_inventory_import, add_inventory_import_item,
    finish_inventory_import
)


# ═══════════════════════════════════════════════════════════════════════════
#  Допустимые цехи (каноническая таблица)
# ═══════════════════════════════════════════════════════════════════════════

VALID_WORKSHOPS = [
    "Цех 6 (Картэкс, 2-й)",
    "Цех 66 (66.2, Спецсталь)",
    "Печь 10 (Ижора, цех 66.1)",
    "Цех 92 (ИСМ)",
    "Цех 47 (Спецсталь)",
]

# Паттерны для нечёткого сопоставления текста ИИ → каноническое имя цеха
# Порядок важен: сначала более специфичные (66, 66.1, 66.2), потом общие (6, 47)
_WS_PATTERNS = [
    # Печь 10 / Ижора / 66.1 / 34/66-2 — ПЕРВЫЙ, т.к. 66.1 и 34/66 специфичнее чем 66
    (r"(?:печь\s*(?:№?\s*)?10|ижора|66[\.\-]1|34/66|цех\s*(?:№?\s*)?34)", "Печь 10 (Ижора, цех 66.1)"),
    # Цех 66 / 66.2 / 66-2 / Спецсталь (не 66.1!)
    (r"(?:цех\s*(?:№?\s*)?66|66[\.\-]2|спецсталь)", "Цех 66 (66.2, Спецсталь)"),
    # Цех 92 / ИСМ
    (r"(?:цех\s*(?:№?\s*)?92|исм|и\.?\s*с\.?\s*м)", "Цех 92 (ИСМ)"),
    # Цех 47
    (r"(?:цех\s*(?:№?\s*)?47)", "Цех 47 (Спецсталь)"),
    # Цех 6 / Картэкс / 2-й — ПОСЛЕДНИЙ, чтобы не перехватить 66
    (r"(?:цех\s*(?:№?\s*)?6(?![\d\.])|картэкс|карт[её]кс|(?:^|\s)2[\-\s]?(?:й|ой)(?:\s|$))", "Цех 6 (Картэкс, 2-й)"),
]


def _match_workshop(raw_name: str) -> str | None:
    """Сопоставить произвольный текст с каноническим именем цеха."""
    if not raw_name or not raw_name.strip():
        return None
    s = raw_name.strip().lower()

    # Точное совпадение
    for ws in VALID_WORKSHOPS:
        if ws.lower() == s or ws.lower() in s or s in ws.lower():
            return ws

    # Паттерновое сопоставление
    for pattern, ws_name in _WS_PATTERNS:
        if re.search(pattern, s, re.IGNORECASE):
            return ws_name

    # Частичное совпадение по числу — проверяем от более длинных к коротким
    nums_found = re.findall(r"\d+", s)
    num_mapping = {
        "92": "Цех 92 (ИСМ)",
        "66": "Цех 66 (66.2, Спецсталь)",
        "47": "Цех 47 (Спецсталь)",
        "10": "Печь 10 (Ижора, цех 66.1)",
        "6": "Цех 6 (Картэкс, 2-й)",
        "2": "Цех 6 (Картэкс, 2-й)",
    }
    # Check longest matches first
    for num in sorted(nums_found, key=lambda x: -len(x)):
        if num in num_mapping:
            return num_mapping[num]

    return None


# ═══════════════════════════════════════════════════════════════════════════
#  Извлечение текста / изображений из файлов
# ═══════════════════════════════════════════════════════════════════════════

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'}
EXCEL_EXTENSIONS = {'.xlsx', '.xls'}
DOCUMENT_EXTENSIONS = {'.docx', '.doc', '.txt', '.csv', '.pdf'}


def _extract_text_from_file(filepath: str) -> str:
    """Извлечь текст из документа (Excel, Word, PDF, TXT)."""
    ext = os.path.splitext(filepath)[1].lower()
    text = ""

    try:
        if ext in EXCEL_EXTENSIONS:
            import pandas as pd
            sheets = pd.read_excel(filepath, sheet_name=None, header=None)
            parts = []
            for sheet_name, df in sheets.items():
                parts.append(f"\n=== Лист: {sheet_name} ===\n")
                parts.append(df.to_string(index=False, na_rep=""))
            text = "\n".join(parts)

        elif ext == '.docx':
            from docx import Document
            doc = Document(filepath)
            text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])

        elif ext == '.pdf':
            try:
                import fitz  # PyMuPDF
                doc = fitz.open(filepath)
                pages = []
                for page in doc:
                    pages.append(page.get_text())
                text = "\n".join(pages)
                doc.close()
            except ImportError:
                # Fallback: попробовать pdfplumber
                try:
                    import pdfplumber
                    with pdfplumber.open(filepath) as pdf:
                        pages = [p.extract_text() or "" for p in pdf.pages]
                    text = "\n".join(pages)
                except ImportError:
                    return ""

        elif ext in ('.txt', '.csv'):
            encodings = ['utf-8', 'cp1251', 'latin-1']
            for enc in encodings:
                try:
                    with open(filepath, 'r', encoding=enc) as f:
                        text = f.read()
                    break
                except (UnicodeDecodeError, UnicodeError):
                    continue

    except Exception as e:
        print(f"[ai_parser] Ошибка чтения файла {filepath}: {e}")

    return text


def _encode_image_base64(filepath: str) -> str:
    """Закодировать изображение в base64 для vision API."""
    with open(filepath, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')


def _get_image_mime(filepath: str) -> str:
    """Определить MIME-тип изображения."""
    ext = os.path.splitext(filepath)[1].lower()
    mime_map = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png', '.bmp': 'image/bmp',
        '.tiff': 'image/tiff', '.tif': 'image/tiff',
        '.webp': 'image/webp',
    }
    return mime_map.get(ext, 'image/jpeg')


# ═══════════════════════════════════════════════════════════════════════════
#  ИИ-парсер (OpenRouter API)
# ═══════════════════════════════════════════════════════════════════════════

_AI_SYSTEM_PROMPT = """\
Ты — специалист по извлечению данных о контрольно-измерительных приборах (КИП).
Твоя задача — из предоставленного документа или фотографии сертификата извлечь ВСЕ упоминания приборов.

ВАЖНО: Существуют только 5 допустимых цехов/площадок. Определи, к какому цеху относится прибор:
  1. "Цех 6 (Картэкс, 2-й)" — он же цех №6, Картэкс, 2-й цех
  2. "Цех 66 (66.2, Спецсталь)" — он же цех №66, 66-2, 66.2, Спецсталь
  3. "Печь 10 (Ижора, цех 66.1)" — он же Ижора, цех 66.1, цех 34/66-2, печь 10
  4. "Цех 92 (ИСМ)" — он же цех №92, ИСМ
  5. "Цех 47 (Спецсталь)" — он же цех №47

Если цех не удаётся определить — используй "Не определён".

Для каждого прибора извлеки:
  - workshop: одно из 5 значений выше (или "Не определён")
  - location: место установки (Печь 1, УТИР, Кладовка, и т.д.) или "Общий"
  - location_type: "furnace" (печь), "utir", "storage" (кладовка/резерв), "general" (прочее)
  - device_name: название прибора / средства измерения (Потенциометр, Дифманометр, Термопара и т.д.)
  - model: тип, модель (КСП-4 м.008, и т.д.)
  - serial_number: заводской номер (если есть)
  - calibration_date: дата следующей поверки в формате YYYY-MM-DD (если есть, иначе null)
  - position: что измеряет (температура, давление, расход газа и т.д.)

Верни результат строго как JSON-массив. Никакого текста вокруг — только JSON.
Пример:
[
  {
    "workshop": "Цех 47 (Спецсталь)",
    "location": "Печь 3",
    "location_type": "furnace",
    "device_name": "Потенциометр",
    "model": "КСП 4 м.008",
    "serial_number": "Б0307715",
    "calibration_date": "2026-01-13",
    "position": "Измерение температуры"
  }
]

Извлеки ВСЕ приборы, которые найдёшь в документе. Не пропускай ни одного.
Если это сертификат/свидетельство о поверке — извлеки данные из него: название прибора, модель, заводской номер, дату поверки (когда действует ДО или дату следующей поверки).
"""


def _call_ai_text(text: str, api_key: str, base_url: str, model: str, user_comment: str = "") -> tuple[list[dict], str]:
    """Вызвать ИИ для текстового документа."""
    comment_text = f"КОММЕНТАРИЙ ПОЛЬЗОВАТЕЛЯ К ЭТОМУ ДОКУМЕНТУ: {user_comment}\nУчитывай его при извлечении данных (особенно цех).\n\n" if user_comment else ""
    user_content = f"{comment_text}Вот текст документа. Извлеки все приборы:\n\n{text[:50000]}"

    return _call_ai_api(
        messages=[
            {"role": "system", "content": _AI_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        api_key=api_key, base_url=base_url, model=model
    )


def _call_ai_vision(image_path: str | list[str], api_key: str, base_url: str, model: str, user_comment: str = "") -> tuple[list[dict], str]:
    """Вызвать ИИ для изображения (фото сертификата)."""
    paths = image_path if isinstance(image_path, list) else [image_path]

    # Для vision нужна модель, поддерживающая изображения
    # OpenRouter: попробуем использовать бесплатную vision-модель или ту, что указана
    vision_model = model
    # Если модель явно "openrouter/free", заменим на актуальную бесплатную модель с поддержкой vision
    if "free" in model.lower() or not model:
        vision_model = "nvidia/nemotron-nano-12b-v2-vl:free"

    comment_text = f"КОММЕНТАРИЙ ПОЛЬЗОВАТЕЛЯ К ЭТОМУ ДОКУМЕНТУ: {user_comment}\nУчитывай его (особенно цех).\n\n" if user_comment else ""

    user_content = [
        {
            "type": "text",
            "text": (
                f"{comment_text}Это фотография сертификата/свидетельства о поверке прибора или документ с данными о приборах КИП. "
                "Извлеки все данные о приборах, которые можешь разобрать на изображении."
            ),
        }
    ]

    for path in paths:
        b64 = _encode_image_base64(path)
        mime = _get_image_mime(path)
        user_content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime};base64,{b64}",
            },
        })

    return _call_ai_api(
        messages=[
            {"role": "system", "content": _AI_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        api_key=api_key, base_url=base_url, model=vision_model
    )


def _call_ai_api(messages: list, api_key: str, base_url: str, model: str) -> tuple[list[dict], str]:
    """Общий вызов OpenRouter API."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8000",
        "X-Title": "Automation SSZ",
    }

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
    }

    result_text = ""
    try:
        resp = requests.post(base_url, json=payload, headers=headers, timeout=180)
        resp.raise_for_status()
        data = resp.json()
        if not data or 'choices' not in data or len(data['choices']) == 0:
            return [], f"Некорректный ответ от API ИИ (отсутствуют варианты choices): {data}"
        choice = data['choices'][0]
        if 'message' not in choice or 'content' not in choice['message']:
            return [], f"Некорректный формат ответа ИИ choice: {choice}"
        result_text = choice['message']['content'].strip()

        # Извлечь JSON из ответа
        parsed = _extract_json_array(result_text)
        if parsed is not None:
            return parsed, ""

        return [], f"ИИ вернул ответ, но не в формате JSON-массива.\nОтвет: {result_text[:300]}..."

    except requests.exceptions.Timeout:
        return [], "Таймаут запроса к ИИ (180 сек). Попробуйте ещё раз."
    except requests.exceptions.ConnectionError:
        return [], "Нет соединения с сервером ИИ. Проверьте интернет-подключение."
    except Exception as e:
        err_msg = str(e)
        if result_text:
            err_msg += f"\nОтвет ИИ: {result_text[:200]}..."

        # Попробовать извлечь ошибку из ответа API
        try:
            if 'resp' in locals() and resp is not None:
                try:
                    err_data = resp.json()
                    if "error" in err_data:
                        api_err = err_data["error"]
                        if isinstance(api_err, dict) and "message" in api_err:
                            err_msg = f"Ошибка API: {api_err['message']}"
                        else:
                            err_msg = f"Ошибка API: {api_err}"
                except ValueError:
                    err_msg += f"\nОтвет сервера: {resp.text[:300]}"
        except Exception:
            pass

        print(f"[ai_parser] AI API Error: {err_msg}")
        return [], err_msg


def _extract_json_array(text: str) -> list[dict] | None:
    """Извлечь JSON-массив из текста ИИ (может быть обёрнут в ```json ... ```)."""
    # Убрать markdown-обёртки
    clean = text.strip()
    if clean.startswith("```json"):
        clean = clean[7:]
    elif clean.startswith("```"):
        clean = clean[3:]
    if clean.endswith("```"):
        clean = clean[:-3]
    clean = clean.strip()

    # Попытка напрямую
    try:
        result = json.loads(clean)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Поиск массива регулярным выражением
    match = re.search(r'\[\s*\{.*?\}\s*\]', text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(0))
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    return None


# ═══════════════════════════════════════════════════════════════════════════
#  Валидация и нормализация результатов ИИ
# ═══════════════════════════════════════════════════════════════════════════

def _normalize_date(val) -> str | None:
    """Нормализовать дату из ответа ИИ в формат YYYY-MM-DD."""
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in ("null", "none", "nan", "nat", "не указана", "неизвестно", ""):
        return None

    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y", "%d/%m/%y",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(s.split("T")[0].split()[0], fmt)
            return dt.strftime("%Y-%m-%d")
        except (ValueError, IndexError):
            continue
    return None


def _validate_and_normalize(raw_items: list[dict]) -> tuple[list[dict], list[str]]:
    """
    Провалидировать и нормализовать результаты ИИ.
    Привязать к допустимым цехам, нормализовать даты.
    """
    valid = []
    warnings = []
    unmatched_ws = set()

    if not isinstance(raw_items, list):
        return [], ["Ответ ИИ не является списком объектов."]

    for item in raw_items:
        if not isinstance(item, dict):
            continue

        # Определить цех
        raw_ws = str(item.get("workshop", "")).strip()
        ws_name = _match_workshop(raw_ws)
        if not ws_name:
            unmatched_ws.add(raw_ws)
            ws_name = None  # Пометим — спросим пользователя позже, или пропустим

        # Извлечь остальные поля
        device_name = str(item.get("device_name", "")).strip()
        model = str(item.get("model", "")).strip()
        serial = str(item.get("serial_number", "")).strip()
        position = str(item.get("position", "")).strip()
        location = str(item.get("location", "Общий")).strip()
        loc_type = str(item.get("location_type", "general")).strip()
        cal_date = _normalize_date(item.get("calibration_date"))

        # Минимальная валидация — нужно хотя бы имя прибора
        if not device_name and not model:
            continue

        # Комбинированное имя
        if model and device_name:
            full_name = f"{device_name} — {model}"
        elif model:
            full_name = model
        else:
            full_name = device_name

        # Нормализация типа места
        if loc_type not in ("furnace", "utir", "storage", "general"):
            loc_lower = location.lower()
            if "печь" in loc_lower or "печ" in loc_lower:
                loc_type = "furnace"
            elif "утир" in loc_lower:
                loc_type = "utir"
            elif any(w in loc_lower for w in ("резерв", "кладовк", "склад")):
                loc_type = "storage"
            else:
                loc_type = "general"

        if not location:
            location = "Общий"

        valid.append({
            "workshop": ws_name,
            "location": location,
            "location_type": loc_type,
            "device_name": full_name,
            "serial_number": serial if serial.lower() not in ("", "nan", "none") else "",
            "position": position,
            "calibration_date": cal_date,
        })

    if unmatched_ws:
        for u in unmatched_ws:
            warnings.append(f"Не удалось определить цех: «{u}» — приборы без цеха будут пропущены.")

    return valid, warnings


# ═══════════════════════════════════════════════════════════════════════════
#  Детерминистический парсер для Excel-файлов графиков ППР
# ═══════════════════════════════════════════════════════════════════════════

# Маппинг имён листов → каноническое имя цеха (для известного формата ППР)
_SHEET_TO_WORKSHOP = {
    "цех 47":   "Цех 47 (Спецсталь)",
    "цех 66":   "Цех 66 (66.2, Спецсталь)",
    "цех 6":    "Цех 6 (Картэкс, 2-й)",
    "цех 2":    "Цех 6 (Картэкс, 2-й)",
    "исм":      "Цех 92 (ИСМ)",
    "из п.10":  "Печь 10 (Ижора, цех 66.1)",
    "из п":     "Печь 10 (Ижора, цех 66.1)",
    "п.10":     "Печь 10 (Ижора, цех 66.1)",
    "печь 10":  "Печь 10 (Ижора, цех 66.1)",
}


def _is_nan(val) -> bool:
    if val is None:
        return True
    if isinstance(val, float) and math.isnan(val):
        return True
    if isinstance(val, str) and not val.strip():
        return True
    return False


def _clean_str(val) -> str:
    if _is_nan(val):
        return ""
    s = str(val).strip()
    s = s.replace("\r\n", " / ").replace("\n", " / ").replace("\r", " / ")
    return s


def _parse_cal_date_cell(val) -> str | None:
    """Разобрать дату из ячейки Excel."""
    if _is_nan(val):
        return None
    if isinstance(val, (datetime, date)):
        return val.strftime("%Y-%m-%d")
    if hasattr(val, 'strftime'):
        try:
            return val.strftime("%Y-%m-%d")
        except Exception:
            pass
    s = str(val).strip()
    if not s or s.lower() in ("брак", "ремонт", "списан", "nan", "nat", "none"):
        return None
    for fmt in ("%d.%m.%y", "%d.%m.%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(s.split()[0], fmt)
            return dt.strftime("%Y-%m-%d")
        except (ValueError, IndexError):
            continue
    return None


def _is_warehouse_inventory_excel(filepath: str) -> bool:
    """Определить компактный список приборов кладовки/вывоза без обращения к ИИ."""
    try:
        import pandas as pd
        sheets = pd.read_excel(filepath, sheet_name=None, header=None, nrows=12)
        for sheet_name, df in sheets.items():
            text = " ".join(
                _clean_str(value).lower()
                for value in [sheet_name, *df.fillna("").to_numpy().ravel().tolist()]
            )
            if "тип прибора" in text and "заводской" in text and ("на вывоз" in text or "кладов" in text):
                return True
    except Exception:
        pass
    return False


def _parse_warehouse_inventory_excel(filepath: str) -> tuple[list[dict], list[str]]:
    """Разобрать ведомость вида «тип / заводской номер / датчик»."""
    import pandas as pd

    devices = []
    warnings = []
    sheets = pd.read_excel(filepath, sheet_name=None, header=None, dtype=object)
    for sheet_name, df in sheets.items():
        sheet_text = " ".join(
            _clean_str(value).lower()
            for value in [sheet_name, *df.head(12).fillna("").to_numpy().ravel().tolist()]
        )
        is_decommissioned = "не вывозить" in sheet_text or "исключ" in sheet_text

        header_row = None
        columns = {}
        for row_index in range(min(15, len(df))):
            headers = [_clean_str(value).lower() for value in df.iloc[row_index]]
            for column_index, header in enumerate(headers):
                if "тип прибора" in header or header == "тип":
                    columns["type"] = column_index
                elif "заводской" in header or "зав." in header:
                    columns["serial"] = column_index
                elif "датчик" in header:
                    columns["sensor"] = column_index
            if "type" in columns and "serial" in columns:
                header_row = row_index
                break

        if header_row is None:
            warnings.append(f"Лист «{sheet_name}»: не найдены обязательные колонки — пропущен.")
            continue

        sheet_count = 0
        for row_index in range(header_row + 1, len(df)):
            row = df.iloc[row_index]
            device_type = _clean_str(row.iloc[columns["type"]])
            serial = _clean_str(row.iloc[columns["serial"]])
            sensor = _clean_str(row.iloc[columns["sensor"]]) if "sensor" in columns else ""
            if not device_type or not serial:
                continue
            name = f"{device_type} / {sensor}" if sensor else device_type
            devices.append({
                "workshop": "Цех 47 (Спецсталь)",
                "location": "Кладовка 47 цеха",
                "location_type": "storage",
                "device_name": name,
                "serial_number": serial,
                "position": "",
                "calibration_date": None,
                "authoritative_location": True,
                "lifecycle_status": "out_of_service" if is_decommissioned else "active",
                "source_file": os.path.basename(filepath),
                "source_row": row_index + 1,
            })
            sheet_count += 1

        status_label = "выведено из эксплуатации" if is_decommissioned else "принято в кладовку"
        warnings.append(f"Лист «{sheet_name}»: {status_label} ({sheet_count} строк).")

    return devices, warnings


def ingest_decommissioned_warehouse_items(filepath: str, note: str = "") -> tuple[bool, str]:
    """Добавить только помеченные как неэксплуатируемые приборы из ведомости."""
    devices, warnings = _parse_warehouse_inventory_excel(filepath)
    devices = [item for item in devices if item.get("lifecycle_status") == "out_of_service"]
    if not devices:
        return False, "В файле не найдено приборов со статусом «Выведено из эксплуатации»."

    ws = get_workshop_by_name("Цех 47 (Спецсталь)")
    if not ws:
        return False, "Не найден цех 47 для загрузки выведенных из эксплуатации приборов."
    location = get_location_by_name(ws["id"], "Кладовка 47 цеха")
    if not location:
        location_id = add_location(ws["id"], "Кладовка 47 цеха", "storage")
    else:
        location_id = location["id"]

    import_id = create_inventory_import(filepath, ws["id"], location_id, len(devices), note)
    added = updated = skipped = 0
    for item in devices:
        action, device_id = smart_upsert_device(
            name=item["device_name"],
            serial_number=item["serial_number"],
            location_id=location_id,
            calibration_date=None,
            position=None,
            update_location=True,
            source=item.get("source_file"),
            lifecycle_status="out_of_service",
            return_device_id=True,
        )
        if action == "added":
            added += 1
        elif action == "updated":
            updated += 1
        else:
            skipped += 1
        add_inventory_import_item(import_id, device_id, action, item.get("source_row"))
    finish_inventory_import(import_id, added, updated, skipped)

    detail = "\n".join(f"  • {warning}" for warning in warnings if "выведено" in warning)
    return True, (
        f"Выведено из эксплуатации: {added + updated} приборов "
        f"({added} добавлено, {updated} обновлено).\n{detail}"
    )


def _is_ppr_excel(filepath: str) -> bool:
    """Быстрая проверка: это Excel-файл с графиками ППР?"""
    try:
        import pandas as pd
        sheets = pd.ExcelFile(filepath).sheet_names
        for sn in sheets:
            sn_lower = sn.strip().lower()
            for pattern in _SHEET_TO_WORKSHOP:
                if pattern in sn_lower:
                    return True
    except Exception:
        pass
    return False


def _parse_ppr_excel(filepath: str) -> tuple[list[dict], list[str]]:
    """Детерминистический парсер для Excel-файлов графиков ППР."""
    import pandas as pd
    devices = []
    warnings = []

    try:
        sheets = pd.read_excel(filepath, sheet_name=None, header=None)
    except Exception as e:
        return [], [f"Ошибка чтения файла: {e}"]

    for sheet_name, df in sheets.items():
        # Определить цех по имени листа
        sn_lower = sheet_name.strip().lower()
        ws_name = None
        for pattern, ws in sorted(_SHEET_TO_WORKSHOP.items(), key=lambda x: -len(x[0])):
            if pattern in sn_lower:
                ws_name = ws
                break
        if ws_name is None:
            warnings.append(f"Лист «{sheet_name}»: не соответствует известному цеху — пропущен.")
            continue

        # Найти строку заголовка
        header_row = None
        for i in range(min(15, len(df))):
            row_text = " ".join(_clean_str(v).lower() for v in df.iloc[i])
            if "п/п" in row_text or "п\\п" in row_text or "позиция" in row_text:
                header_row = i
                break
        if header_row is None:
            warnings.append(f"Лист «{sheet_name}»: не найдена строка заголовка.")
            continue

        # Найти индексы столбцов
        headers = [_clean_str(v).lower() for v in df.iloc[header_row]]
        cols = {}
        for i, h in enumerate(headers):
            if "п/п" in h or "п\\п" in h:
                cols["num"] = i
            elif "позиция" in h:
                cols["position"] = i
            elif h in ("си", "с и"):
                cols["si"] = i
            elif "тип" in h or "модель" in h:
                cols["model"] = i
            elif "заводской" in h or "зав" in h:
                cols["serial"] = i
            elif "место" in h and "установ" in h:
                cols["location"] = i
            elif "период" in h:
                cols["period"] = i
            elif "дата" in h and ("повер" in h or "очеред" in h):
                cols["cal_date"] = i

        if "num" not in cols:
            warnings.append(f"Лист «{sheet_name}»: не найден столбец «№ п/п».")
            continue

        num_col = cols["num"]
        has_loc = "location" in cols

        # Найти начало данных
        data_start = header_row + 3
        for i in range(header_row + 1, min(header_row + 10, len(df))):
            val = df.iloc[i, num_col]
            if not _is_nan(val):
                try:
                    int(float(val))
                    data_start = i
                    break
                except (ValueError, TypeError):
                    continue

        parsed_count = 0
        for i in range(data_start, len(df)):
            val = df.iloc[i, num_col]
            if _is_nan(val):
                continue
            try:
                n = int(float(val))
                if n <= 0:
                    continue
            except (ValueError, TypeError):
                continue

            row = df.iloc[i]
            position = _clean_str(row.iloc[cols["position"]]) if "position" in cols else ""
            si = _clean_str(row.iloc[cols["si"]]) if "si" in cols else ""
            model = _clean_str(row.iloc[cols["model"]]) if "model" in cols else ""
            serial = _clean_str(row.iloc[cols["serial"]]) if "serial" in cols else ""
            cal_date = _parse_cal_date_cell(row.iloc[cols["cal_date"]] if "cal_date" in cols else None)

            # Место установки
            if has_loc:
                location = _clean_str(row.iloc[cols["location"]])
            else:
                # Попробовать извлечь из позиции (например «Печь № 3»)
                m = re.match(r"[Пп]ечь\s*[№#]?\s*(\d+)", position)
                location = f"Печь {m.group(1)}" if m else ""

            loc_lower = location.lower()
            if not location:
                loc_type = "general"
            elif "печь" in loc_lower or "печ" in loc_lower:
                loc_type = "furnace"
            elif "утир" in loc_lower:
                loc_type = "utir"
            elif any(w in loc_lower for w in ("резерв", "кладовк", "склад")):
                loc_type = "storage"
            else:
                loc_type = "general"

            device_name = f"{si} — {model}" if si and model else (si or model or "Неизвестный прибор")

            devices.append({
                "workshop": ws_name,
                "location": location if location else "Общий",
                "location_type": loc_type,
                "device_name": device_name,
                "serial_number": serial,
                "position": position,
                "calibration_date": cal_date,
            })
            parsed_count += 1

        warnings.append(f"Лист «{sheet_name}» ({ws_name}): {parsed_count} приборов.")

    return devices, warnings


# ═══════════════════════════════════════════════════════════════════════════
#  Главная функция: ingest_document()
# ═══════════════════════════════════════════════════════════════════════════

def ingest_document(filepath: str, user_comment: str = "") -> tuple[bool, str]:
    """
    Загрузить документ / изображение и добавить приборы в БД.

    Логика:
      1. Если Excel и это формат ППР → детерминистический парсер (без ИИ)
      2. Если изображение → vision API
      3. Иначе → текстовый ИИ-парсер
    """
    ext = os.path.splitext(filepath)[1].lower()

    # Проверка поддержки формата
    all_supported = IMAGE_EXTENSIONS | EXCEL_EXTENSIONS | DOCUMENT_EXTENSIONS
    if ext not in all_supported:
        return False, (
            f"Формат файла «{ext}» не поддерживается.\n\n"
            "Поддерживаемые форматы:\n"
            "  • Excel: .xlsx, .xls\n"
            "  • Документы: .docx, .txt, .csv, .pdf\n"
            "  • Изображения: .jpg, .jpeg, .png, .bmp, .tiff, .webp"
        )

    devices = []
    warnings = []

    # ──── Путь 1: ведомость кладовки/вывоза → детерминистический парсер ────
    if ext in EXCEL_EXTENSIONS and _is_warehouse_inventory_excel(filepath):
        devices, warnings = _parse_warehouse_inventory_excel(filepath)
        warnings.insert(0, "Распознан формат: список кладовки/вывоза (без ИИ)")

    # ──── Путь 2: Excel с графиками ППР → детерминистический парсер ────
    elif ext in EXCEL_EXTENSIONS and _is_ppr_excel(filepath):
        devices, warnings = _parse_ppr_excel(filepath)
        warnings.insert(0, "Распознан формат: Графики ППР (детерминистический парсер)")

    # ──── Путь 3: Изображение → vision API ────
    elif ext in IMAGE_EXTENSIONS:
        api_key = CONFIG.get("ai_api_key", "").strip()
        if not api_key:
            return False, (
                "Для обработки изображений необходим API-ключ ИИ.\n\n"
                "Укажите ключ OpenRouter в настройках (поле ai_api_key в config.json)."
            )
        base_url = CONFIG.get("ai_base_url", "https://openrouter.ai/api/v1/chat/completions").strip()
        model = CONFIG.get("ai_model", "google/gemini-2.0-flash-exp:free").strip()

        raw_items, err = _call_ai_vision(filepath, api_key, base_url, model, user_comment)
        if err:
            return False, f"Ошибка ИИ при обработке изображения:\n{err}"
        devices, val_warnings = _validate_and_normalize(raw_items)
        warnings.extend(val_warnings)
        warnings.insert(0, "Распознан формат: Изображение (ИИ vision)")

    # ──── Путь 4: Документ → текстовый ИИ ────
    else:
        # Для Excel, который не ППР — тоже идём через ИИ
        text = _extract_text_from_file(filepath)
        
        # Если это PDF и текст не извлекся (вероятно, сканы), пробуем через vision API
        if not text.strip() and ext == '.pdf':
            try:
                import fitz
                import tempfile
                doc = fitz.open(filepath)
                img_paths = []
                for i in range(min(len(doc), 20)): # Увеличили до 20 страниц
                    # Уменьшаем разрешение до 1.0x для стабильности бесплатных моделей ИИ
                    pix = doc.load_page(i).get_pixmap(matrix=fitz.Matrix(1.0, 1.0))
                    temp_img = tempfile.mktemp(suffix=".jpg")
                    pix.save(temp_img)
                    img_paths.append(temp_img)
                doc.close()
                
                if img_paths:
                    api_key = CONFIG.get("ai_api_key", "").strip()
                    if not api_key:
                        return False, "Для обработки изображений необходим API-ключ ИИ."
                    base_url = CONFIG.get("ai_base_url", "https://openrouter.ai/api/v1/chat/completions").strip()
                    # Меняем дефолт на бесплатный роутер, так как gemini-2.0-flash-exp:free удален
                    model = CONFIG.get("ai_model", "openrouter/free").strip()
                    
                    all_raw_items = []
                    chunk_size = 1 # Отправляем по 1 странице за раз для большей стабильности бесплатных моделей
                    for i in range(0, len(img_paths), chunk_size):
                        chunk_paths = img_paths[i:i+chunk_size]
                        raw_items, err = _call_ai_vision(chunk_paths, api_key, base_url, model, user_comment)
                        if err:
                            for p in img_paths:
                                try: os.remove(p)
                                except: pass
                            return False, f"Ошибка ИИ при обработке PDF (стр. {i+1}-{i+len(chunk_paths)}):\n{err}"
                        if raw_items:
                            all_raw_items.extend(raw_items)
                            
                    for p in img_paths:
                        try:
                            os.remove(p)
                        except:
                            pass
                            
                    devices, val_warnings = _validate_and_normalize(all_raw_items)
                    warnings.extend(val_warnings)
                    warnings.insert(0, f"Распознан формат: отсканированный PDF (через Vision API, {len(img_paths)} стр.)")
                    
                    text = "SKIP_TEXT_PROCESSING"
            except Exception as e:
                pass

        if not text.strip():
            return False, "Не удалось извлечь текст из файла, или файл пуст (возможно, это скан в PDF, а PyMuPDF не установлен)."

        if text != "SKIP_TEXT_PROCESSING":
            api_key = CONFIG.get("ai_api_key", "").strip()
            if not api_key:
                return False, (
                    "Для обработки произвольных документов необходим API-ключ ИИ.\n\n"
                    "Укажите ключ OpenRouter в настройках (поле ai_api_key в config.json)."
                )
            base_url = CONFIG.get("ai_base_url", "https://openrouter.ai/api/v1/chat/completions").strip()
            model = CONFIG.get("ai_model", "openrouter/free").strip()
    
            raw_items, err = _call_ai_text(text, api_key, base_url, model, user_comment)
            if err:
                return False, f"Ошибка ИИ при обработке документа:\n{err}"
            devices, val_warnings = _validate_and_normalize(raw_items)
            warnings.extend(val_warnings)
            warnings.insert(0, f"Распознан формат: Документ ({ext}) — ИИ-парсер")

    # ──── Запись в БД ────

    if not devices:
        msg = "Не удалось извлечь ни одного прибора из файла.\n\n"
        if warnings:
            msg += "Подробности:\n" + "\n".join(f"  • {w}" for w in warnings)
        return False, msg

    added = 0
    updated = 0
    skipped = 0
    import_id = None
    for item in devices:
        ws_name = item["workshop"]

        # Пропустить приборы без определённого цеха
        if ws_name is None:
            skipped += 1
            continue

        # Найти или создать цех (только из допустимого списка)
        ws = get_workshop_by_name(ws_name)
        if not ws:
            if ws_name in VALID_WORKSHOPS:
                ws_id = add_workshop(ws_name)
            else:
                skipped += 1
                continue
        else:
            ws_id = ws["id"]

        loc_name = item["location"]
        loc_type = item["location_type"]
        position = item.get("position", "").strip()

        # Фильтр: только наши приборы (КСП, КСД, Метран, Термопары, ТХА, ТПР)
        dev_name = str(item.get("device_name", "")).lower()
        model_name = str(item.get("model", "")).lower()
        combined_name = f"{dev_name} {model_name}"
        
        valid_devs = ("ксп", "ксд", "метран", "термопар", "тха", "тпр", "ш4500", "нмп")
        if not any(v in combined_name for v in valid_devs):
            skipped += 1
            warnings.append(f"Пропущен прибор '{combined_name}' (не КСП/КСД/Метран/Термопара)")
            continue

        # Если это печь и не указана позиция - отправляем в "Нераспределенные"
        if loc_type == "furnace" and not position:
            loc_id = get_unassigned_location(ws_id)
        else:
            # Найти или создать место
            loc = get_location_by_name(ws_id, loc_name)
            if not loc:
                loc_id = add_location(ws_id, loc_name, loc_type)
            else:
                loc_id = loc["id"]

        if item.get("authoritative_location") and import_id is None:
            import_id = create_inventory_import(
                item.get("source_file", filepath), ws_id, loc_id, len(devices), user_comment
            )

        upsert_result = smart_upsert_device(
            name=item["device_name"],
            serial_number=item["serial_number"],
            location_id=loc_id,
            calibration_date=item["calibration_date"],
            position=position,
            update_location=bool(item.get("authoritative_location")),
            source=item.get("source_file"),
            lifecycle_status=item.get("lifecycle_status"),
            return_device_id=bool(import_id),
        )
        status, device_id = upsert_result if isinstance(upsert_result, tuple) else (upsert_result, None)
        if status == "added":
            added += 1
        elif status == "updated":
            updated += 1
        else:
            skipped += 1
        if import_id and device_id:
            add_inventory_import_item(import_id, device_id, status, item.get("source_row"))

    if import_id:
        finish_inventory_import(import_id, added, updated, skipped)

    # Сводка
    by_ws = {}
    for d in devices:
        if d["workshop"]:
            by_ws.setdefault(d["workshop"], 0)
            by_ws[d["workshop"]] += 1

    summary_parts = [f"Добавлено новых приборов: {added}\nОбновлено существующих: {updated}"]
    if skipped:
        summary_parts.append(f"Пропущено (цех не определён): {skipped}")
    summary_parts.append("")
    if by_ws:
        summary_parts.append("По цехам:")
        for ws, cnt in sorted(by_ws.items()):
            summary_parts.append(f"  • {ws}: {cnt}")
    if warnings:
        summary_parts.append("\nДетали:")
        for w in warnings:
            summary_parts.append(f"  • {w}")

    return True, "\n".join(summary_parts)
