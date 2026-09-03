import sqlite3
import os
import json
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "app_data.db")

def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        # Quick integrity verification
        conn.execute("PRAGMA integrity_check(1)")
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        return conn
    except (sqlite3.DatabaseError, sqlite3.OperationalError) as e:
        print(f"[data_manager] SQLite database corrupted or locked: {e}. Recreating...")
        try:
            if 'conn' in locals():
                conn.close()
        except Exception:
            pass
            
        if os.path.exists(DB_PATH):
            bak_path = DB_PATH + f".corrupted_{int(datetime.now().timestamp())}"
            try:
                os.rename(DB_PATH, bak_path)
            except Exception:
                try:
                    os.remove(DB_PATH)
                except Exception:
                    pass
                    
        for suffix in ("-wal", "-shm"):
            p = DB_PATH + suffix
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
                    
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
            
        _init_db_tables(conn)
        return conn

def _init_db_tables(conn):
    cursor = conn.cursor()
    # 1. operations_log
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS operations_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event TEXT NOT NULL,
            detail TEXT
        )
    """)
    # 2. crash_log
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS crash_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            content TEXT NOT NULL
        )
    """)
    # 3. manual_tasks_cache
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS manual_tasks_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work TEXT NOT NULL,
            place TEXT NOT NULL,
            UNIQUE(work, place)
        )
    """)
    # 4. bulk_extra_cache
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bulk_extra_cache (
            date_str TEXT PRIMARY KEY,
            tasks_json TEXT NOT NULL
        )
    """)
    # 5. excel_color_cache
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS excel_color_cache (
            file_key TEXT PRIMARY KEY,
            colored_cells_json TEXT NOT NULL
        )
    """)
    # 6. ppr_history
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ppr_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry TEXT NOT NULL UNIQUE
        )
    """)
    # 7. audit_log
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            message TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS staff_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            work_mode TEXT NOT NULL CHECK(work_mode IN ('shift_a','shift_b','day')),
            role TEXT NOT NULL DEFAULT 'Наладчик КИПиА',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS staff_absences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_name TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            absence_type TEXT NOT NULL,
            replacement_name TEXT,
            note TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK(end_date >= start_date)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_staff_absences_period
        ON staff_absences(start_date, end_date, staff_name)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS staff_day_overrides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_date TEXT NOT NULL,
            staff_name TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('work','off')),
            replaces_name TEXT,
            reason TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(work_date, staff_name)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_staff_day_overrides_date
        ON staff_day_overrides(work_date, staff_name, status)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ppr_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_key TEXT NOT NULL,
            event_type TEXT NOT NULL,
            event_at TEXT NOT NULL,
            assigned_date TEXT,
            executor TEXT,
            note TEXT
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_ppr_events_task
        ON ppr_events(task_key, event_at)
    """)
    conn.commit()

def init_db():
    conn = get_conn()
    _init_db_tables(conn)
    conn.close()

    
    # Migrate old data once initialized
    try:
        migrate_old_files()
    except Exception as e:
        print(f"[data_manager] Error migrating old files: {e}")

# ═══════════════════════════════════════════════════════════════════════════
#  Migration from old text/json files
# ═══════════════════════════════════════════════════════════════════════════

def migrate_old_files():
    # 1. Manual tasks cache
    old_manual = "Кэш_доп_заданий.txt"
    if os.path.exists(old_manual):
        conn = get_conn()
        try:
            with open(old_manual, "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split(" | ", 1)
                    if len(parts) == 2:
                        conn.execute("""
                            INSERT OR IGNORE INTO manual_tasks_cache (work, place)
                            VALUES (?, ?)
                        """, (parts[0], parts[1]))
            conn.commit()
            # Rename old file so we don't migrate it again
            os.rename(old_manual, old_manual + ".bak")
        except Exception as e:
            print(f"[data_manager] Manual tasks migration failed: {e}")
        finally:
            conn.close()

    # 2. Bulk extra cache
    old_bulk = "Кэш_массовых_доп_заданий.json"
    if os.path.exists(old_bulk):
        conn = get_conn()
        try:
            with open(old_bulk, "r", encoding="utf-8") as f:
                raw = json.load(f)
                by_date = raw.get("by_date", {})
                for date_str, tasks in by_date.items():
                    conn.execute("""
                        INSERT OR REPLACE INTO bulk_extra_cache (date_str, tasks_json)
                        VALUES (?, ?)
                    """, (date_str, json.dumps(tasks, ensure_ascii=False)))
            conn.commit()
            os.rename(old_bulk, old_bulk + ".bak")
        except Exception as e:
            print(f"[data_manager] Bulk extra tasks migration failed: {e}")
        finally:
            conn.close()

    # 3. Excel colors cache
    old_colors = "Кэш_цветов_графиков.json"
    if os.path.exists(old_colors):
        conn = get_conn()
        try:
            with open(old_colors, "r", encoding="utf-8") as f:
                raw = json.load(f)
                for file_key, cells in raw.items():
                    # cells is list of [row, col]
                    conn.execute("""
                        INSERT OR REPLACE INTO excel_color_cache (file_key, colored_cells_json)
                        VALUES (?, ?)
                    """, (file_key, json.dumps(cells)))
            conn.commit()
            os.rename(old_colors, old_colors + ".bak")
        except Exception as e:
            print(f"[data_manager] Excel colors cache migration failed: {e}")
        finally:
            conn.close()

    # 4. PPR History
    from ssz_config import CONFIG
    old_history = CONFIG.get("history_file", "Учет_выполненных_ППР.txt")
    if os.path.exists(old_history):
        conn = get_conn()
        try:
            with open(old_history, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for line in lines:
                s = line.strip()
                if s:
                    conn.execute("INSERT OR IGNORE INTO ppr_history (entry) VALUES (?)", (s,))
            conn.commit()
            # Do NOT rename history_file, since users might expect it to still be there,
            # but we sync it. We will keep writing/reading from SQLite as the primary source,
            # or sync both. Let's sync both to be safe, or just use SQLite.
        except Exception as e:
            print(f"[data_manager] History migration failed: {e}")
        finally:
            conn.close()

# ═══════════════════════════════════════════════════════════════════════════
#  Logging APIs
# ═══════════════════════════════════════════════════════════════════════════

def db_log_operation(event, detail=""):
    try:
        conn = get_conn()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("""
            INSERT INTO operations_log (timestamp, event, detail)
            VALUES (?, ?, ?)
        """, (ts, event, detail))
        conn.commit()
        conn.close()
    except Exception:
        pass

def db_log_audit(message):
    try:
        conn = get_conn()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("""
            INSERT INTO audit_log (timestamp, message)
            VALUES (?, ?)
        """, (ts, message))
        conn.commit()
        conn.close()
    except Exception:
        pass

def db_log_crash(content):
    try:
        conn = get_conn()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("""
            INSERT INTO crash_log (timestamp, content)
            VALUES (?, ?)
        """, (ts, content))
        conn.commit()
        conn.close()
    except Exception:
        pass

def db_read_log_tail(max_lines=120):
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT timestamp, event, detail FROM operations_log
            ORDER BY id DESC LIMIT ?
        """, (max_lines,))
        rows = cursor.fetchall()
        conn.close()
        
        lines = []
        for r in reversed(rows):
            line = f"{r[0]} [{r[1]}]"
            if r[2]:
                line += f" {r[2]}"
            lines.append(line)
        return "\n".join(lines) if lines else "Журнал пуст."
    except Exception as e:
        return f"Не удалось прочитать журнал: {e}"

