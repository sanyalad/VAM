"""Парсинг графиков ППР, распределение, история, отчёт предупреждений."""

import os
import re
import time
import calendar
import uuid
from datetime import date, datetime

from ssz_config import CONFIG

class DummyPd:
    @staticmethod
    def notna(val):
        if val is None: return False
        if isinstance(val, float) and val != val: return False
        return True
pd = DummyPd()

from operations_log import log_operation
from ssz_safety import PprSafetyError, source_fingerprint, utc_now_iso
from xls_color_cache import (
    ExcelColorSession,
    DATA_ROW_START,
    DATA_ROW_END,
    PLAN_COL_START,
    PLAN_COL_END,
)

def get_schedules_dir():
    return CONFIG.get("schedules_dir", "Графики")

def get_history_file():
    return CONFIG.get("history_file", "Учет_выполненных_ППР.txt")
DEFAULT_BG_INDICES = frozenset({8, 9, 64, 65535})
_HISTORY_LINE_RE = re.compile(r"^\[\d{2}\.\d{2}\.\d{4}\]\s*\|")
PPR_STATUSES = ("Выдано", "Выполнено", "Не выполнено", "Отменено")
_PPR_STATUS_RE = r"(Выдано|Выполнено|Не выполнено|Отменено)"




class AnalysisReport:
    def __init__(self):
        self.warnings = []
        self.color_failures = []
        self._seen = set()
        self.stats = {
            "xlsx_files": 0,
            "xls_files": 0,
            "com_cells": 0,
            "color_cells_required": 0,
            "ppr_candidates": 0,
            "openpyxl_colored": 0,
            "com_colored_added": 0,
            "cache_hits": 0,
            "elapsed_s": 0.0,
        }

    def add(self, kind, message):
        self.warnings.append({"kind": kind, "message": message})

    def add_once(self, kind, message):
        key = (kind, message)
        if key in self._seen:
            return
        self._seen.add(key)
        self.add(kind, message)

    def merge_color_failures(self, failures):
        for f in failures:
            if f not in self.color_failures:
                self.color_failures.append(f)

    def merge_stats(self, other_stats):
        for k in self.stats:
            if k == "elapsed_s":
                self.stats[k] += other_stats.get(k, 0)
            else:
                self.stats[k] += other_stats.get(k, 0)

    def stats_summary(self):
        s = self.stats
        parts = [f"xlsx={s['xlsx_files']}", f"xls={s['xls_files']}"]
        if s["com_cells"]:
            parts.append(f"COM={s['com_cells']} яч.")
        else:
            parts.append("COM не использовался")
        if s["openpyxl_colored"]:
            parts.append(f"openpyxl={s['openpyxl_colored']}")
        if s.get("com_colored_added"):
            parts.append(f"COM+={s['com_colored_added']}")
        parts.append(f"{s['elapsed_s']:.1f} с")
        return "Графики: " + ", ".join(parts)

    def has_issues(self):
        return bool(self.warnings or self.color_failures)

    def all_messages(self):
        msgs = [w["message"] for w in self.warnings] + list(self.color_failures)
        summary = self.stats_summary()
        if summary:
            msgs.insert(0, summary)
        return msgs


def _schedule_base_name(fname):
    lower = fname.lower()
    if lower.endswith(".xlsx"):
        return fname[:-5]
    if lower.endswith(".xls"):
        return fname[:-4]
    return fname


def _is_xls(fname):
    return fname.lower().endswith(".xls") and not fname.lower().endswith(".xlsx")


def _is_xlsx(fname):
    return fname.lower().endswith(".xlsx")


def _list_schedule_files(report=None):
    """Список файлов графиков с приоритетом .xlsx над парным .xls."""
    schedules_dir = get_schedules_dir()
    if not os.path.isdir(schedules_dir):
        return [], {"xlsx": 0, "xls": 0, "skipped_dup": 0}

    all_files = [
        f
        for f in os.listdir(schedules_dir)
        if f.lower().endswith((".xls", ".xlsx"))
    ]
    by_base = {}
    for f in all_files:
        base = _schedule_base_name(f).lower()
        by_base.setdefault(base, []).append(f)

    chosen = []
    skipped = 0
    prefer_xlsx = CONFIG.get("prefer_xlsx", True)

    for variants in by_base.values():
        xlsx_files = [v for v in variants if _is_xlsx(v)]
        xls_files = [v for v in variants if _is_xls(v)]
        if prefer_xlsx and xlsx_files and xls_files:
            chosen.extend(sorted(xlsx_files))
            skipped += len(xls_files)
            if report:
                for x in xls_files:
                    report.add_once(
                        "dup_skipped",
                        f"Пропущен «{x}» — используется одноимённый .xlsx",
                    )
        elif xlsx_files:
            chosen.extend(sorted(xlsx_files))
        else:
            chosen.extend(sorted(xls_files))

    if CONFIG.get("warn_on_xls", True) and report:
        for f in chosen:
            if _is_xls(f):
                report.add_once(
                    "xls_legacy",
                    f"«{f}» — .xls (медленный COM-анализ; рекомендуется .xlsx)",
                )

    stats = {
        "xlsx": sum(1 for f in chosen if _is_xlsx(f)),
        "xls": sum(1 for f in chosen if _is_xls(f)),
        "skipped_dup": skipped,
    }
    return sorted(chosen), stats


def schedules_need_com_excel():
    """Excel обязателен, если найден хотя бы один график ППР."""
    fnames, stats = _list_schedule_files(None)
    return bool(fnames and (stats.get("xls", 0) or stats.get("xlsx", 0)))


def _schedule_uses_com_color(fname, color_session):
    if color_session is None:
        return False
    return _is_xls(fname) or _is_xlsx(fname)


