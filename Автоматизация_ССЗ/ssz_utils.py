"""
ssz_utils.py — Общие утилиты ССЗ.
Вынесены из ssz_window.py и ssz_dialogs.py для устранения дублирования.
"""

from __future__ import annotations

from datetime import date, datetime

from ssz_config import CONFIG


# ═══════════════════════════════════════════════════════════════════════════
#  Исполнители / расписание
# ═══════════════════════════════════════════════════════════════════════════

def get_executor(target_date) -> str:
    """Возвращает сменного на дату с учётом табеля и отсутствий."""
    d = target_date.date() if isinstance(target_date, datetime) else target_date
    epoch = CONFIG["duty_epoch"]
    block = ((d - epoch).days // 2) % 2
    default_exec = CONFIG.get("executor_1", "") if block == 0 else CONFIG.get("executor_2", "")
    from staff_schedule import ensure_staff_seeded, resolve_duty_executor

    ensure_staff_seeded()
    return resolve_duty_executor(d, default_exec)


def get_day_executors(target_date) -> list[str]:
    """Активные дневные сотрудники на дату с учётом табеля."""
    from staff_schedule import get_day_executors as _get_day_executors

    d = target_date.date() if isinstance(target_date, datetime) else target_date
    return _get_day_executors(d)


def get_duty_surname(target_date) -> str:
    """Фамилии исполнителей на дату (краткий формат)."""
    full = get_executor(target_date)
    surnames = []
    for ex in full.split(","):
        parts = ex.strip().split()
        surname = ""
        for i, part in enumerate(parts):
            if part == "КИПиА" and i + 1 < len(parts):
                surname = parts[i + 1]
                break
        if not surname:
            if len(parts) >= 2 and "." in parts[-1]:
                surname = parts[-2]
            else:
                surname = parts[-1] if parts else ex.strip()
        if surname:
            surnames.append(surname)
    return ", ".join(surnames) if surnames else full


def get_kip_dmm_number(target_date) -> int:
    """Номер КИП для замены д-мм на заданную дату."""
    epoch = CONFIG["kip_epoch"]
    d = target_date.date() if isinstance(target_date, datetime) else target_date
    return (5 + (d - epoch).days) % 7 + 1


def kip_dmm_task_text(kip_num: int) -> str:
    return f"Заменить круговые д-ммы в КИПе №{int(kip_num)}."


def get_default_tasks(target_date) -> list[dict]:
    """Только штатные задания ССЗ; план уточнения базы печатается отдельно."""
    return [
        {"work": CONFIG.get("task_1", ""), "place": CONFIG.get("place_1", "")},
        {"work": CONFIG.get("task_2", ""), "place": CONFIG.get("place_2", "")},
    ]


# ═══════════════════════════════════════════════════════════════════════════
#  Автокоррекция ввода
# ═══════════════════════════════════════════════════════════════════════════

def auto_correct_task(text: str) -> str:
    """Нормализует текст задания: заглавная буква + точка в конце."""
    text = text.strip()
    if not text:
        return text
    text = text[0].upper() + text[1:]
    if not text.endswith((".", "!", "?")):
        text += "."
    return text


def auto_correct_place(place: str) -> str:
    """Нормализует название места: «Цех № N», аббревиатуры и т.д."""
    place = place.strip()
    if not place:
        return "Цеха обслуживания"
    if all(c.isdigit() or c in "-/\\" for c in place):
        return f"Цех № {place}"

    place_lower = place.lower()
    if place_lower == "исм":
        return "ИСМ"
    if place_lower == "кип":
        return "КИП"

    if "цех" in place_lower and "обслуживания" not in place_lower:
        cleaned = place_lower.replace("цех", "").replace("№", "").strip()
        if cleaned:
            return f"Цех № {cleaned.upper()}"

    return place[0].upper() + place[1:]


# ═══════════════════════════════════════════════════════════════════════════
#  Кэш ручных заданий
# ═══════════════════════════════════════════════════════════════════════════

def manual_cache_combo_lists(cached_tasks) -> tuple[list, list]:
    """Возвращает (works, places) для выпадающих списков, без дублей."""
    works, places = [], []
    for w, p in reversed(cached_tasks):
        if w and w not in works:
            works.append(w)
        if p and p not in places:
            places.append(p)
    return works, places
