import sqlite3
from datetime import datetime
from inventory_db import _get_conn, smart_upsert_device, replace_device

def init_checklist_tables():
    conn = _get_conn()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS replacement_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at DATETIME NOT NULL,
            executor TEXT NOT NULL,
            workshop_id INTEGER NOT NULL,
            location_id INTEGER NOT NULL,
            status TEXT DEFAULT 'open',
            note TEXT,
            FOREIGN KEY(workshop_id) REFERENCES workshops(id),
            FOREIGN KEY(location_id) REFERENCES locations(id)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS replacement_task_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            position TEXT NOT NULL,
            removed_device_id INTEGER,
            installed_device_id INTEGER,
            installed_name TEXT,
            installed_serial TEXT,
            installed_cal_date TEXT,
            status TEXT DEFAULT 'pending',
            FOREIGN KEY(task_id) REFERENCES replacement_tasks(id),
            FOREIGN KEY(removed_device_id) REFERENCES devices(id),
            FOREIGN KEY(installed_device_id) REFERENCES devices(id)
        )
    """)
    
    conn.commit()
    conn.close()

def create_replacement_task(executor, workshop_id, location_id, items_data, note=""):
    """
    items_data: list of dicts: [{'position': str, 'removed_device_id': int or None}]
    Returns task_id
    """
    conn = _get_conn()
    cursor = conn.cursor()
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO replacement_tasks (created_at, executor, workshop_id, location_id, note, status)
        VALUES (?, ?, ?, ?, ?, 'open')
    """, (now_str, executor, workshop_id, location_id, note))
    
    task_id = cursor.lastrowid
    
    for item in items_data:
        cursor.execute("""
            INSERT INTO replacement_task_items (task_id, position, removed_device_id)
            VALUES (?, ?, ?)
        """, (task_id, item['position'], item.get('removed_device_id')))
        
    conn.commit()
    conn.close()
    return task_id

def get_open_tasks():
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.id, t.created_at, t.executor, w.name, l.name, t.note,
               (SELECT COUNT(*) FROM replacement_task_items WHERE task_id = t.id) as items_count,
               (SELECT COUNT(*) FROM replacement_task_items WHERE task_id = t.id AND status = 'done') as items_done
        FROM replacement_tasks t
        JOIN workshops w ON t.workshop_id = w.id
        JOIN locations l ON t.location_id = l.id
        WHERE t.status = 'open'
        ORDER BY t.created_at DESC
    """)
    res = cursor.fetchall()
    conn.close()
    return [
        {
            "id": r[0], "created_at": r[1], "executor": r[2], 
            "workshop_name": r[3], "location_name": r[4], "note": r[5],
            "items_count": r[6], "items_done": r[7]
        }
        for r in res
    ]

def get_task_items(task_id):
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT i.id, i.position, i.removed_device_id, d.name, d.serial_number,
               i.installed_device_id, i.installed_name, i.installed_serial, i.installed_cal_date, i.status
        FROM replacement_task_items i
        LEFT JOIN devices d ON i.removed_device_id = d.id
        WHERE i.task_id = ?
    """, (task_id,))
    res = cursor.fetchall()
    
    # Get task details
    cursor.execute("SELECT workshop_id, location_id FROM replacement_tasks WHERE id = ?", (task_id,))
    task_res = cursor.fetchone()
    conn.close()
    
    items = []
    for r in res:
        items.append({
            "id": r[0],
            "position": r[1],
            "removed_device_id": r[2],
            "removed_name": r[3],
            "removed_serial": r[4],
            "installed_device_id": r[5],
            "installed_name": r[6],
            "installed_serial": r[7],
            "installed_cal_date": r[8],
            "status": r[9]
        })
    return {
        "workshop_id": task_res[0] if task_res else None,
        "location_id": task_res[1] if task_res else None,
        "items": items
    }

def save_item_result(item_id, installed_device_id, installed_name, installed_serial, installed_cal_date):
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE replacement_task_items 
        SET installed_device_id = ?, installed_name = ?, installed_serial = ?, installed_cal_date = ?, status = 'done'
        WHERE id = ?
    """, (installed_device_id, installed_name, installed_serial, installed_cal_date, item_id))
    conn.commit()
    conn.close()

def _move_device_to_storage(device_id):
    replace_device(device_id, to_storage=True)

def close_task(task_id):
    from operations_log import log_business_event
    
    # 1. Update the inventory based on items
    task_data = get_task_items(task_id)
    location_id = task_data['location_id']
    
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT executor FROM replacement_tasks WHERE id = ?", (task_id,))
    executor = cursor.fetchone()[0]
    conn.close()
    
    for item in task_data['items']:
        if item['status'] == 'done':
            # a. Remove old device to storage
            if item['removed_device_id']:
                _move_device_to_storage(item['removed_device_id'])
            
            # b. Install new device
            if item['installed_device_id']:
                # Existing device, update its location and calibration date
                conn = _get_conn()
                cursor = conn.cursor()
                cursor.execute("UPDATE devices SET location_id = ?, position = ?, calibration_date = ? WHERE id = ?", 
                               (location_id, item['position'], item['installed_cal_date'], item['installed_device_id']))
                conn.commit()
                conn.close()
            elif item['installed_name']:
                # New device, create it via smart_upsert_device
                smart_upsert_device(item['installed_name'], item['installed_serial'], location_id, item['installed_cal_date'], position=item['position'])

    # 2. Mark task as done
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("UPDATE replacement_tasks SET status = 'done' WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    
    log_business_event("TASK_CLOSED", f"Задание на замену #{task_id} закрыто. Исполнитель: {executor}.")

def delete_task(task_id):
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM replacement_task_items WHERE task_id = ?", (task_id,))
    cursor.execute("DELETE FROM replacement_tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()

def get_replacement_history(limit=100):
    conn = _get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.id, t.created_at, t.executor, w.name, l.name, t.note
        FROM replacement_tasks t
        JOIN workshops w ON t.workshop_id = w.id
        JOIN locations l ON t.location_id = l.id
        WHERE t.status = 'done'
        ORDER BY t.created_at DESC
        LIMIT ?
    """, (limit,))
    res = cursor.fetchall()
    
    history = []
    for r in res:
        task_id = r[0]
        cursor.execute("""
            SELECT i.position, d.name, d.serial_number,
                   i.installed_name, i.installed_serial, i.installed_cal_date, d2.name, d2.serial_number
            FROM replacement_task_items i
            LEFT JOIN devices d ON i.removed_device_id = d.id
            LEFT JOIN devices d2 ON i.installed_device_id = d2.id
            WHERE i.task_id = ? AND i.status = 'done'
        """, (task_id,))
        items_res = cursor.fetchall()
        items = []
        for ir in items_res:
            removed_str = f"{ir[1]} (№ {ir[2] or 'нет'})" if ir[1] else "Пусто"
            installed_str = ""
            if ir[6]: # Had device id
                installed_str = f"{ir[6]} (№ {ir[7] or 'нет'}) до {ir[5]}"
            elif ir[3]: # Name
                installed_str = f"{ir[3]} (№ {ir[4] or 'нет'}) до {ir[5]}"
            items.append({
                "position": ir[0],
                "removed": removed_str,
                "installed": installed_str
            })
            
        history.append({
            "task_id": r[0],
            "created_at": r[1],
            "executor": r[2],
            "workshop_name": r[3],
            "location_name": r[4],
            "note": r[5],
            "items": items
        })
    conn.close()
    return history
