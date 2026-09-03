import os
import unittest
from datetime import date
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog, QPushButton

from ppr_dashboard import PprDashboardWidget
from ppr_printer import PprPrintDialog, ppr_form_for_task


class PprDashboardPrintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_task_form_is_determined_by_workshop_and_device_type(self):
        cases = (
            ({"place": "Цех № 47", "work": "ППР термопары"}, "Спецсталь — обычный ППР"),
            ({"place": "Цех № 66-2", "work": "ППР МЭО 25/63"}, "Спецсталь — МЭО"),
            ({"place": "ИСМ", "work": "ППР прибора"}, "ИСМ — обычный ППР"),
            ({"place": "Цех № 6", "work": "ППР МЭО"}, "КАРТЭКС — МЭО"),
            ({"place": "Печь 10 Ижора", "work": "ППР прибора"}, "Ижора — обычный ППР"),
        )
        for task, expected in cases:
            with self.subTest(task=task):
                self.assertEqual(ppr_form_for_task(task)[0], expected)
        self.assertIsNone(ppr_form_for_task({"place": "Неизвестно", "work": "ППР"}))

    def test_locked_dialog_uses_exact_selected_task_counts(self):
        filename = PprPrintDialog.FORMS[0][1]
        dialog = PprPrintDialog(initial_counts={filename: 7}, lock_counts=True)
        self.assertTrue(dialog.forms_table.cellWidget(0, 0).isChecked())
        self.assertFalse(dialog.forms_table.cellWidget(0, 0).isEnabled())
        self.assertEqual(dialog.forms_table.cellWidget(0, 2).value(), 7)
        self.assertFalse(dialog.forms_table.cellWidget(0, 2).isEnabled())
        dialog.close()

    def test_selected_blank_forms_print_without_changing_issue_status(self):
        widget = PprDashboardWidget()
        task = {
            "task_kind": "ppr",
            "place": "Цех № 47",
            "work": "Выполнить ППР прибору TEST",
            "plan_day": 10,
            "plan_month": 8,
            "plan_year": 2026,
            "assigned_date": date(2026, 8, 10),
            "executor": "Наладчик КИПиА Тестов Т.Т.",
        }
        widget._set_task_print_selected(task, True)
        captured = {}

        class AcceptedDialog:
            def __init__(self, _parent, initial_counts, lock_counts):
                captured["counts"] = initial_counts
                captured["locked"] = lock_counts

            def exec(self):
                return QDialog.DialogCode.Accepted

        with patch("ppr_dashboard.PprPrintDialog", AcceptedDialog), patch(
            "ppr_dashboard.record_issued_tasks"
        ) as record, patch("ppr_dashboard.QMessageBox.information"):
            widget._print_selected_ppr()

        self.assertEqual(sum(captured["counts"].values()), 1)
        self.assertTrue(captured["locked"])
        record.assert_not_called()
        self.assertEqual(widget._print_selection, {})
        widget.close()

    def test_colored_history_record_is_not_shown_as_active(self):
        widget = PprDashboardWidget()
        widget.current_month = 8
        widget.current_year = 2026
        widget.today_day = 28
        task = {
            "task_kind": "ppr", "place": "Цех № 47", "work": "ППР COLOR",
            "plan_day": 28, "plan_month": 8, "plan_year": 2026,
            "assigned_date": date(2026, 8, 28), "executor": "Дмитриев",
        }
        canonical = widget._print_task_key(task)
        history = [{"canonical": canonical, "status": "Выдано", "task": task}]
        result = {
            "month_schedules": {8: {}},
            "colored_skipped": [{
                "place": task["place"], "work": task["work"], "day": 28,
                "month": 8, "year": 2026,
            }],
        }
        with patch("ppr_dashboard.get_ppr_history_records", return_value=history):
            widget.on_data_loaded(result)
        self.assertEqual(widget.lbl_issued_cnt.text(), "🟠 Выдано: 0")
        self.assertEqual(widget.tabs.count(), 0)
        widget.close()

    def test_not_completed_card_has_print_checkbox(self):
        widget = PprDashboardWidget()
        task = {
            "place": "Цех № 6", "work": "ППР прибора", "plan_day": 12,
            "plan_month": 8, "plan_year": 2026, "assigned_date": date(2026, 8, 12),
        }
        card = widget._create_task_card(task, "not_completed")
        checkbox = next(
            item for item in card.findChildren(QPushButton)
            if "Выбрать для печати" in item.text()
        )
        checkbox.setChecked(True)
        self.assertEqual(len(widget._print_selection), 1)
        self.assertTrue(widget.btn_print_selected.isEnabled())
        widget.close()

    def test_issued_card_can_be_selected_for_repeat_print(self):
        widget = PprDashboardWidget()
        task = {
            "place": "Цех № 47", "work": "ППР прибора", "plan_day": 12,
            "plan_month": 8, "plan_year": 2026, "assigned_date": date(2026, 8, 12),
        }
        card = widget._create_task_card(task, "issued")
        selector = next(
            item for item in card.findChildren(QPushButton)
            if "Повторно в печать" in item.text()
        )
        selector.setChecked(True)
        self.assertEqual(len(widget._print_selection), 1)
        self.assertIn("Выбрано", selector.text())
        widget.close()


if __name__ == "__main__":
    unittest.main()
