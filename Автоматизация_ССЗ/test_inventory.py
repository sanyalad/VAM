import sys
import os
import logging
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from inventory_main_widget import InventoryDashboardWidget
from inventory_components import format_date_ru, get_colored_date_html

# Make sure log dir exists
log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Логи")
os.makedirs(log_dir, exist_ok=True)
app_log = os.path.join(log_dir, "app_main.log")


def test_date_helpers():
    print("Testing date helpers...")
    assert format_date_ru("2026-07-17") == "17.07.2026"
    assert format_date_ru("invalid") == "invalid"
    assert "17.07.2026" in get_colored_date_html("2026-07-17")
    print("Date helpers: OK")


def test_widget_creation(app):
    print("Testing InventoryDashboardWidget creation...")
    widget = InventoryDashboardWidget()
    widget.set_role("admin")
    assert widget.btn_checklist.isHidden() is False
    
    widget.set_role("user")
    assert widget.btn_checklist.isHidden() is True
    
    # Check that refresh database runs without errors
    widget.refresh_db()
    
    # Check tabs count and names
    assert widget.tabs.count() == 7
    assert widget.tabs.tabText(0) == "План на день"
    assert widget.tabs.indexOf(widget.tab_attention) == 1
    assert widget.attention_table.columnCount() == 7
    assert widget.attention_table.rowCount() > 0
    print("InventoryDashboardWidget creation and tabs: OK")


def test_sys_excepthook_logging():
    print("Testing sys.excepthook logging simulation...")
    
    # Configure logging manually to avoid basicConfig block
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Remove existing handlers
    for h in list(logger.handlers):
        logger.removeHandler(h)
        
    # Clear log file if exists to verify fresh write
    if os.path.exists(app_log):
        try: os.remove(app_log)
        except Exception: pass
        
    fh = logging.FileHandler(app_log, encoding='utf-8')
    fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    logger.addHandler(fh)
    
    sh = logging.StreamHandler(sys.stdout)
    logger.addHandler(sh)
    
    # Simulate main.py _log_exception behavior
    def test_excepthook(exctype, value, tb):
        import io
        import traceback
        buf = io.StringIO()
        traceback.print_exception(exctype, value, tb, file=buf)
        err_text = buf.getvalue()
        logging.critical(f"Unhandled exception:\n{err_text}")
        
    sys.excepthook = test_excepthook
    
    # Trigger sys.excepthook manually
    ex = ValueError("SIMULATED CRITICAL UI ERROR FOR LOG TESTING")
    sys.excepthook(ValueError, ex, None)
    
    # Verify app_main.log exists and contains the exception text
    assert os.path.exists(app_log)
    with open(app_log, "r", encoding="utf-8") as f:
        content = f.read()
    
    assert "SIMULATED CRITICAL UI ERROR FOR LOG TESTING" in content
    print("sys.excepthook logging verification: OK")



if __name__ == "__main__":
    app = QApplication.instance()
    if not app:
        app = QApplication([])
        
    try:
        test_date_helpers()
        test_widget_creation(app)
        test_sys_excepthook_logging()
        print("\n=== ALL INVENTORY REFACTORING TESTS PASSED ===")
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
