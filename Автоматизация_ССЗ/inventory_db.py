import sqlite3
import os
import re
from datetime import date, datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "inventory.db")

def _get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def normalize_serial_number(value):
    """Канонический вид номера для показа без потери значащих нулей."""
    value = str(value or "").strip().upper()
    value = value.replace("\\", "/")
    value = re.sub(r"\s*/\s*", " / ", value)
    value = re.sub(r"\s+", " ", value)
    return value


def serial_key(value):
    """Стабильный ключ поиска: пробелы и разделители не влияют на совпадение."""
    return re.sub(r"[^0-9A-ZА-ЯЁ]+", "", normalize_serial_number(value))


def _ensure_column(cursor, table, column, definition):
    cursor.execute(f"PRAGMA table_info({table})")
    columns = {col[1] for col in cursor.fetchall()}
    if column not in columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _merge_duplicate_locations(cursor):
    """Слить одноимённые места внутри цеха, сохранив все приборы."""
    duplicates = cursor.execute("""
        SELECT workshop_id, lower(trim(name)) AS normalized_name,
               min(id) AS keep_id, group_concat(id) AS ids
        FROM locations
        GROUP BY workshop_id, normalized_name
        HAVING count(*) > 1
    """).fetchall()
    for workshop_id, _name, keep_id, ids_csv in duplicates:
        for duplicate_id in (int(value) for value in ids_csv.split(",")):
            if duplicate_id == keep_id:
                continue
            cursor.execute(
                "UPDATE devices SET location_id = ? WHERE location_id = ?",
                (keep_id, duplicate_id),
            )
            cursor.execute("DELETE FROM locations WHERE id = ?", (duplicate_id,))