def normalize_work_text(text):
    return " ".join(str(text).split())


def _parse_plan_day(value):
    if not pd.notna(value):
        return None
    value_text = str(value).strip()
    if value_text in ("", "36"):
        return None
    import re
    match = re.search(r"^\s*(\d+)", value_text)
    try:
        day = int(match.group(1)) if match else int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None
    return day if 1 <= day <= 31 else None


def _excel_a1(row_zero_based, col_zero_based):
    number = int(col_zero_based) + 1
    letters = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return f"{letters}{int(row_zero_based) + 1}"


def format_ppr_task(pos, si, model, zav):
    mod = str(model).strip() if pd.notna(model) else ""
    p_str = str(pos).strip() if pd.notna(pos) else ""
    z_str = str(zav).strip() if pd.notna(zav) else ""
    s_str = str(si).strip() if pd.notna(si) else ""
    if z_str.endswith(".0"):
        z_str = z_str[:-2]

    if "мэо" in mod.lower() or "мэо" in s_str.lower():
        pf = p_str.lower().replace("печь", "печи") if "печь" in p_str.lower() else p_str.lower()
        qty = z_str if z_str else "несколько шт."
        return normalize_work_text(
            f"Выполнить ППР приборам МЭО {qty} на {pf}. Оформить документацию."
        )
    dev = mod if mod else s_str
    zp = (
        f" №{z_str}"
        if z_str and not (z_str.startswith("№") or z_str.lower().startswith("зав"))
        else f" {z_str}" if z_str else ""
    )
    return normalize_work_text(f"Выполнить ППР прибору {dev}{zp}. Оформить документацию.")


def is_plan_cell_colored_xlrd(wb, ws, row, col):
    try:
        row, col = int(row), int(col)
        if row >= ws.nrows or col >= ws.ncols:
            return False
        xfx = ws.cell_xf_index(row, col)
        xf = wb.xf_list[xfx]
        bg = xf.background
        if bg.fill_pattern == 0:
            return False
        return bg.pattern_colour_index not in DEFAULT_BG_INDICES
    except Exception:
        return False


def _rgb_is_white_or_empty(rgb_val):
    val = (rgb_val or "").upper()
    if not val:
        return True
    if val in ("FFFFFFFF", "FFFFFF", "00000000", "FF000000"):
        return True
    if len(val) >= 6 and val[-6:] in ("FFFFFF",):
        return True
    return False


def _openpyxl_color_is_default(color):
    if not color:
        return True
    ctype = color.type
    if ctype == "indexed":
        return color.indexed in DEFAULT_BG_INDICES
    if ctype == "rgb":
        return _rgb_is_white_or_empty(color.rgb)
    if ctype == "theme":
        if hasattr(color, 'theme') and color.theme in (0, 1):
            return True
        return False
    return False


def _scan_openpyxl_colored_set(ws):
    """Один проход по зоне плана — быстрее, чем COM по каждой ячейке."""
    colored = set()
    max_row = min(ws.max_row or 0, DATA_ROW_END + 1)
    for row in range(DATA_ROW_START, max_row):
        for col in range(PLAN_COL_START, PLAN_COL_END + 1):
            if is_plan_cell_colored_openpyxl(ws, row, col):
                colored.add((row, col))
    return colored


def is_plan_cell_colored_openpyxl(ws, row, col):
    try:
        row, col = int(row), int(col)
        cell = ws.cell(row=row + 1, column=col + 1)
        fill = cell.fill
        if not fill or fill.patternType in (None, "none"):
            return False
            
        if fill.fgColor and not _openpyxl_color_is_default(fill.fgColor):
            return True
            
        if fill.patternType != "solid" and fill.bgColor and not _openpyxl_color_is_default(fill.bgColor):
            return True
            
        return False
    except Exception:
        return False


def _worksheet_to_dataframe(ws):
    import pandas as pd
    rows = [list(row) for row in ws.iter_rows(values_only=True)]
    if not rows:
        return pd.DataFrame()
    max_cols = max(len(r) for r in rows)
    padded = [list(r) + [None] * (max_cols - len(r)) for r in rows]
    return pd.DataFrame(padded)


def _detect_schedule_period(fname, num_plan_cols):
    import re
    compact = re.sub(r"\s+", "", fname.lower())
    if "iiпол" in compact or "2пол" in compact:
        return 6, 6, "II полугодие (июль–декабрь)"
    if "iпол" in compact or "1пол" in compact:
        return 0, 6, "I полугодие (январь–июнь)"
    if num_plan_cols >= 12:
        return 0, 12, "год (12 месяцев)"
    if num_plan_cols == 6:
        return 0, 6, "полугодие (6 месяцев, январь–июнь)"
    return 0, num_plan_cols, f"{num_plan_cols} месяцев"


def _plan_column_for_month(t_month, p_cols, fname):
    num_cols = len(p_cols)
    month_offset, span, period_label = _detect_schedule_period(fname, num_cols)
    if span == 6:
        if t_month <= month_offset or t_month > month_offset + 6:
            return None, period_label
        return p_cols[t_month - month_offset - 1], period_label
    if t_month < 1 or t_month > num_cols:
        return None, period_label
    return p_cols[t_month - 1], period_label


def _normalize_workshop_name(sheet_name, fname):
    w_n = str(sheet_name).strip()
    if w_n.lower().startswith(("лист", "sheet")):
        w_n = fname.split("-")[-1].replace(".xls", "").replace(".xlsx", "").strip()
    if "цех" not in w_n.lower() and "исм" not in w_n.lower():
        w_n = f"Цех № {w_n}"
    elif "цех" in w_n.lower() and "обслуживания" not in w_n.lower():
        cl = w_n.lower().replace("цех", "").replace("№", "").strip()
        w_n = f"Цех № {cl.upper()}" if cl else "Цех"
    elif w_n.lower() == "исм":
        w_n = "ИСМ"
    return w_n


