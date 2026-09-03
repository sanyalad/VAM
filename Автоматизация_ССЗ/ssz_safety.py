"""Инварианты безопасности для ППР в ССЗ.

ППР разрешено записывать и печатать только после подтверждённой проверки
видимого цвета через Excel. Обычные и ручные задания этими правилами не
ограничиваются.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

from openpyxl.utils.cell import coordinate_from_string, column_index_from_string

from ssz_config import CONFIG


AUDIT_SHEET = "_SSZ_AUDIT"
AUDIT_MARKER = "SSZ_SAFETY_V1"


class PprSafetyError(RuntimeError):
    """Нарушен обязательный инвариант проверки ППР."""


def is_ppr_task(task):
    return (
        task.get("task_kind") == "ppr"
        or "plan_day" in task
        or "ППР" in str(task.get("work") or "").upper()
    )


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def source_fingerprint(path):
    absolute = os.path.abspath(path)
    try:
        stat = os.stat(absolute)
    except OSError as exc:
        raise PprSafetyError(f"Исходный график недоступен: {absolute}") from exc

    digest = hashlib.sha256()
    try:
        with open(absolute, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise PprSafetyError(f"Не удалось прочитать исходный график: {absolute}") from exc

    return {
        "path": absolute,
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": digest.hexdigest(),
    }


def fingerprint_matches(expected):
    if not expected or not expected.get("path"):
        return False
    current = source_fingerprint(expected["path"])
    return all(current.get(key) == expected.get(key) for key in ("size", "mtime_ns", "sha256"))


def _parse_utc(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise PprSafetyError("У ППР отсутствует корректное время проверки цвета") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate_ppr_tasks_for_generation(tasks, now=None):
    """Проверяет, что каждый ППР имеет свежий доказанный допуск."""
    ppr_tasks = [task for task in tasks if is_ppr_task(task)]
    if not ppr_tasks:
        return []

    now = now or datetime.now(timezone.utc)
    max_age_s = float(CONFIG.get("ppr_validation_max_age_s", 900.0))
    fingerprints = {}

    for task in ppr_tasks:
        work = str(task.get("work") or "ППР")
        if task.get("color_state") != "uncolored":
            raise PprSafetyError(f"ППР не имеет допуска по цвету: {work}")
        if task.get("color_source") != "excel_display_format":
            raise PprSafetyError(f"ППР не проверен по видимому цвету Excel: {work}")
        if not task.get("analysis_id"):
            raise PprSafetyError(f"У ППР отсутствует идентификатор анализа: {work}")
        checked_at = _parse_utc(task.get("color_checked_at"))
        age_s = (now - checked_at).total_seconds()
        if age_s < -60 or age_s > max_age_s:
            raise PprSafetyError(
                f"Проверка цвета ППР устарела ({int(max(age_s, 0))} сек.): {work}"
            )
        for field, label in (
            ("source_file", "файл"),
            ("source_sheet", "лист"),
            ("source_cell", "ячейка"),
        ):
            if not task.get(field):
                raise PprSafetyError(f"У ППР не указан исходный {label}: {work}")

        expected = task.get("source_fingerprint")
        path = os.path.abspath(task["source_file"])
        if path not in fingerprints:
            fingerprints[path] = source_fingerprint(path)
        current = fingerprints[path]
        if not expected or any(
            current.get(key) != expected.get(key) for key in ("size", "mtime_ns", "sha256")
        ):
            raise PprSafetyError(
                f"График изменился после анализа. Повторите анализ перед генерацией: {os.path.basename(path)}"
            )
    return ppr_tasks


def build_audit_payload(target_date, tasks):
    ppr_tasks = validate_ppr_tasks_for_generation(tasks)
    return {
        "version": 1,
        "marker": AUDIT_MARKER,
        "generated_at": utc_now_iso(),
        "target_date": target_date.strftime("%Y-%m-%d"),
        "ppr_tasks": [
            {
                key: task.get(key)
                for key in (
                    "work",
                    "place",
                    "plan_date",
                    "assigned_date",
                    "analysis_id",
                    "color_state",
                    "color_source",
                    "color_checked_at",
                    "source_file",
                    "source_sheet",
                    "source_cell",
                    "source_fingerprint",
                )
            }
            for task in ppr_tasks
        ],
    }


def write_audit_sheet(workbook, payload):
    if AUDIT_SHEET in workbook.sheetnames:
        del workbook[AUDIT_SHEET]
    sheet = workbook.create_sheet(AUDIT_SHEET)
    sheet.sheet_state = "veryHidden"
    sheet["A1"] = AUDIT_MARKER
    sheet["A2"] = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def read_audit_sheet(workbook):
    if AUDIT_SHEET not in workbook.sheetnames:
        return None
    sheet = workbook[AUDIT_SHEET]
    if sheet["A1"].value != AUDIT_MARKER:
        raise PprSafetyError("Некорректный паспорт безопасности ССЗ")
    try:
        payload = json.loads(sheet["A2"].value or "")
    except (TypeError, ValueError) as exc:
        raise PprSafetyError("Повреждён паспорт безопасности ССЗ") from exc
    if payload.get("marker") != AUDIT_MARKER or payload.get("version") != 1:
        raise PprSafetyError("Неподдерживаемая версия паспорта безопасности ССЗ")
    return payload


def source_coord(task):
    try:
        column_letters, row_one_based = coordinate_from_string(task["source_cell"])
        return (
            str(task["source_sheet"]),
            int(row_one_based) - 1,
            int(column_index_from_string(column_letters)) - 1,
        )
    except Exception as exc:
        raise PprSafetyError(
            f"Некорректная исходная ячейка ППР: {task.get('source_cell', '')}"
        ) from exc
