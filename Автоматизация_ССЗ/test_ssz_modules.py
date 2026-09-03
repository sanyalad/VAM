import os
from PyQt6.QtWidgets import QApplication, QDialog
from PyQt6.QtCore import Qt

from ssz_dialogs import (
    auto_correct_task,
    auto_correct_place,
    manual_cache_combo_lists,
    AnalysisWarningsDialog,
)
from ssz_controller import WorkerController
from data_manager import (
    init_db,
    db_save_manual_task,
    db_load_manual_tasks,
)

# Ensure QApplication is initialized for UI tests
def qapp():
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    return app


def test_auto_correct_task():
    assert auto_correct_task("проверить прибор") == "Проверить прибор."
    assert auto_correct_task("Проверить прибор.") == "Проверить прибор."
    assert auto_correct_task("  проверить прибор!  ") == "Проверить прибор!"
    assert auto_correct_task("") == ""


def test_auto_correct_place():
    assert auto_correct_place("") == "Цеха обслуживания"
    assert auto_correct_place("47") == "Цех № 47"
    assert auto_correct_place("исм") == "ИСМ"
    assert auto_correct_place("Цех 6") == "Цех № 6"
    assert auto_correct_place("Кладовка") == "Кладовка"


def test_manual_cache_combo_lists():
    cached = [("Задание 1", "Цех 1"), ("Задание 2", "Цех 2"), ("Задание 1", "Цех 2")]
    works, places = manual_cache_combo_lists(cached)
    assert "Задание 1" in works
    assert "Задание 2" in works
    assert len(works) == 2
    assert "Цех 1" in places
    assert "Цех 2" in places
    assert len(places) == 2


def test_analysis_warnings_dialog(qapp):
    dialog = AnalysisWarningsDialog(["Предупреждение 1", "Предупреждение 2"])
    assert dialog.windowTitle() == "Предупреждения анализа"
    # Clean up
    dialog.close()


def test_data_manager_robustness():
    # Verify DB initialization and fallback
    init_db()
    
    # Save/load manual tasks
    db_save_manual_task("Тестовое задание КИП", "Цех № 47")
    tasks = db_load_manual_tasks()
    assert ("Тестовое задание КИП", "Цех № 47") in tasks


def test_corrupted_cache_files():
    # Simulate corrupted old cache file scenario
    corrupted_txt = "Кэш_доп_заданий.txt"
    with open(corrupted_txt, "w", encoding="utf-8") as f:
        f.write("Some completely garbled data without pipes or structure\n")
        f.write("Also invalid line\n")
    
    # Import and verify ssz_window load_manual_cache handles it without crashing
    from ssz_window import SszWindow
    try:
        window = SszWindow()
        window.load_manual_cache()
    finally:
        if os.path.exists(corrupted_txt):
            os.remove(corrupted_txt)
        if os.path.exists(corrupted_txt + ".bak"):
            os.remove(corrupted_txt + ".bak")


def test_manual_task_executor(qapp):
    from ssz_window import SszWindow
    win = SszWindow()
    win.ent_manual_work.setCurrentText("Проверка КИПиА")
    win.ent_manual_place.setCurrentText("Цех № 47")
    win.ent_manual_exec.setCurrentText("Наладчик КИПиА Дмитриев И.С.")
    win.add_manual_task()
    assert len(win.manual_tasks) == 1
    assert win.manual_tasks[0]["executor"] == "Наладчик КИПиА Дмитриев И.S." or win.manual_tasks[0]["executor"] == "Наладчик КИПиА Дмитриев И.С."
    assert "Дмитриев" in win.table_manual.item(0, 2).text()
    win.close()


if __name__ == "__main__":
    import sys
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    # Run test functions manually
    try:
        test_auto_correct_task()
        print("test_auto_correct_task: PASS")
        
        test_auto_correct_place()
        print("test_auto_correct_place: PASS")
        
        test_manual_cache_combo_lists()
        print("test_manual_cache_combo_lists: PASS")
        
        test_analysis_warnings_dialog(app)
        print("test_analysis_warnings_dialog: PASS")
        
        test_data_manager_robustness()
        print("test_data_manager_robustness: PASS")
        
        test_corrupted_cache_files()
        print("test_corrupted_cache_files: PASS")
        
        test_manual_task_executor(app)
        print("test_manual_task_executor: PASS")
        
        print("\n=== ALL SSZ UNIT TESTS PASSED ===")
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