# ═══════════════════════════════════════════════════════════════════════════
#  Manual Tasks Cache APIs
# ═══════════════════════════════════════════════════════════════════════════

def db_load_manual_tasks():
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT work, place FROM manual_tasks_cache ORDER BY id ASC")
        rows = cursor.fetchall()
        conn.close()
        return [(r[0], r[1]) for r in rows]
    except Exception:
        return []

def db_save_manual_task(work, place):
    try:
        conn = get_conn()
        # Delete first if exists to update its order (move to end)
        conn.execute("DELETE FROM manual_tasks_cache WHERE work = ? AND place = ?", (work, place))
        conn.execute("INSERT OR REPLACE INTO manual_tasks_cache (work, place) VALUES (?, ?)", (work, place))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

# ═══════════════════════════════════════════════════════════════════════════
#  Bulk Extra Cache APIs
# ═══════════════════════════════════════════════════════════════════════════

def db_load_bulk_extra():
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT date_str, tasks_json FROM bulk_extra_cache")
        rows = cursor.fetchall()
        conn.close()
        return {r[0]: json.loads(r[1]) for r in rows}
    except Exception:
        return {}

def db_save_bulk_extra(date_str, tasks):
    try:
        conn = get_conn()
        if tasks:
            conn.execute("""
                INSERT OR REPLACE INTO bulk_extra_cache (date_str, tasks_json)
                VALUES (?, ?)
            """, (date_str, json.dumps(tasks, ensure_ascii=False)))
        else:
            conn.execute("DELETE FROM bulk_extra_cache WHERE date_str = ?", (date_str,))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

