"""Единый кадровый календарь сменного и дневного персонала."""

from __future__ import annotations

from datetime import date, datetime

from data_manager import _init_db_tables, get_conn
from ssz_config import CONFIG


_seed_signature = None
_staff_rows_cache = None
_absence_rows_cache = None
_day_override_rows_cache = None


ABSENCE_TYPES = (
    "Отпуск",
    "Больничный",
    "За свой счёт",
    "Командировка",
    "Обучение",
    "Отгул",
    "Другое",
)

WORK_MODES = {
    "shift_a": "Сменный 1",
    "shift_b": "Сменный 2",
    "day": "Дневной",
}


def invalidate_schedule_cache(reset_seed=False):
    global _seed_signature, _staff_rows_cache, _absence_rows_cache, _day_override_rows_cache
    _staff_rows_cache = None
    _absence_rows_cache = None
    _day_override_rows_cache = None
    if reset_seed:
        _seed_signature = None


def _iso(value):
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    return datetime.strptime(str(value), "%Y-%m-%d").date().isoformat()


def _display_name(value):
    name = str(value or "").strip()
    if name and not name.lower().startswith(
        ("наладчик", "инженер", "мастер", "электромонтер", "начальник")
    ):
        return f"Наладчик КИПиА {name}"
    return name


def ensure_staff_seeded():
    global _seed_signature
    import data_manager

    seeds = (
        (CONFIG.get("executor_1", "").strip(), "shift_a"),
        (CONFIG.get("executor_2", "").strip(), "shift_b"),
        (CONFIG.get("overflow_executor", "").strip(), "day"),
        # Дмитриев присутствует в списке пользователей и старых заменах,
        # но не входил в первоначальные три настройки исполнителей.
        ("Наладчик КИПиА Дмитриев И.С.", "day"),
    )
    signature = (
        data_manager.DB_PATH,
        tuple(seeds),
        repr(CONFIG.get("executor_overrides", [])),
    )
    if _seed_signature == signature:
        return
    conn = get_conn()
    try:
        _init_db_tables(conn)
        for name, mode in seeds:
            if not name:
                continue
            conn.execute(
                """
                INSERT INTO staff_members(name, work_mode)
                VALUES (?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    work_mode=excluded.work_mode,
                    active=staff_members.active,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (name, mode),
            )
        existing = conn.execute("SELECT count(*) FROM staff_absences").fetchone()[0]
        if not existing:
            for item in CONFIG.get("executor_overrides", []):
                start = str(item.get("start") or "")
                end = str(item.get("end") or "")
                replacement = str(item.get("name") or "").strip()
                if not start or not end or not replacement:
                    continue
                target = str(item.get("target") or "Любого")
                target_name = "Любого сменного"
                for name, _mode in seeds:
                    if name and target in name:
                        target_name = name
                        break
                conn.execute(
                    """
                    INSERT INTO staff_absences(
                        staff_name,start_date,end_date,absence_type,replacement_name,note
                    ) VALUES (?,?,?,?,?,?)
                    """,
                    (target_name, start, end, "Другое", replacement, "Перенесено из старых замен"),
                )
        conn.commit()
    finally:
        conn.close()
    _seed_signature = signature
    invalidate_schedule_cache()


def list_staff(active_only=False):
    global _staff_rows_cache
    ensure_staff_seeded()
    if _staff_rows_cache is None:
        conn = get_conn()
        try:
            query = (
                "SELECT id,name,work_mode,role,active FROM staff_members "
                "ORDER BY CASE work_mode WHEN 'shift_a' THEN 1 WHEN 'shift_b' THEN 2 ELSE 3 END, name"
            )
            _staff_rows_cache = [
            {"id": r[0], "name": r[1], "work_mode": r[2], "role": r[3], "active": bool(r[4])}
            for r in conn.execute(query).fetchall()
            ]
        finally:
            conn.close()
    rows = _staff_rows_cache
    if active_only:
        rows = [row for row in rows if row["active"]]
    return [dict(row) for row in rows]


def save_staff(rows):
    conn = get_conn()
    try:
        names = set()
        for row in rows:
            name = str(row.get("name") or "").strip()
            mode = str(row.get("work_mode") or "").strip()
            if not name or mode not in WORK_MODES:
                raise ValueError("У каждого сотрудника должны быть указаны ФИО и режим работы")
            if name.lower() in names:
                raise ValueError(f"Сотрудник указан дважды: {name}")
            names.add(name.lower())
            conn.execute(
                """
                INSERT INTO staff_members(name,work_mode,role,active)
                VALUES (?,?,?,?)
                ON CONFLICT(name) DO UPDATE SET
                    work_mode=excluded.work_mode, role=excluded.role,
                    active=excluded.active, updated_at=CURRENT_TIMESTAMP
                """,
                (name, mode, str(row.get("role") or "Наладчик КИПиА"), int(bool(row.get("active", True)))),
            )
        if names:
            placeholders = ",".join("?" for _ in names)
            conn.execute(
                f"UPDATE staff_members SET active=0,updated_at=CURRENT_TIMESTAMP "
                f"WHERE lower(name) NOT IN ({placeholders})",
                tuple(names),
            )
        else:
            conn.execute("UPDATE staff_members SET active=0,updated_at=CURRENT_TIMESTAMP")
        conn.commit()
    finally:
        conn.close()
    invalidate_schedule_cache()


def list_absences(start=None, end=None):
    global _absence_rows_cache
    ensure_staff_seeded()
    if _absence_rows_cache is None:
        conn = get_conn()
        try:
            _absence_rows_cache = [
            {
                "id": r[0], "staff_name": r[1], "start": r[2], "end": r[3],
                "absence_type": r[4], "replacement_name": r[5] or "", "note": r[6] or "",
            }
            for r in conn.execute(
                "SELECT id,staff_name,start_date,end_date,absence_type,replacement_name,note "
                "FROM staff_absences ORDER BY start_date,staff_name,id"
            ).fetchall()
            ]
        finally:
            conn.close()
    rows = _absence_rows_cache
    if start is not None and end is not None:
        start_iso, end_iso = _iso(start), _iso(end)
        rows = [row for row in rows if row["end"] >= start_iso and row["start"] <= end_iso]
    return [dict(row) for row in rows]


def replace_absences(rows):
    normalized = []
    for row in rows:
        staff_name = str(row.get("staff_name") or "").strip()
        start = _iso(row.get("start"))
        end = _iso(row.get("end"))
        kind = str(row.get("absence_type") or "").strip()
        if not staff_name or kind not in ABSENCE_TYPES:
            raise ValueError("Для отсутствия укажите сотрудника и корректную причину")
        if end < start:
            raise ValueError(f"Дата окончания раньше начала: {staff_name}")
        normalized.append((staff_name, start, end, kind, str(row.get("replacement_name") or "").strip(), str(row.get("note") or "").strip()))

    for i, left in enumerate(normalized):
        for right in normalized[i + 1:]:
            if left[0] == right[0] and left[1] <= right[2] and right[1] <= left[2]:
                raise ValueError(f"Пересекающиеся отсутствия сотрудника: {left[0]}")

    conn = get_conn()
    try:
        conn.execute("DELETE FROM staff_absences")
        conn.executemany(
            """
            INSERT INTO staff_absences(
                staff_name,start_date,end_date,absence_type,replacement_name,note
            ) VALUES (?,?,?,?,?,?)
            """,
            normalized,
        )
        conn.commit()
    finally:
        conn.close()
    invalidate_schedule_cache()


def list_day_overrides(start=None, end=None):
    global _day_override_rows_cache
    ensure_staff_seeded()
    if _day_override_rows_cache is None:
        conn = get_conn()
        try:
            _day_override_rows_cache = [
                {
                    "id": row[0], "date": row[1], "staff_name": row[2],
                    "status": row[3], "replaces_name": row[4] or "", "reason": row[5] or "",
                }
                for row in conn.execute(
                    "SELECT id,work_date,staff_name,status,replaces_name,reason "
                    "FROM staff_day_overrides ORDER BY work_date,staff_name"
                ).fetchall()
            ]
        finally:
            conn.close()
    rows = _day_override_rows_cache
    if start is not None and end is not None:
        start_iso, end_iso = _iso(start), _iso(end)
        rows = [row for row in rows if start_iso <= row["date"] <= end_iso]
    return [dict(row) for row in rows]


def replace_day_overrides(rows):
    normalized = []
    seen = set()
    incoming_replacements = set()
    for row in rows:
        work_date = _iso(row.get("date"))
        staff_name = str(row.get("staff_name") or "").strip()
        status = str(row.get("status") or "").strip()
        replaces_name = str(row.get("replaces_name") or "").strip()
        reason = str(row.get("reason") or "").strip()
        if not staff_name or status not in ("work", "off"):
            raise ValueError("Для ручной смены укажите сотрудника и состояние «работает/выходной»")
        if status == "off":
            replaces_name = ""
        if replaces_name and _display_name(replaces_name) == _display_name(staff_name):
            replaces_name = ""
        key = (work_date, staff_name.lower())
        if key in seen:
            raise ValueError(f"Ручной график указан дважды: {staff_name}, {work_date}")
        seen.add(key)
        if status == "work" and replaces_name:
            replacement_key = (work_date, _display_name(replaces_name).lower())
            if replacement_key in incoming_replacements:
                raise ValueError(
                    f"На {work_date} одного сотрудника пытаются заменить несколько человек: {replaces_name}"
                )
            incoming_replacements.add(replacement_key)
        normalized.append((work_date, staff_name, status, replaces_name, reason))
    conn = get_conn()
    try:
        conn.execute("DELETE FROM staff_day_overrides")
        conn.executemany(
            "INSERT INTO staff_day_overrides(work_date,staff_name,status,replaces_name,reason) "
            "VALUES (?,?,?,?,?)",
            normalized,
        )
        conn.commit()
    finally:
        conn.close()
    invalidate_schedule_cache()


def _day_override_for(name, day):
    day_iso = _iso(day)
    return next(
        (row for row in list_day_overrides() if row["date"] == day_iso and row["staff_name"] == name),
        None,
    )


def _incoming_shift_replacement(name, day):
    day_iso = _iso(day)
    rows = [
        row for row in list_day_overrides()
        if row["date"] == day_iso and row["status"] == "work"
        and _display_name(row.get("replaces_name")) == name
    ]
    if len(rows) > 1:
        raise RuntimeError(f"На {day_iso} сменного {name} одновременно заменяют несколько сотрудников")
    return rows[0] if rows else None


def _absence_for(name, day):
    day_iso = _iso(day)
    rows = [
        row for row in list_absences()
        if row["start"] <= day_iso <= row["end"]
        and row["staff_name"] in (name, "Любого сменного")
    ]
    if not rows:
        return None
    rows.sort(key=lambda row: (row["staff_name"] != name, -int(row["id"])))
    return rows[0]


def resolve_duty_executor(day, default_executor):
    incoming = _incoming_shift_replacement(default_executor, day)
    if incoming:
        return incoming["staff_name"]
    absence = _absence_for(default_executor, day)
    if absence:
        replacement = absence.get("replacement_name", "").strip()
        if replacement:
            return _display_name(replacement)
        raise RuntimeError(
            f"На {_iso(day)} сменный отсутствует ({absence['absence_type']}), но замена не назначена: {default_executor}"
        )
    own_override = _day_override_for(default_executor, day)
    if own_override and own_override["status"] == "off":
        raise RuntimeError(
            f"На {_iso(day)} у сменного отмечен ручной выходной, но заменяющий не назначен: {default_executor}"
        )
    return default_executor


def get_day_executors(day):
    if isinstance(day, datetime):
        day = day.date()
    if day.weekday() >= 5:
        return []
    result = []
    for member in list_staff(active_only=True):
        if member["work_mode"] != "day":
            continue
        manual = _day_override_for(member["name"], day)
        if manual and (manual["status"] == "off" or manual.get("replaces_name")):
            continue
        absence = _absence_for(member["name"], day)
        if absence:
            replacement = absence.get("replacement_name", "").strip()
            replacement = _display_name(replacement)
            if replacement and replacement not in result:
                result.append(replacement)
        elif member["name"] not in result:
            result.append(member["name"])
    return result


def is_staff_available(name, day):
    manual = _day_override_for(name, day) if name else None
    return bool(name) and _absence_for(name, day) is None and not (manual and manual["status"] == "off")


def staffing_for_day(day, default_executor):
    duty = resolve_duty_executor(day, default_executor)
    return {"duty": duty, "day": get_day_executors(day)}