def init_db():
    conn = _get_conn()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workshops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workshop_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL, -- 'furnace', 'utir', 'storage'
            FOREIGN KEY(workshop_id) REFERENCES workshops(id)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            serial_number TEXT,
            location_id INTEGER,
            calibration_date DATE,
            position TEXT,
            FOREIGN KEY(location_id) REFERENCES locations(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory_imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file TEXT NOT NULL,
            workshop_id INTEGER NOT NULL,
            location_id INTEGER NOT NULL,
            imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            rows_total INTEGER NOT NULL DEFAULT 0,
            rows_added INTEGER NOT NULL DEFAULT 0,
            rows_updated INTEGER NOT NULL DEFAULT 0,
            rows_skipped INTEGER NOT NULL DEFAULT 0,
            note TEXT,
            FOREIGN KEY(workshop_id) REFERENCES workshops(id),
            FOREIGN KEY(location_id) REFERENCES locations(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory_import_items (
            import_id INTEGER NOT NULL,
            device_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            source_row INTEGER,
            PRIMARY KEY(import_id, device_id),
            FOREIGN KEY(import_id) REFERENCES inventory_imports(id) ON DELETE CASCADE,
            FOREIGN KEY(device_id) REFERENCES devices(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory_daily_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_date TEXT NOT NULL,
            device_id INTEGER NOT NULL,
            issue_type TEXT NOT NULL,
            work TEXT NOT NULL,
            place TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'normal',
            status TEXT NOT NULL DEFAULT 'open',
            include_in_ssz INTEGER NOT NULL DEFAULT 1,
            include_in_print INTEGER NOT NULL DEFAULT 1,
            note TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            UNIQUE(plan_date, device_id, issue_type),
            FOREIGN KEY(device_id) REFERENCES devices(id)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_inventory_daily_tasks_date
        ON inventory_daily_tasks(plan_date,status)
    """)
    
    # Миграция: добавление колонки position, если её нет
    _ensure_column(cursor, "devices", "position", "TEXT")
    _ensure_column(cursor, "devices", "serial_key", "TEXT")
    _ensure_column(cursor, "devices", "source", "TEXT")
    _ensure_column(cursor, "devices", "lifecycle_status", "TEXT")
    _ensure_column(cursor, "devices", "created_at", "TEXT")
    _ensure_column(cursor, "devices", "updated_at", "TEXT")
    _ensure_column(cursor, "inventory_daily_tasks", "include_in_print", "INTEGER NOT NULL DEFAULT 1")
        
    # Миграция: добавление колонки es_image_path для locations
    _ensure_column(cursor, "locations", "es_image_path", "TEXT")
    
    # Canonical workshop names — these are the ONLY valid workshops
    default_workshops = [
        "Цех 6 (Картэкс, 2-й)",
        "Цех 66 (66.2, Спецсталь)",
        "Цех 92 (ИСМ)",
        "Цех 47 (Спецсталь)",
    ]

    # Migrate old generic names → new canonical names
    renames = [
        ("Цех 6",   "Цех 6 (Картэкс, 2-й)"),
        ("Цех 66",  "Цех 66 (66.2, Спецсталь)"),
        ("Цех ИСМ", "Цех 92 (ИСМ)"),
        ("Цех 47",  "Цех 47 (Спецсталь)"),
        ("Цех 2",   "Цех 6 (Картэкс, 2-й)"),      # Цех 2 is part of Картэкс
        ("Печь 10 (Ижора, цех 66.1)", "Цех 66 (66.2, Спецсталь)"),
    ]
    for old_name, new_name in renames:
        cursor.execute("SELECT id FROM workshops WHERE name = ?", (old_name,))
        old_row = cursor.fetchone()
        if not old_row:
            continue
        old_id = old_row[0]
        cursor.execute("SELECT id FROM workshops WHERE name = ?", (new_name,))
        new_row = cursor.fetchone()
        if new_row:
            # Target already exists — merge same-named locations safely.
            new_id = new_row[0]
            old_locations = cursor.execute(
                "SELECT id, name FROM locations WHERE workshop_id = ?", (old_id,)
            ).fetchall()
            for old_location_id, old_location_name in old_locations:
                target_location = cursor.execute("""
                    SELECT id FROM locations
                    WHERE workshop_id = ? AND name = ? COLLATE NOCASE
                    LIMIT 1
                """, (new_id, old_location_name)).fetchone()
                if target_location:
                    cursor.execute(
                        "UPDATE devices SET location_id = ? WHERE location_id = ?",
                        (target_location[0], old_location_id),
                    )
                    cursor.execute("DELETE FROM locations WHERE id = ?", (old_location_id,))
                else:
                    cursor.execute(
                        "UPDATE locations SET workshop_id = ? WHERE id = ?",
                        (new_id, old_location_id),
                    )
            cursor.execute("DELETE FROM workshops WHERE id = ?", (old_id,))
        else:
            cursor.execute("UPDATE workshops SET name = ? WHERE id = ?", (new_name, old_id))

    for ws in default_workshops:
        cursor.execute("INSERT OR IGNORE INTO workshops (name) VALUES (?)", (ws,))

    # Привести накопленные данные к единому виду до установки ограничений.
    _merge_duplicate_locations(cursor)
    cursor.execute("UPDATE workshops SET name = trim(name)")
    cursor.execute("UPDATE locations SET name = trim(name), type = lower(trim(type))")
    device_rows = cursor.execute("SELECT id, serial_number FROM devices").fetchall()
    now = datetime.now().isoformat(timespec="seconds")
    for device_id, raw_serial in device_rows:
        normalized_serial = normalize_serial_number(raw_serial)
        cursor.execute("""
            UPDATE devices
            SET name = trim(name), serial_number = ?, serial_key = ?,
                lifecycle_status = coalesce(nullif(lifecycle_status, ''), 'active'),
                created_at = coalesce(created_at, ?), updated_at = coalesce(updated_at, ?)
            WHERE id = ?
        """, (normalized_serial, serial_key(normalized_serial), now, now, device_id))

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_locations_workshop ON locations(workshop_id)")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_locations_workshop_name ON locations(workshop_id, name COLLATE NOCASE)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_devices_location ON devices(location_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_devices_calibration ON devices(calibration_date)")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_devices_serial_key ON devices(serial_key) WHERE serial_key <> ''")
        
    conn.commit()
    conn.close()
    
    # Initialize checklist tables
    try:
        from checklist_db import init_checklist_tables
        init_checklist_tables()
    except ImportError:
        pass

def get_furnace_template(ws_name):
    if "92" in ws_name:
        return ["КСП-3", "Термопары"]
    else:
        return [
            "Расход газа (КСД-2)", 
            "Расход воздуха (КСД-2)", 
            "Температура в печи (КСП-4)", 
            "Температура гибких (аттестация) (КСП-4)", 
            "Давление в печи (КСД-2)",
            "Температура дыма и воздуха после рекуператора",
            "Температура дыма до рекуператора"
        ]

def get_workshops():
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM workshops ORDER BY name")
    res = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1]} for r in res]

def get_workshop_by_name(name):
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM workshops WHERE name LIKE ?", (f"%{name}%",))
    res = cursor.fetchone()
    conn.close()
    if res:
        return {"id": res[0], "name": res[1]}
    return None

def add_workshop(name):
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO workshops (name) VALUES (?)", (name,))
    conn.commit()
    cursor.execute("SELECT id FROM workshops WHERE name = ?", (name,))
    ws_id = cursor.fetchone()[0]
    conn.close()
    return ws_id

def add_location(workshop_id, name, loc_type):
    conn = _get_conn()
    cursor = conn.cursor()
    name = str(name or "").strip()
    loc_type = str(loc_type or "general").strip().lower()
    cursor.execute("INSERT OR IGNORE INTO locations (workshop_id, name, type) VALUES (?, ?, ?)", (workshop_id, name, loc_type))
    conn.commit()
    cursor.execute("SELECT id FROM locations WHERE workshop_id = ? AND name = ? COLLATE NOCASE", (workshop_id, name))
    loc_id = cursor.fetchone()[0]
    conn.close()
    return loc_id

def get_locations(workshop_id=None):
    conn = _get_conn()
    cursor = conn.cursor()
    if workshop_id is not None:
        cursor.execute("SELECT id, workshop_id, name, type, es_image_path FROM locations WHERE workshop_id = ? ORDER BY name", (workshop_id,))
    else:
        cursor.execute("SELECT id, workshop_id, name, type, es_image_path FROM locations ORDER BY name")
    res = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "workshop_id": r[1], "name": r[2], "type": r[3], "es_image_path": r[4]} for r in res]

def get_location_by_name(workshop_id, name):
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id, workshop_id, name, type, es_image_path FROM locations WHERE workshop_id = ? AND name LIKE ?", (workshop_id, f"%{name}%"))
    res = cursor.fetchone()
    conn.close()
    if res:
        return {"id": res[0], "workshop_id": res[1], "name": res[2], "type": res[3], "es_image_path": res[4]}
    return None

def update_location(loc_id, name, type_val):
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("UPDATE locations SET name = ?, type = ? WHERE id = ?", (name, type_val, loc_id))
    conn.commit()
    conn.close()

def update_location_es_path(loc_id, es_image_path):
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("UPDATE locations SET es_image_path = ? WHERE id = ?", (es_image_path, loc_id))
    conn.commit()
    conn.close()

def delete_location(loc_id):
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM devices WHERE location_id = ?", (loc_id,))
    cursor.execute("DELETE FROM locations WHERE id = ?", (loc_id,))
    conn.commit()
    conn.close()

def add_device(name, serial_number, location_id, calibration_date, position=None, source=None,
               lifecycle_status="active"):
    conn = _get_conn()
    cursor = conn.cursor()
    serial_number = normalize_serial_number(serial_number)
    now = datetime.now().isoformat(timespec="seconds")
    cursor.execute("""
        INSERT INTO devices (
            name, serial_number, serial_key, location_id, calibration_date,
            position, source, lifecycle_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (str(name or "").strip(), serial_number, serial_key(serial_number), location_id,
          calibration_date, position, source, lifecycle_status or "active", now, now))
    conn.commit()
    conn.close()

def smart_upsert_device(name, serial_number, location_id, calibration_date, position=None,
                        update_location=False, source=None, lifecycle_status=None,
                        return_device_id=False):
    """
    Умное добавление или обновление прибора.
    Возвращает "added", "updated" или "skipped".
    """
    conn = _get_conn()
    cursor = conn.cursor()
    
    device_found = False
    device_ids = []
    
    serial_number = normalize_serial_number(serial_number)
    normalized_key = serial_key(serial_number)
    if normalized_key:
        cursor.execute("SELECT id, calibration_date, location_id, position FROM devices WHERE serial_key = ?", (normalized_key,))
        rows = cursor.fetchall()
        if rows:
            device_found = True
            device_ids = rows
            
    if not device_found and position:
        cursor.execute("SELECT type FROM locations WHERE id = ?", (location_id,))
        loc_row = cursor.fetchone()
        if loc_row and loc_row[0] in ('furnace', 'utir'):
            cursor.execute("SELECT id, calibration_date, location_id, position FROM devices WHERE location_id = ? AND position = ?", (location_id, position))
            rows = cursor.fetchall()
            if rows:
                device_found = True
                device_ids = rows
                
    if device_found:
        status = "skipped"
        for row in device_ids:
            d_id, old_cal, old_loc, old_pos = row
            updates = {}
            
            if calibration_date:
                update_cal = False
                if not old_cal:
                    update_cal = True
                else:
                    try:
                        old_dt = datetime.strptime(old_cal.split("T")[0], "%Y-%m-%d")
                        new_dt = datetime.strptime(calibration_date.split("T")[0], "%Y-%m-%d")
                        if new_dt > old_dt:
                            update_cal = True
                    except:
                        update_cal = True
                
                if update_cal:
                    updates["calibration_date"] = calibration_date
            
            if update_location and old_loc != location_id:
                updates["location_id"] = location_id

            if position and (not old_pos or update_location):
                updates["position"] = position

            if source:
                updates["source"] = source

            if lifecycle_status:
                updates["lifecycle_status"] = lifecycle_status

            updates["serial_number"] = serial_number
            updates["serial_key"] = normalized_key
                
            if updates:
                updates["updated_at"] = datetime.now().isoformat(timespec="seconds")
                set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
                params = list(updates.values())
                params.append(d_id)
                cursor.execute(f"UPDATE devices SET {set_clause} WHERE id = ?", tuple(params))
                status = "updated"
                
        conn.commit()
        conn.close()
        result = (status, device_ids[0][0]) if return_device_id else status
        return result
    else:
        now = datetime.now().isoformat(timespec="seconds")
        cursor.execute("""
            INSERT INTO devices (
                name, serial_number, serial_key, location_id, calibration_date,
                position, source, lifecycle_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (str(name or "").strip(), serial_number, normalized_key, location_id,
              calibration_date, position, source, lifecycle_status or "active", now, now))
        device_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return ("added", device_id) if return_device_id else "added"

def get_devices(location_id=None, include_unassigned=True):
    conn = _get_conn()
    cursor = conn.cursor()
    
    query = "SELECT id, name, serial_number, location_id, calibration_date, position FROM devices"
    params = []
    
    if location_id is not None:
        query += " WHERE location_id = ?"
        params.append(location_id)
        
    cursor.execute(query, tuple(params))
    res = cursor.fetchall()
    conn.close()
    
    return [
        {
            "id": r[0], 
            "name": r[1], 
            "serial_number": r[2], 
            "location_id": r[3], 
            "calibration_date": r[4],
            "position": r[5]
        } 
        for r in res
    ]

def get_unassigned_location(workshop_id):
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM locations WHERE workshop_id = ? AND type = 'unassigned' LIMIT 1", (workshop_id,))
    res = cursor.fetchone()
    if not res:
        cursor.execute("INSERT INTO locations (workshop_id, name, type) VALUES (?, ?, ?)", (workshop_id, "Требуют распределения", "unassigned"))
        loc_id = cursor.lastrowid
        conn.commit()
    else:
        loc_id = res[0]
    conn.close()
    return loc_id

def update_device_location(device_id, location_id, position=None):
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE devices
        SET location_id = ?, position = ?, updated_at = ?
        WHERE id = ?
    """, (location_id, position, datetime.now().isoformat(timespec="seconds"), device_id))
    conn.commit()
    conn.close()

def get_devices_for_calibration(months_margin=3):
    conn = _get_conn()
    cursor = conn.cursor()
    
    target_date = (datetime.now() + timedelta(days=30 * months_margin)).strftime("%Y-%m-%d")
    
    query = """
        SELECT d.id, d.name, d.serial_number, d.calibration_date, l.name as loc_name, w.name as ws_name, l.type, d.position
        FROM devices d
        JOIN locations l ON d.location_id = l.id
        JOIN workshops w ON l.workshop_id = w.id
        WHERE d.calibration_date <= ? AND d.calibration_date IS NOT NULL AND d.calibration_date != ''
          AND coalesce(d.lifecycle_status, 'active') = 'active'
        ORDER BY d.calibration_date ASC
    """
    cursor.execute(query, (target_date,))
    res = cursor.fetchall()
    conn.close()
    
    return [
        {
            "id": r[0],
            "name": r[1],
            "serial_number": r[2],
            "calibration_date": r[3],
            "location_name": r[4],
            "workshop_name": r[5],
            "location_type": r[6],
            "position": r[7]
        }
        for r in res
    ]

def replace_device(device_id, new_calibration_date=None, to_storage=True):
    conn = _get_conn()
    cursor = conn.cursor()
    if to_storage:
        cursor.execute("""
            SELECT l.id, l.workshop_id FROM devices d
            JOIN locations l ON d.location_id = l.id
            WHERE d.id = ?
        """, (device_id,))
        res = cursor.fetchone()
        if res:
            loc_id, ws_id = res
            cursor.execute("SELECT id FROM locations WHERE workshop_id = ? AND type = 'storage' LIMIT 1", (ws_id,))
            storage_res = cursor.fetchone()
            if not storage_res:
                cursor.execute("INSERT INTO locations (workshop_id, name, type) VALUES (?, ?, ?)", (ws_id, "Кладовка (Резерв)", "storage"))
                storage_id = cursor.lastrowid
            else:
                storage_id = storage_res[0]
            
            cursor.execute(
                "UPDATE devices SET location_id = ?, position = NULL, updated_at = ? WHERE id = ?",
                (storage_id, datetime.now().isoformat(timespec="seconds"), device_id),
            )
    
    if new_calibration_date:
        cursor.execute(
            "UPDATE devices SET calibration_date = ?, updated_at = ? WHERE id = ?",
            (new_calibration_date, datetime.now().isoformat(timespec="seconds"), device_id),
        )
        
    conn.commit()
    conn.close()

def get_db_readiness_percentage():
    """Процент готовности БД = доля заполненных слотов в печах."""
    conn = _get_conn()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT l.id, w.name 
        FROM locations l
        JOIN workshops w ON l.workshop_id = w.id
        WHERE l.type = 'furnace'
    """)
    furnaces = cursor.fetchall()
    
    if not furnaces:
        conn.close()
        return 0.0
        
    total_slots = 0
    filled_slots = 0
    
    for loc_id, ws_name in furnaces:
        template = set(get_furnace_template(ws_name))
            
        total_slots += len(template)
        
        cursor.execute("SELECT position FROM devices WHERE location_id = ?", (loc_id,))
        devices_positions = [row[0] for row in cursor.fetchall() if row[0]]
        
        filled_in_this_furnace = len(template.intersection(set(devices_positions)))
        filled_slots += filled_in_this_furnace
        
    conn.close()
    
    if total_slots == 0:
        return 0.0
    
    percentage = (filled_slots / total_slots) * 100
    return min(100.0, round(percentage, 1))

def get_all_devices_full_info():
    conn = _get_conn()
    cursor = conn.cursor()
    query = """
        SELECT d.id, d.name, d.serial_number, d.calibration_date, l.name as loc_name, w.name as ws_name, l.type, d.position, w.id as ws_id, l.id as loc_id, d.lifecycle_status
        FROM devices d
        JOIN locations l ON d.location_id = l.id
        JOIN workshops w ON l.workshop_id = w.id
    """
    cursor.execute(query)
    res = cursor.fetchall()
    conn.close()
    
    return [
        {
            "id": r[0],
            "name": r[1],
            "serial_number": r[2],
            "calibration_date": r[3],
            "location_name": r[4],
            "workshop_name": r[5],
            "location_type": r[6],
            "position": r[7],
            "ws_id": r[8],
            "loc_id": r[9],
            "lifecycle_status": r[10] or "active",
        }
        for r in res
    ]


def create_inventory_import(source_file, workshop_id, location_id, rows_total, note=None):
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO inventory_imports (
            source_file, workshop_id, location_id, rows_total, note
        ) VALUES (?, ?, ?, ?, ?)
    """, (os.path.basename(source_file), workshop_id, location_id, rows_total, note))
    import_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return import_id


def add_inventory_import_item(import_id, device_id, action, source_row=None):
    conn = _get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO inventory_import_items (
            import_id, device_id, action, source_row
        ) VALUES (?, ?, ?, ?)
    """, (import_id, device_id, action, source_row))
    conn.commit()
    conn.close()


def finish_inventory_import(import_id, added, updated, skipped):
    conn = _get_conn()
    conn.execute("""
        UPDATE inventory_imports
        SET rows_added = ?, rows_updated = ?, rows_skipped = ?
        WHERE id = ?
    """, (added, updated, skipped, import_id))
    conn.commit()
    conn.close()


def get_inventory_stats():
    """Компактная сводка для главного экрана учета."""
    conn = _get_conn()
    cursor = conn.cursor()
    today = date.today().isoformat()
    margin = (date.today() + timedelta(days=90)).isoformat()
    row = cursor.execute("""
        SELECT
            count(*) AS total,
            sum(CASE WHEN l.type = 'storage' THEN 1 ELSE 0 END) AS in_storage,
            sum(CASE WHEN l.type = 'unassigned' THEN 1 ELSE 0 END) AS unassigned,
            sum(CASE WHEN coalesce(d.lifecycle_status, 'active') = 'active' AND (d.calibration_date IS NULL OR trim(d.calibration_date) = '') THEN 1 ELSE 0 END) AS without_calibration,
            sum(CASE WHEN coalesce(d.lifecycle_status, 'active') = 'active' AND d.calibration_date < ? THEN 1 ELSE 0 END) AS overdue,
            sum(CASE WHEN coalesce(d.lifecycle_status, 'active') = 'active' AND d.calibration_date >= ? AND d.calibration_date <= ? THEN 1 ELSE 0 END) AS due_soon
        FROM devices d
        LEFT JOIN locations l ON l.id = d.location_id
    """, (today, today, margin)).fetchone()
    latest = cursor.execute("""
        SELECT imported_at, source_file, rows_total, rows_added, rows_updated
        FROM inventory_imports
        ORDER BY id DESC LIMIT 1
    """).fetchone()
    conn.close()
    keys = ("total", "in_storage", "unassigned", "without_calibration", "overdue", "due_soon")
    result = {key: int(value or 0) for key, value in zip(keys, row)}
    result["latest_import"] = {
        "imported_at": latest[0], "source_file": latest[1], "rows_total": latest[2],
        "rows_added": latest[3], "rows_updated": latest[4],
    } if latest else None
    return result


def get_attention_items():
    """Сформировать рабочую очередь проблем, требующих решения сотрудника."""
    conn = _get_conn()
    cursor = conn.cursor()
    today = date.today()
    margin = today + timedelta(days=90)
    rows = cursor.execute("""
        SELECT d.id, d.name, d.serial_number, d.calibration_date, d.position,
               l.name, l.type, w.name
        FROM devices d
        LEFT JOIN locations l ON l.id = d.location_id
        LEFT JOIN workshops w ON w.id = l.workshop_id
        WHERE coalesce(d.lifecycle_status, 'active') = 'active'
        ORDER BY w.name, l.name, d.name, d.serial_number
    """).fetchall()
    conn.close()

    items = []
    for device_id, name, serial, calibration, position, location, loc_type, workshop in rows:
        base = {
            "device_id": device_id,
            "device_name": name,
            "serial_number": serial or "",
            "workshop_name": workshop or "Не указан",
            "location_name": location or "Не указано",
            "position": position or "",
        }

        if not calibration or not str(calibration).strip():
            items.append({
                **base,
                "priority": "high",
                "issue_type": "missing_calibration",
                "issue": "Не указана дата поверки",
                "request": "Загрузите свидетельство или укажите дату вручную.",
            })
        else:
            try:
                calibration_date = datetime.strptime(str(calibration).split("T")[0], "%Y-%m-%d").date()
                if calibration_date < today:
                    items.append({
                        **base,
                        "priority": "critical",
                        "issue_type": "overdue",
                        "issue": "Поверка просрочена",
                        "request": f"Нужен актуальный документ или решение о замене. Срок: {calibration_date:%d.%m.%Y}.",
                    })
                elif calibration_date <= margin:
                    items.append({
                        **base,
                        "priority": "medium",
                        "issue_type": "due_soon",
                        "issue": "Поверка в ближайшие 90 дней",
                        "request": f"Подготовьте поверку или замену до {calibration_date:%d.%m.%Y}.",
                    })
            except (TypeError, ValueError):
                items.append({
                    **base,
                    "priority": "high",
                    "issue_type": "invalid_calibration",
                    "issue": "Некорректная дата поверки",
                    "request": f"Проверьте значение даты: {calibration}.",
                })

        if not location or loc_type == "unassigned":
            items.append({
                **base,
                "priority": "high",
                "issue_type": "unassigned",
                "issue": "Не определено место",
                "request": "Укажите цех, место установки и позицию.",
            })

    priority_order = {"critical": 0, "high": 1, "medium": 2}
    items.sort(key=lambda item: (
        priority_order.get(item["priority"], 9),
        item["workshop_name"], item["device_name"], item["serial_number"],
    ))
    return items


def get_attention_summary():
    items = get_attention_items()
    return {
        "total": len(items),
        "critical": sum(item["priority"] == "critical" for item in items),
        "high": sum(item["priority"] == "high" for item in items),
        "medium": sum(item["priority"] == "medium" for item in items),
    }


def ensure_daily_inventory_plan(plan_date=None, limit=None):
    """Создаёт небольшой выполнимый план: за день только один цех."""
    from ssz_config import CONFIG

    if not CONFIG.get("inventory_daily_plan_enabled", True):
        return []
    plan_date = plan_date or date.today()
    if isinstance(plan_date, datetime):
        plan_date = plan_date.date()
    plan_iso = plan_date.isoformat()
    limit = int(limit or CONFIG.get("inventory_daily_plan_size", 6))
    cooldown = int(CONFIG.get("inventory_daily_plan_cooldown_days", 14))
    cutoff = (plan_date - timedelta(days=max(cooldown, 0))).isoformat()

    conn = _get_conn()
    # Старые версии могли смешивать цеха в одном дне. Незавершённые строки
    # безопасно приводим к одному цеху при первом открытии обновлённого плана.
    existing_rows = conn.execute(
        """
        SELECT t.id,t.status,w.name
        FROM inventory_daily_tasks t
        JOIN devices d ON d.id=t.device_id
        LEFT JOIN locations l ON l.id=d.location_id
        LEFT JOIN workshops w ON w.id=l.workshop_id
        WHERE t.plan_date=?
        ORDER BY CASE WHEN t.status='open' THEN 1 ELSE 0 END,t.id
        """,
        (plan_iso,),
    ).fetchall()
    existing_workshops = [row[2] for row in existing_rows if row[2]]
    if len(set(existing_workshops)) > 1:
        anchor = existing_workshops[0]
        remove_ids = [
            row[0] for row in existing_rows
            if row[1] == "open" and row[2] and row[2] != anchor
        ]
        if remove_ids:
            placeholders = ",".join("?" for _ in remove_ids)
            conn.execute(
                f"DELETE FROM inventory_daily_tasks WHERE id IN ({placeholders})",
                remove_ids,
            )
            conn.commit()
    existing = conn.execute(
        "SELECT count(*) FROM inventory_daily_tasks WHERE plan_date=?",
        (plan_iso,),
    ).fetchone()[0]
    conn.close()
    if existing < limit:
        candidates = get_attention_items()
        conn = _get_conn()
        try:
            recent = {
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT device_id FROM inventory_daily_tasks WHERE plan_date>=? AND plan_date<?",
                    (cutoff, plan_iso),
                ).fetchall()
            }
            existing_workshop = conn.execute(
                """
                SELECT w.name
                FROM inventory_daily_tasks t
                JOIN devices d ON d.id=t.device_id
                LEFT JOIN locations l ON l.id=d.location_id
                LEFT JOIN workshops w ON w.id=l.workshop_id
                WHERE t.plan_date=? AND w.name IS NOT NULL
                ORDER BY t.id LIMIT 1
                """,
                (plan_iso,),
            ).fetchone()
            available = [item for item in candidates if item["device_id"] not in recent]
            workshop_name = existing_workshop[0] if existing_workshop else None
            if not workshop_name and available:
                groups = {}
                for item in available:
                    groups.setdefault(item.get("workshop_name") or "Не указан", []).append(item)
                last_used = {
                    row[0]: row[1]
                    for row in conn.execute(
                        """
                        SELECT w.name,max(t.plan_date)
                        FROM inventory_daily_tasks t
                        JOIN devices d ON d.id=t.device_id
                        LEFT JOIN locations l ON l.id=d.location_id
                        LEFT JOIN workshops w ON w.id=l.workshop_id
                        WHERE t.plan_date<? AND w.name IS NOT NULL
                        GROUP BY w.name
                        """,
                        (plan_iso,),
                    ).fetchall()
                }
                priority_order = {"critical": 0, "high": 1, "medium": 2}
                workshop_name = min(
                    groups,
                    key=lambda name: (
                        last_used.get(name, ""),
                        min(priority_order.get(item["priority"], 9) for item in groups[name]),
                        -len(groups[name]),
                        name,
                    ),
                )
            selected_devices = set()
            for item in available:
                if existing >= limit:
                    break
                if item.get("workshop_name") != workshop_name:
                    continue
                device_id = item["device_id"]
                if device_id in selected_devices:
                    continue
                serial = item.get("serial_number") or "не указан"
                work = (
                    f"Уточнить данные прибора {item['device_name']}, зав. № {serial}: "
                    f"{item['issue'].lower()}. {item['request']}"
                )
                place = " / ".join(
                    value for value in (item.get("workshop_name"), item.get("location_name"))
                    if value and value not in ("Не указан", "Не указано")
                ) or "Место установки уточнить"
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO inventory_daily_tasks(
                        plan_date,device_id,issue_type,work,place,priority
                    ) VALUES (?,?,?,?,?,?)
                    """,
                    (plan_iso, device_id, item["issue_type"], work, place, item["priority"]),
                )
                if cursor.rowcount:
                    existing += 1
                    selected_devices.add(device_id)
            conn.commit()
        finally:
            conn.close()
    return get_daily_inventory_plan(plan_date)


def get_daily_inventory_plan(plan_date=None):
    plan_date = plan_date or date.today()
    if isinstance(plan_date, datetime):
        plan_date = plan_date.date()
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT t.id,t.plan_date,t.device_id,t.issue_type,t.work,t.place,
                   t.priority,t.status,t.include_in_print,t.note,d.name,d.serial_number,
                   d.calibration_date,d.position,d.location_id,l.name,l.type,w.id,w.name
            FROM inventory_daily_tasks t
            JOIN devices d ON d.id=t.device_id
            LEFT JOIN locations l ON l.id=d.location_id
            LEFT JOIN workshops w ON w.id=l.workshop_id
            WHERE t.plan_date=?
            ORDER BY CASE t.priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 ELSE 2 END,t.id
            """,
            (plan_date.isoformat(),),
        ).fetchall()
        return [
            {
                "id": r[0], "plan_date": r[1], "device_id": r[2], "issue_type": r[3],
                "work": r[4], "place": r[5], "priority": r[6], "status": r[7],
                "include_in_print": bool(r[8]), "note": r[9] or "",
                "device_name": r[10], "serial_number": r[11] or "",
                "calibration_date": r[12] or "", "position": r[13] or "",
                "location_id": r[14], "location_name": r[15] or "",
                "location_type": r[16] or "", "workshop_id": r[17],
                "workshop_name": r[18] or "Не указан",
            }
            for r in rows
        ]
    finally:
        conn.close()


def update_daily_inventory_task(task_id, status=None, include_in_print=None, note=None):
    updates = []
    params = []
    if status is not None:
        if status not in ("open", "completed", "skipped"):
            raise ValueError("Некорректный статус задания по базе")
        updates.extend(["status=?", "completed_at=CASE WHEN ?='completed' THEN CURRENT_TIMESTAMP ELSE NULL END"])
        params.extend([status, status])
    if include_in_print is not None:
        updates.append("include_in_print=?")
        params.append(int(bool(include_in_print)))
    if note is not None:
        updates.append("note=?")
        params.append(str(note))
    if not updates:
        return False
    params.append(int(task_id))
    conn = _get_conn()
    try:
        conn.execute(f"UPDATE inventory_daily_tasks SET {','.join(updates)} WHERE id=?", params)
        conn.commit()
        return True
    finally:
        conn.close()


def update_device_details(device_id, serial_number=None, calibration_date=None,
                          location_id=None, position=None):
    """Сохраняет ответы из ежедневного интерактивного плана."""
    updates = {}
    if serial_number is not None and str(serial_number).strip():
        normalized = normalize_serial_number(serial_number)
        updates["serial_number"] = normalized
        updates["serial_key"] = serial_key(normalized)
    if calibration_date is not None and str(calibration_date).strip():
        updates["calibration_date"] = str(calibration_date).strip()
    if location_id is not None:
        updates["location_id"] = int(location_id)
    if position is not None and str(position).strip():
        updates["position"] = str(position).strip()
    if not updates:
        return False
    updates["updated_at"] = datetime.now().isoformat(timespec="seconds")
    clause = ",".join(f"{key}=?" for key in updates)
    conn = _get_conn()
    try:
        conn.execute(
            f"UPDATE devices SET {clause} WHERE id=?",
            (*updates.values(), int(device_id)),
        )
        conn.commit()
        return True
    finally:
        conn.close()


init_db()