# ═══════════════════════════════════════════════════════════════════════════
#  Excel Colors Cache APIs
# ═══════════════════════════════════════════════════════════════════════════

def db_load_excel_colors():
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT file_key, colored_cells_json FROM excel_color_cache")
        rows = cursor.fetchall()
        conn.close()
        result = {}
        for file_key, payload_json in rows:
            payload = json.loads(payload_json)
            if isinstance(payload, dict):
                result[file_key] = {
                    "checked": set(tuple(c) for c in payload.get("checked", [])),
                    "colored": set(tuple(c) for c in payload.get("colored", [])),
                }
            else:
                # Legacy v3 entries contained only colored coordinates.
                result[file_key] = set(tuple(c) for c in payload)
        return result
    except Exception:
        return {}

def db_save_excel_color(file_key, cells):
    try:
        conn = get_conn()
        if isinstance(cells, dict):
            payload = {
                "checked": [list(c) for c in cells.get("checked", set())],
                "colored": [list(c) for c in cells.get("colored", set())],
            }
        else:
            payload = [list(c) for c in cells]
        conn.execute("""
            INSERT OR REPLACE INTO excel_color_cache (file_key, colored_cells_json)
            VALUES (?, ?)
        """, (file_key, json.dumps(payload)))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def db_prune_excel_colors(active_version="v5", max_entries=64):
    """Remove obsolete/redundant cache rows; all data is safely reproducible."""
    try:
        conn = get_conn()
        conn.execute(
            "DELETE FROM excel_color_cache WHERE file_key NOT LIKE ?",
            (f"%|{active_version}",),
        )
        conn.execute(
            """
            DELETE FROM excel_color_cache
            WHERE rowid NOT IN (
                SELECT rowid FROM excel_color_cache
                ORDER BY rowid DESC LIMIT ?
            )
            """,
            (int(max_entries),),
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

# ═══════════════════════════════════════════════════════════════════════════
#  PPR History APIs
# ═══════════════════════════════════════════════════════════════════════════

def db_load_ppr_history():
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT entry FROM ppr_history ORDER BY id ASC")
        rows = cursor.fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []

def db_add_ppr_history(entry):
    try:
        conn = get_conn()
        conn.execute("INSERT OR IGNORE INTO ppr_history (entry) VALUES (?)", (entry,))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

def db_clear_ppr_history_pattern(pattern):
    try:
        conn = get_conn()
        conn.execute("DELETE FROM ppr_history WHERE entry LIKE ?", (pattern,))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False