def _task_key(place, plan_day, work):
    return (place, int(plan_day), normalize_work_text(work))


def make_signature(place, plan_day, work, assigned_day=None, plan_month=None, plan_year=None):
    sig = f"{place} | План: {plan_day} | {normalize_work_text(work)}"
    if plan_month is not None and plan_year is not None:
        sig += f" | Период: {int(plan_month):02d}.{int(plan_year):04d}"
    if assigned_day is not None and int(assigned_day) != int(plan_day):
        sig += f" | Выдано: {assigned_day}"
    return sig


def make_history_line(assigned_date_str, task, status="Выполнено"):
    plan_day = task.get("plan_day", task.get("original_day"))
    assigned_day = task.get("assigned_day", plan_day)
    try:
        assigned_date = datetime.strptime(assigned_date_str, "%d.%m.%Y")
        plan_month = task.get("plan_month", assigned_date.month)
        plan_year = task.get("plan_year", assigned_date.year)
    except ValueError:
        plan_month = task.get("plan_month")
        plan_year = task.get("plan_year")
    sig = make_signature(
        task["place"], plan_day, task["work"], assigned_day, plan_month, plan_year
    )
    executor = str(task.get("executor", "")).strip()
    if executor:
        sig += f" | Исполнитель: {executor}"
    sig += f" | Статус: {status}"
    return f"[{assigned_date_str}] | {sig}"


def _history_canonical_and_status(full_line):
    signature = full_line.split("] | ", 1)[1] if "] | " in full_line else full_line
    status_match = re.search(rf" \| Статус: {_PPR_STATUS_RE}\s*$", signature)
    status = status_match.group(1) if status_match else "Выполнено"
    signature = re.sub(rf" \| Статус: {_PPR_STATUS_RE}\s*$", "", signature)
    if " | Период:" not in signature:
        hist_date = _history_date_from_line(full_line)
        if hist_date is not None:
            marker = " | Выдано:"
            if marker in signature:
                base, tail = signature.split(marker, 1)
                signature = (
                    f"{base} | Период: {hist_date.month:02d}.{hist_date.year:04d}"
                    f"{marker}{tail}"
                )
            else:
                signature += f" | Период: {hist_date.month:02d}.{hist_date.year:04d}"
    signature = re.sub(r" \| Исполнитель:.*$", "", signature)
    if " | Выдано:" in signature:
        signature = signature.split(" | Выдано:")[0]
    return signature, status


def _replace_history_status(line, status):
    if re.search(rf" \| Статус: {_PPR_STATUS_RE}\s*$", line):
        return re.sub(
            rf" \| Статус: {_PPR_STATUS_RE}\s*$",
            f" | Статус: {status}",
            line,
        )
    return line.rstrip() + f" | Статус: {status}"


