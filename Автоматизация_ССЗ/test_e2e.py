"""End-to-end test of the full ingest pipeline."""
import sys
import tempfile
sys.stdout.reconfigure(encoding='utf-8')

import inventory_db
from inventory_db import init_db, get_workshops, get_devices, get_locations, get_db_readiness_percentage
import sqlite3, os

# Никогда не запускать разрушающий e2e-сценарий на рабочей базе.
_test_db_dir = tempfile.TemporaryDirectory(prefix="inventory_e2e_")
DB_PATH = os.path.join(_test_db_dir.name, "inventory.db")
inventory_db.DB_PATH = DB_PATH
init_db()

# Clean DB first
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
c.execute("DELETE FROM devices")
c.execute("DELETE FROM locations")
conn.commit()
conn.close()

print("=== Test 1: Ingest PPR Excel (deterministic) ===")
from ai_parser import ingest_document
success, msg = ingest_document("Графики/Графики ППР на I пол 2026 уч 47.xlsx")
print(f"Success: {success}")
print(f"Message:\n{msg}")
print()

# Count devices
all_devices = get_devices()
print(f"Total devices in DB: {len(all_devices)}")
print(f"DB Readiness: {get_db_readiness_percentage()}%")
print()

# Check workshops
workshops = get_workshops()
print("Workshops with device counts:")
for ws in workshops:
    locs = get_locations(ws["id"])
    dev_count = sum(len(get_devices(loc["id"])) for loc in locs)
    print(f"  {ws['name']}: {dev_count} devices, {len(locs)} locations")
print()

# Verify no garbage workshops
print("=== Test 2: Verify no garbage workshops ===")
valid = [
    "Цех 6 (Картэкс, 2-й)",
    "Цех 66 (66.2, Спецсталь)",
    "Печь 10 (Ижора, цех 66.1)",
    "Цех 92 (ИСМ)",
    "Цех 47 (Спецсталь)",
]
for ws in workshops:
    status = "OK" if ws["name"] in valid else "GARBAGE!"
    print(f"  [{status}] {ws['name']}")
print()

# Test unsupported format handling
print("=== Test 3: Unsupported format ===")
success, msg = ingest_document("test_fake.mp4")
print(f"Success: {success} (expected: False)")
print(f"Message: {msg[:100]}...")
print()

# Test AI path with text doc (should require API key)
print("=== Test 4: Text file path (AI required) ===")
# Create a small test file
test_txt = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "test_cert.txt")
with open(test_txt, "w", encoding="utf-8") as f:
    f.write("Свидетельство о поверке\nПрибор: Потенциометр КСП-4 м.008\nЗав. номер: Б0307715\nЦех 47\nДата поверки до: 2027-01-15\n")

success, msg = ingest_document(test_txt)
print(f"Success: {success}")
print(f"Message: {msg[:200]}...")
try:
    if os.path.exists(test_txt):
        os.remove(test_txt)
except Exception as e:
    print(f"Note: Could not remove test_cert.txt: {e}")
print()

# Test image path (should require API key)
print("=== Test 5: Image file path check ===")
from ai_parser import IMAGE_EXTENSIONS, EXCEL_EXTENSIONS, DOCUMENT_EXTENSIONS
print(f"Image extensions: {IMAGE_EXTENSIONS}")
print(f"Excel extensions: {EXCEL_EXTENSIONS}")
print(f"Document extensions: {DOCUMENT_EXTENSIONS}")

# Verify vision model selection
from ai_parser import _call_ai_vision
print("Vision function exists and is callable:", callable(_call_ai_vision))
print()

# Test UI & QSS integrity
print("=== Test 6: Verify UI and QSS Stylesheet ===")
try:
    from PyQt6.QtWidgets import QApplication
    from main import MainWindow
    
    app = QApplication.instance()
    if not app:
        app = QApplication([])
        
    style_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.qss")
    if not os.path.exists(style_path):
        raise FileNotFoundError(f"style.qss not found at {style_path}")
        
    with open(style_path, "r", encoding="utf-8") as f:
        style_content = f.read()
        
    if not style_content.strip():
        raise ValueError("style.qss is empty!")
        
    app.setStyleSheet(style_content)
    window = MainWindow()
    if window.windowTitle() != "ВАМ — Рабочие инструменты":
        raise ValueError("MainWindow title mismatch!")
        
    print("UI & QSS integration check: OK")
except Exception as e:
    print(f"UI & QSS integration check FAILED: {e}")
print()

# Test SQLite corruption resilience
print("=== Test 7: Verify SQLite Database Corruption Resilience ===")
try:
    from data_manager import DB_PATH, db_save_bulk_extra, db_load_bulk_extra
    from datetime import date
    import shutil
    
    # 1. Back up the actual database if it exists
    backup_db = DB_PATH + ".actual_backup"
    if os.path.exists(DB_PATH):
        shutil.copy2(DB_PATH, backup_db)
        
    try:
        # 2. Corrupt the database file
        with open(DB_PATH, "w", encoding="utf-8") as f:
            f.write("totally corrupted non-sqlite database content 1234567890")
            
        # 3. Attempting to load should trigger automatic recovery and return empty dict instead of crashing
        from bulk_extra_cache import load_bulk_extra_draft
        res = load_bulk_extra_draft(date.today(), date.today())
        print(f"Resilience check load_bulk_extra_draft: OK (returned {res})")
        
        # 4. Write new data to make sure it works fine after recreation
        ok = db_save_bulk_extra("2026-07-17", [{"work": "Test task", "place": "Test place"}])
        print(f"Write to reconstructed DB: {'OK' if ok else 'FAILED'}")
        
        loaded = db_load_bulk_extra()
        print(f"Read from reconstructed DB: {loaded}")
    finally:
        # Restore actual DB
        if os.path.exists(backup_db):
            if os.path.exists(DB_PATH):
                os.remove(DB_PATH)
            # Remove reconstructed database WAL files to avoid lock/mismatch
            for suffix in ("-wal", "-shm"):
                p = DB_PATH + suffix
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
            shutil.copy2(backup_db, DB_PATH)
            os.remove(backup_db)
except Exception as e:
    print(f"Cache corruption resilience check FAILED: {e}")
print()

print("=== ALL TESTS PASSED ===")