def record_tasks_status(task_groups, status):
    """Идемпотентно переводит ППР между рабочими состояниями."""
    if status not in PPR_STATUSES:
        raise ValueError(f"Неизвестный статус ППР: {status}")
    history_file = get_history_file()
    existing_lines = list(_iter_history_entries())
    by_canonical = {}
    for index, line in enumerate(existing_lines):
        canonical, old_status = _history_canonical_and_status(line)
        by_canonical[canonical] = (index, old_status)
    added_lines = []
    skipped = 0
    updated = 0
    events = []

    for assigned_date_str, tasks in task_groups:
        try:
            assigned_date = datetime.strptime(assigned_date_str, "%d.%m.%Y")
        except ValueError:
            raise ValueError(f"Некорректная дата напечатанного ССЗ: {assigned_date_str}")
        for task in tasks or []:
            if task.get("task_kind") != "ppr" and "plan_day" not in task:
                continue
            plan_day = task.get("plan_day", task.get("original_day"))
            plan_month = task.get("plan_month", assigned_date.month)
            plan_year = task.get("plan_year", assigned_date.year)
            canonical = make_signature(
                task["place"], plan_day, task["work"],
                plan_month=plan_month, plan_year=plan_year,
            )
            current = by_canonical.get(canonical)
            if current is not None:
                index, old_status = current
                if status == old_status:
                    skipped += 1
                    continue
                if status == "Выдано" and old_status in ("Не выполнено", "Отменено"):
                    existing_lines[index] = make_history_line(
                        assigned_date_str, task, status="Выдано"
                    )
                    updated += 1
                    by_canonical[canonical] = (index, status)
                    events.append((canonical, status, assigned_date_str, task.get("executor", "")))
                elif status in ("Выполнено", "Не выполнено", "Отменено"):
                    existing_lines[index] = _replace_history_status(existing_lines[index], status)
                    updated += 1
                    by_canonical[canonical] = (index, status)
                    events.append((canonical, status, assigned_date_str, task.get("executor", "")))
                else:
                    skipped += 1
                continue
            line = make_history_line(assigned_date_str, task, status=status)
            added_lines.append(line)
            by_canonical[canonical] = (len(existing_lines) + len(added_lines) - 1, status)
            events.append((canonical, status, assigned_date_str, task.get("executor", "")))

    if not added_lines and not updated:
        return {"added": 0, "updated": 0, "skipped": skipped}

    temp_file = history_file + ".tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as stream:
            for line in existing_lines + added_lines:
                stream.write(line + "\n")
        os.replace(temp_file, history_file)
    finally:
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except OSError:
                pass
    if events:
        try:
            from data_manager import _init_db_tables, get_conn
            conn = get_conn()
            _init_db_tables(conn)
            conn.executemany(
                """
                INSERT INTO ppr_events(task_key,event_type,event_at,assigned_date,executor)
                VALUES (?,?,CURRENT_TIMESTAMP,?,?)
                """,
                events,
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            log_operation("ppr_event_log_error", str(exc))
    return {"added": len(added_lines), "updated": updated, "skipped": skipped}


def record_issued_tasks(printed_groups):
    """Отмечает подтверждённые печатью ППР как выданные."""
    return record_tasks_status(printed_groups, "Выдано")


def record_completed_tasks(task_groups):
    """Переводит ППР в состояние «Выполнено» (совместимый API)."""
    return record_tasks_status(task_groups, "Выполнено")


def record_not_completed_tasks(task_groups):
    """Возвращает выданный ППР в очередь для повторной выдачи."""
    return record_tasks_status(task_groups, "Не выполнено")


def record_cancelled_tasks(task_groups):
    return record_tasks_status(task_groups, "Отменено")


def _history_date_from_line(full_line):
    import re
    from datetime import datetime
    m = re.match(r"^\[(\d{2}\.\d{2}\.\d{4})\]", full_line.strip())
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%d.%m.%Y").date()
    except ValueError:
        return None


def _iter_history_entries():
    history_file = get_history_file()
    if not os.path.exists(history_file):
        return
    try:
        with open(history_file, "r", encoding="utf-8") as f:
            raw_lines = f.readlines()
    except Exception:
        return

    i = 0
    while i < len(raw_lines):
        line = raw_lines[i].rstrip("\n\r")
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if not _HISTORY_LINE_RE.match(stripped):
            i += 1
            continue

        full_line = stripped
        j = i + 1
        while j < len(raw_lines):
            nxt = raw_lines[j].strip()
            if not nxt or _HISTORY_LINE_RE.match(nxt):
                break
            full_line += " " + nxt
            j += 1
        i = j
        yield full_line


def count_history_in_period(start_date, end_date):
    from datetime import datetime
    if isinstance(start_date, datetime):
        start_date = start_date.date()
    if isinstance(end_date, datetime):
        end_date = end_date.date()
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    n = 0
    for full_line in _iter_history_entries():
        d = _history_date_from_line(full_line)
        if d is not None and start_date <= d <= end_date:
            n += 1
    return n


def clear_history_for_period(start_date, end_date):
    from datetime import datetime
    if isinstance(start_date, datetime):
        start_date = start_date.date()
    if isinstance(end_date, datetime):
        end_date = end_date.date()
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    kept = []
    removed = 0
    for full_line in _iter_history_entries():
        d = _history_date_from_line(full_line)
        if d is not None and start_date <= d <= end_date:
            removed += 1
        else:
            kept.append(full_line)

    try:
        history_file = get_history_file()
        with open(history_file, "w", encoding="utf-8") as f:
            for line in kept:
                f.write(line + "\n")
    except Exception as e:
        raise OSError(f"Не удалось записать {get_history_file()}: {e}") from e

    return removed, len(kept)


def get_filtered_history(ignore_dates_str_set):
    kept = []
    completed = set()
    for full_line in _iter_history_entries():
        is_ignored = any(full_line.startswith(f"[{d}]") for d in ignore_dates_str_set)
        if not is_ignored:
            kept.append(full_line)
            canonical, status = _history_canonical_and_status(full_line)
            if status in ("Выдано", "Выполнено", "Отменено"):
                completed.add(canonical)

    return kept, completed


def get_ppr_history_records():
    """Структурированное представление совместимой текстовой истории."""
    records = []
    for line in _iter_history_entries():
        try:
            parts = line.split(" | ")
            assigned_date = _history_date_from_line(line)
            if assigned_date is None or len(parts) < 4:
                continue
            canonical, status = _history_canonical_and_status(line)
            plan_text = parts[2].replace("План:", "").strip()
            plan_day = int(plan_text)
            period_match = re.search(r"\| Период: (\d{2})\.(\d{4})", line)
            plan_month = int(period_match.group(1)) if period_match else assigned_date.month
            plan_year = int(period_match.group(2)) if period_match else assigned_date.year
            executor = next(
                (
                    part.replace("Исполнитель:", "", 1).strip()
                    for part in parts if part.strip().startswith("Исполнитель:")
                ),
                "",
            )
            records.append({
                "canonical": canonical,
                "status": status,
                "assigned_date": assigned_date,
                "task": {
                    "task_kind": "ppr",
                    "place": parts[1].strip(),
                    "plan_day": plan_day,
                    "plan_month": plan_month,
                    "plan_year": plan_year,
                    "work": parts[3].strip(),
                    "executor": executor,
                    "assigned_date": assigned_date,
                    "status": status,
                },
                "line": line,
            })
        except (ValueError, IndexError):
            continue
    return records


def _dedupe_tasks(tasks):
    seen = set()
    out = []
    for t in tasks:
        key = _task_key(t["place"], t["plan_day"], t["work"])
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def _dedupe_colored(colored_skipped):
    seen = set()
    out = []
    for p in colored_skipped:
        key = (p["month"], p["day"], p["place"], normalize_work_text(p["work"]))
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def redistribute_schedule(sch, moved_log, t_month, target_day=1, t_year=None):
    from ssz_config import CONFIG
    max_p = int(CONFIG.get("max_ppr_per_day", 2))
    t_year = int(t_year or datetime.now().year)
    days_in_month = calendar.monthrange(t_year, int(t_month))[1]
    valid_days = list(range(1, days_in_month + 1))
    target_day = min(max(int(target_day or 1), 1), days_in_month)
    assignment_days = list(range(target_day, days_in_month + 1))

    from ssz_utils import get_day_executors, get_executor
    from staff_schedule import is_staff_available

    all_tasks = []
    for day in sorted(sch):
        all_tasks.extend(dict(t) for t in sch.get(day, []))
    unsafe = [
        task
        for task in all_tasks
        if task.get("task_kind") == "ppr" and task.get("color_state") != "uncolored"
    ]
    if unsafe:
        raise PprSafetyError(
            "Распределение заблокировано: в него попали ППР без подтверждённого допуска по цвету"
        )
    all_tasks.sort(key=lambda t: (int(t.get("plan_day", 1)), t.get("place", ""), t.get("work", "")))
    result = {d: [] for d in valid_days}
    counts = {d: {} for d in valid_days}

    def ordered_days(plan_day):
        plan_day = min(max(int(plan_day), target_day), days_in_month)
        return sorted(
            assignment_days,
            key=lambda day: (abs(day - plan_day), day > plan_day, day),
        )

    def assign(task, day, executor):
        plan = int(task.get("plan_day", day))
        task["plan_day"] = plan
        task["original_day"] = plan
        task["assigned_day"] = day
        task["plan_month"] = int(t_month)
        task["plan_year"] = t_year
        task["executor"] = executor
        task["signature"] = make_signature(
            task["place"], plan, task["work"], day, t_month, t_year
        )
        result[day].append(task)
        counts[day][executor] = counts[day].get(executor, 0) + 1
        primary = get_executor(date(t_year, int(t_month), day))
        if day != plan or executor != primary:
            moved_log.append(
                {
                    "plan_day": plan, "assigned_day": day, "place": task["place"],
                    "work": task["work"], "month": t_month, "year": t_year,
                    "executor": executor,
                    "reserve_assignment": executor != primary,
                }
            )

    overflow = []
    # Сначала резервируем плановые даты. Перенос на соседние дни на этом этапе
    # запрещён: иначе избыток одного дня может занять дату другого планового ППР
    # и запустить каскад необязательных переносов.
    for task in all_tasks:
        plan_day = min(max(int(task.get("plan_day", 1)), 1), days_in_month)
        if plan_day < target_day:
            overflow.append(task)
            continue
        primary = get_executor(date(t_year, int(t_month), plan_day))
        if counts[plan_day].get(primary, 0) < max_p:
            assign(task, plan_day, primary)
        else:
            overflow.append(task)

    # Перераспределяем только то, что нельзя выполнить в плановую дату:
    # превышение лимита либо просроченный план до начала выбранного периода.
    reserve_overflow = []
    for task in overflow:
        placed = False
        for day in ordered_days(task.get("plan_day", 1)):
            primary = get_executor(date(t_year, int(t_month), day))
            if counts[day].get(primary, 0) < max_p:
                assign(task, day, primary)
                placed = True
                break
        if not placed:
            reserve_overflow.append(task)

    # Только остаток, не поместившийся дежурным, отдаётся резерву.
    reserve_config = [
        CONFIG.get("overflow_executor", ""),
        CONFIG.get("executor_1", ""),
        CONFIG.get("executor_2", ""),
    ]
    unassigned = []
    for task in reserve_overflow:
        placed = False
        for day in ordered_days(task.get("plan_day", 1)):
            work_date = date(t_year, int(t_month), day)
            primary = get_executor(work_date)
            available_reserve = get_day_executors(work_date) + [
                name for name in reserve_config if is_staff_available(name, work_date)
            ]
            for executor in dict.fromkeys(x.strip() for x in available_reserve if str(x).strip()):
                if executor == primary:
                    continue
                if counts[day].get(executor, 0) < max_p:
                    assign(task, day, executor)
                    placed = True
                    break
            if placed:
                break
        if not placed:
            unassigned.append(task)

    if unassigned:
        raise RuntimeError(
            f"Не удалось распределить {len(unassigned)} ППР за {t_month:02d}.{t_year}: "
            f"исчерпана емкость исполнителей при лимите {max_p} ППР/чел./день"
        )

    sch.clear()
    sch.update(result)
    return sch


def _find_plan_layout(df):
    for row_idx, row in df.iterrows():
        plan_columns = [
            column
            for column, value in row.items()
            if str(value).strip().lower() == "план"
        ]
        if len(plan_columns) >= 6:
            return int(row_idx), list(plan_columns)
    return -1, []


def _find_equipment_columns(df, plan_row):
    columns = {"position": 1, "instrument": 2, "model": 3, "serial": 4}
    for row_idx in range(max(0, plan_row - 3), plan_row + 1):
        for column_idx, value in df.iloc[row_idx].items():
            text = str(value).lower()
            if "позиция" in text:
                columns["position"] = column_idx
            elif "си" in text or "прибор" in text:
                columns["instrument"] = column_idx
            elif "тип" in text or "модель" in text:
                columns["model"] = column_idx
            elif "заводской" in text or "зав" in text:
                columns["serial"] = column_idx
    return columns


def _collect_plan_cell_coords(df, sheet, plan_row, plan_columns):
    coordinates = set()
    for row_idx in range(plan_row + 1, len(df)):
        for plan_column in plan_columns:
            if _parse_plan_day(df.iloc[row_idx, plan_column]) is not None:
                coordinates.add((str(sheet), int(row_idx), int(plan_column)))
    return coordinates


def _source_metadata(fpath, sheet, row, column):
    return {
        "source_file": os.path.abspath(fpath),
        "source_sheet": str(sheet),
        "source_cell": _excel_a1(row, column),
    }


def _process_sheet_rows(
    df,
    sheet,
    fname,
    t_month,
    t_year,
    w_n,
    completed_signatures,
    all_tasks,
    colored_skipped,
    com_cells_by_file,
    com_task_refs,
    fpath,
    color_wb_xlrd,
    c_ws_xlrd,
    c_ws_op,
    color_session,
    report,
    c_colored_set=None,
):
    """Общая логика разбора одного листа графика."""
    p_row, p_cols = _find_plan_layout(df)
    if p_row == -1:
        report.add_once("no_plan_row", f"«{fname}» / «{sheet}»: строка «План» не найдена")
        return

    t_col, period_label = _plan_column_for_month(t_month, p_cols, fname)
    if t_col is None:
        report.add_once(
            "month_cols",
            f"«{fname}» ({period_label}): нет колонки для месяца {t_month}",
        )
        return

    equipment_columns = _find_equipment_columns(df, p_row)
    pos_c = equipment_columns["position"]
    si_c = equipment_columns["instrument"]
    mod_c = equipment_columns["model"]
    zav_c = equipment_columns["serial"]

    # Warm the cache for every plan month in one Excel launch.  The old code
    # started a separate COM process per month; collecting only real plan
    # cells here keeps later month analyses both correct and fast.
    if _schedule_uses_com_color(fname, color_session):
        com_cells_by_file.setdefault(fpath, set()).update(
            _collect_plan_cell_coords(df, sheet, p_row, p_cols)
        )

    for r_idx in range(p_row + 1, len(df)):
        val = df.iloc[r_idx, t_col]
        d_v = _parse_plan_day(val)
        if d_v is not None:
            report.stats["ppr_candidates"] += 1
            try:
                excel_row = int(r_idx)
                excel_col = int(t_col)
                txt = format_ppr_task(
                    df.iloc[r_idx, pos_c],
                    df.iloc[r_idx, si_c],
                    df.iloc[r_idx, mod_c],
                    df.iloc[r_idx, zav_c],
                )
                source = _source_metadata(fpath, sheet, excel_row, excel_col)

                is_colored = False
                if c_ws_xlrd:
                    is_colored = is_plan_cell_colored_xlrd(
                        color_wb_xlrd, c_ws_xlrd, excel_row, excel_col
                    )
                elif c_ws_op:
                    if c_colored_set is not None:
                        is_colored = (excel_row, excel_col) in c_colored_set
                    else:
                        is_colored = is_plan_cell_colored_openpyxl(
                            c_ws_op, excel_row, excel_col
                        )
                    if is_colored:
                        report.stats["openpyxl_colored"] += 1

                if is_colored:
                    colored_skipped.append(
                        {
                            "day": d_v,
                            "month": t_month,
                            "year": t_year,
                            "plan_date": f"{t_year:04d}-{t_month:02d}-{d_v:02d}",
                            "assigned_date": None,
                            "place": w_n,
                            "work": txt,
                            "color_state": "colored",
                            "color_source": "openpyxl_or_xlrd_fill",
                            **source,
                        }
                    )
                    log_operation(
                        "ppr_color_skip",
                        f"{fname}::{sheet}!{source['source_cell']} "
                        f"plan={t_year:04d}-{t_month:02d}-{d_v:02d} {txt}",
                    )
                    continue

                sig = make_signature(w_n, d_v, txt, plan_month=t_month, plan_year=t_year)
                history_only = sig in completed_signatures
                # Для COM-проверки задача из истории всё равно нужна как ссылка
                # на ячейку цвета, но в распределение она попасть не должна.
                if history_only and not _schedule_uses_com_color(fname, color_session):
                    continue

                task = {
                    "task_kind": "ppr",
                    "plan_day": d_v,
                    "original_day": d_v,
                    "assigned_day": d_v,
                    "plan_month": t_month,
                    "plan_year": t_year,
                    "plan_date": f"{t_year:04d}-{t_month:02d}-{d_v:02d}",
                    "assigned_date": f"{t_year:04d}-{t_month:02d}-{d_v:02d}",
                    "work": txt,
                    "place": w_n,
                    "signature": sig,
                    "_history_only": history_only,
                    "color_state": (
                        "unknown"
                        if _schedule_uses_com_color(fname, color_session)
                        else "uncolored"
                    ),
                    "color_source": (
                        "pending_excel_display_format"
                        if _schedule_uses_com_color(fname, color_session)
                        else "openpyxl_or_xlrd_fill"
                    ),
                    **source,
                }
                task_idx = len(all_tasks)
                all_tasks.append(task)

                if _schedule_uses_com_color(fname, color_session):
                    coord = (sheet, excel_row, excel_col)
                    com_cells_by_file.setdefault(fpath, set()).add(coord)
                    com_task_refs.append((fpath, coord, task_idx))
            except (ValueError, IndexError) as exc:
                report.add_once(
                    "row_parse",
                    f"«{fname}» / «{sheet}», строка {int(r_idx) + 1}: {exc}",
                )


def _fetch_one_file_colored(
    fpath,
    t_month,
    completed_signatures,
    color_session=None,
    report=None,
    t_year=None,
):
    import pandas as pd
    from openpyxl import load_workbook
    """colored_skipped только из одного файла (для audit)."""
    if report is None:
        report = AnalysisReport()
    fname = os.path.basename(fpath)
    t_year = int(t_year or datetime.now().year)
    all_tasks = []
    colored_skipped = []
    com_cells_by_file = {}
    com_task_refs = []

    color_wb_xlrd = None
    color_wb_openpyxl = None
    xls = None
    try:
        if _is_xls(fname):
            import xlrd
            color_wb_xlrd = xlrd.open_workbook(fpath, formatting_info=True)
            xls = pd.ExcelFile(fpath)
            sheet_names = xls.sheet_names
        else:
            color_wb_openpyxl = load_workbook(fpath, data_only=True)
            sheet_names = color_wb_openpyxl.sheetnames

        for sheet in sheet_names:
            w_n = _normalize_workshop_name(sheet, fname)
            c_colored_set = None
            if _is_xlsx(fname):
                ws = color_wb_openpyxl[sheet]
                df = _worksheet_to_dataframe(ws)
                c_ws_op = ws
                c_ws_xlrd = None
                c_colored_set = _scan_openpyxl_colored_set(ws)
            else:
                df = pd.read_excel(xls, sheet_name=sheet, header=None)
                c_ws_xlrd = (
                    color_wb_xlrd.sheet_by_name(sheet)
                    if color_wb_xlrd and sheet in color_wb_xlrd.sheet_names()
                    else None
                )
                c_ws_op = None
            _process_sheet_rows(
                df,
                sheet,
                fname,
                t_month,
                t_year,
                w_n,
                completed_signatures,
                all_tasks,
                colored_skipped,
                com_cells_by_file,
                com_task_refs,
                fpath,
                color_wb_xlrd,
                c_ws_xlrd,
                c_ws_op,
                color_session,
                report,
                c_colored_set=c_colored_set,
            )

        if com_cells_by_file and color_session is not None:
            for fpath2, cells in com_cells_by_file.items():
                colored_coords = color_session.check_cells(
                    fpath2, cells, cancel_check=None, progress_cb=None
                )
                for fp, coord, task_idx in com_task_refs:
                    if fp != fpath2:
                        continue
                    if coord in colored_coords:
                        task = all_tasks[task_idx]
                        if task is not None:
                            report.stats["com_colored_added"] += 1
                            colored_skipped.append(
                                {
                                    "day": task["plan_day"],
                                    "month": t_month,
                                    "place": task["place"],
                                    "work": task["work"],
                                }
                            )
    finally:
        if xls is not None:
            try:
                xls.close()
            except Exception:
                pass
        if color_wb_openpyxl is not None:
            try:
                color_wb_openpyxl.close()
            except Exception:
                pass

    return _dedupe_colored(colored_skipped)


def fetch_month_schedules(
    t_month,
    completed_signatures,
    report=None,
    color_session=None,
    cancel_check=None,
    progress_cb=None,
    target_day=1,
    t_year=None,
):
    import pandas as pd
    from openpyxl import load_workbook
    if report is None:
        report = AnalysisReport()
    t_year = int(t_year or datetime.now().year)
    schedules_dir = get_schedules_dir()
    if not os.path.isdir(schedules_dir):
        report.add("no_dir", f"Папка «{schedules_dir}» не найдена")
        return {d: [] for d in range(1, 32)}, [], []

    phase_t0 = time.monotonic()
    fnames, file_stats = _list_schedule_files(report)
    report.stats["xlsx_files"] += file_stats["xlsx"]
    report.stats["xls_files"] += file_stats["xls"]
    if fnames and color_session is None:
        raise PprSafetyError(
            "Проверка видимого цвета Excel не запущена. Анализ и генерация ППР заблокированы."
        )

    log_operation(
        "phase_start",
        f"month={t_month} files={len(fnames)} xlsx={file_stats['xlsx']} "
        f"xls={file_stats['xls']}",
    )

    all_tasks = []
    colored_skipped = []
    com_cells_by_file = {}
    com_task_refs = []
    total_files = len(fnames)

    for fi, fname in enumerate(fnames, 1):
        if cancel_check and cancel_check():
            return {d: [] for d in range(1, 32)}, colored_skipped, []
        if progress_cb:
            progress_cb(fi, total_files, f"Чтение {fname}…")

        fpath = os.path.join(schedules_dir, fname)
        file_t0 = time.monotonic()
        color_wb_xlrd = None
        color_wb_openpyxl = None
        xls = None

        if cancel_check and cancel_check():
            return {d: [] for d in range(1, 32)}, colored_skipped, []

        try:
            if _is_xls(fname):
                try:
                    import xlrd
                    color_wb_xlrd = xlrd.open_workbook(fpath, formatting_info=True)
                except Exception as e:
                    report.add("format_error", f"«{fname}»: форматирование ({e})")
                xls = pd.ExcelFile(fpath)
                sheet_names = xls.sheet_names
            else:
                color_wb_openpyxl = load_workbook(fpath, data_only=True)
                sheet_names = color_wb_openpyxl.sheetnames

            num_sheets = len(sheet_names)
            for si, sheet in enumerate(sheet_names, 1):
                if cancel_check and cancel_check():
                    return {d: [] for d in range(1, 32)}, colored_skipped, []
                if progress_cb:
                    progress_cb(
                        fi,
                        total_files,
                        f"{fname}: лист {si}/{num_sheets} «{sheet}»…",
                    )
                w_n = _normalize_workshop_name(sheet, fname)

                c_colored_set = None
                if _is_xlsx(fname):
                    ws = color_wb_openpyxl[sheet]
                    df = _worksheet_to_dataframe(ws)
                    c_ws_op = ws
                    c_ws_xlrd = None
                    c_colored_set = _scan_openpyxl_colored_set(ws)
                else:
                    df = pd.read_excel(xls, sheet_name=sheet, header=None)
                    c_ws_xlrd = (
                        color_wb_xlrd.sheet_by_name(sheet)
                        if color_wb_xlrd and sheet in color_wb_xlrd.sheet_names()
                        else None
                    )
                    c_ws_op = None

                _process_sheet_rows(
                    df,
                    sheet,
                    fname,
                    t_month,
                    t_year,
                    w_n,
                    completed_signatures,
                    all_tasks,
                    colored_skipped,
                    com_cells_by_file,
                    com_task_refs,
                    fpath,
                    color_wb_xlrd,
                    c_ws_xlrd,
                    c_ws_op,
                    color_session,
                    report,
                    c_colored_set=c_colored_set,
                )

            elapsed = time.monotonic() - file_t0
            log_operation(
                "file_read",
                f"{fname} sheets={num_sheets} elapsed={elapsed:.1f}s",
            )
        except Exception as e:
            raise PprSafetyError(f"Не удалось полностью прочитать график «{fname}»: {e}") from e
        finally:
            if xls is not None:
                try:
                    xls.close()
                except Exception:
                    pass
            if color_wb_openpyxl is not None:
                try:
                    color_wb_openpyxl.close()
                except Exception:
                    pass
            color_wb_xlrd = None

    if cancel_check and cancel_check():
        return {d: [] for d in range(1, 32)}, colored_skipped, []

    if com_cells_by_file and color_session is not None:
        com_items = list(com_cells_by_file.items())
        total_com = sum(len(c) for _, c in com_items)
        report.stats["com_cells"] += total_com
        report.stats["color_cells_required"] += total_com
        if total_com <= 0 and all_tasks:
            raise PprSafetyError(
                "Найденные ППР не были переданы на проверку цвета Excel. Генерация заблокирована."
            )
        checked_at = utc_now_iso()
        analysis_id = uuid.uuid4().hex
        fingerprints = {fpath: source_fingerprint(fpath) for fpath, _cells in com_items}
        for ci, (fpath, cells) in enumerate(com_items, 1):
            if cancel_check and cancel_check():
                return {d: [] for d in range(1, 32)}, colored_skipped, []
            if progress_cb:
                progress_cb(
                    ci,
                    len(com_items),
                    f"Цвета Excel: {os.path.basename(fpath)} ({len(cells)} яч.)",
                )
            com_t0 = time.monotonic()
            colored_coords = color_session.check_cells(
                fpath, cells, cancel_check, progress_cb=progress_cb
            )
            log_operation(
                "com_batch",
                f"{os.path.basename(fpath)} cells={len(cells)} "
                f"elapsed={time.monotonic() - com_t0:.1f}s",
            )
            for fpath2, coord, task_idx in com_task_refs:
                if fpath2 != fpath:
                    continue
                if coord in colored_coords:
                    task = all_tasks[task_idx]
                    if task is not None:
                        report.stats["com_colored_added"] += 1
                        colored_skipped.append(
                            {
                                "day": task["plan_day"],
                                "month": t_month,
                                "year": t_year,
                                "plan_date": task.get("plan_date"),
                                "assigned_date": None,
                                "place": task["place"],
                                "work": task["work"],
                                "color_state": "colored",
                                "color_source": "excel_display_format",
                                "source_file": task.get("source_file", ""),
                                "source_sheet": task.get("source_sheet", ""),
                                "source_cell": task.get("source_cell", ""),
                            }
                        )
                        log_operation(
                            "ppr_color_skip",
                            f"{os.path.basename(task.get('source_file', ''))}::"
                            f"{task.get('source_sheet', '')}!{task.get('source_cell', '')} "
                            f"plan={task.get('plan_date', '')} {task.get('work', '')}",
                        )
                        all_tasks[task_idx] = None
                else:
                    task = all_tasks[task_idx]
                    if task is not None:
                        task["color_state"] = "uncolored"
                        task["color_source"] = "excel_display_format"
                        task["color_checked_at"] = checked_at
                        task["analysis_id"] = analysis_id
                        task["source_fingerprint"] = dict(fingerprints[fpath])
        report.merge_color_failures(color_session.failures)
        log_operation(
            "color_validation",
            f"analysis_id={analysis_id} required={total_com} checked={total_com} "
            f"candidates={report.stats['ppr_candidates']} status=complete",
        )
    elif all_tasks:
        raise PprSafetyError(
            "ППР найдены, но полная проверка видимого цвета Excel не выполнена."
        )

    all_tasks = [
        t for t in all_tasks
        if t is not None and not t.get("_history_only")
    ]
    all_tasks = _dedupe_tasks(all_tasks)
    colored_skipped = _dedupe_colored(colored_skipped)

    sch = {d: [] for d in range(1, 32)}
    for t in all_tasks:
        sch[t["plan_day"]].append(dict(t))

    moved_log = []
    redistribute_schedule(sch, moved_log, t_month, target_day, t_year=t_year)

    assigned_sch = {d: [] for d in range(1, calendar.monthrange(t_year, t_month)[1] + 1)}
    for plan_day, tasks in sch.items():
        for t in tasks:
            ad = t.get("assigned_day", plan_day)
            t["assigned_date"] = f"{t_year:04d}-{t_month:02d}-{int(ad):02d}"
            assigned_sch.setdefault(ad, []).append(t)

    report.stats["elapsed_s"] += time.monotonic() - phase_t0
    log_operation(
        "phase_done",
        f"month={t_month} com_cells={report.stats['com_cells']} "
        f"total={report.stats['elapsed_s']:.1f}s",
    )

    return assigned_sch, colored_skipped, moved_log


def moved_to_strings(moved_log, month):
    out = []
    for m in moved_log:
        if m.get("reserve_assignment") and m["assigned_day"] == m["plan_day"]:
            action = f"назначено резервному: {m.get('executor', '—')}"
        else:
            action = f"план {m['plan_day']}-е → выдано {m['assigned_day']}-е"
            if m.get("reserve_assignment"):
                action += f", резерв: {m.get('executor', '—')}"
        line = f"[{m['plan_day']:02d}.{month:02d}] {m['place']}: {action} | {m['work']}"
        out.append(line)
    return out


def colored_to_strings(colored_list, month_filter=None):
    out = []
    for p in colored_list:
        if month_filter is not None and p["month"] != month_filter:
            continue
        out.append(f"[{p['day']:02d}.{p['month']:02d}] {p['place']}: {p['work']}")
    return out
