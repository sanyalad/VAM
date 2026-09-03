import os
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import data_manager
import staff_schedule
from ssz_config import CONFIG
from ssz_dialogs import ExecutorOverrideDialog


class StaffCalendarUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(
            data_manager, "DB_PATH", os.path.join(self.temp_dir.name, "calendar.db")
        )
        self.db_patch.start()
        self.config_patch = patch.dict(
            CONFIG,
            {
                "executor_1": "Наладчик КИПиА Сменный А",
                "executor_2": "Наладчик КИПиА Сменный Б",
                "overflow_executor": "Наладчик КИПиА Дневной",
                "duty_epoch": date(2026, 8, 27),
                "executor_overrides": [],
            },
        )
        self.config_patch.start()
        staff_schedule.invalidate_schedule_cache(reset_seed=True)
        staff_schedule.ensure_staff_seeded()

    def tearDown(self):
        staff_schedule.invalidate_schedule_cache(reset_seed=True)
        self.config_patch.stop()
        self.db_patch.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def _row_for(dialog, name):
        for row in range(dialog.month_table.rowCount()):
            if dialog.month_table.item(row, 0).text().split("\n", 1)[0] == name:
                return row
        raise AssertionError(f"Сотрудник не найден: {name}")

    def _open_august(self):
        dialog = ExecutorOverrideDialog()
        dialog.month_year.setValue(2026)
        dialog.month_combo.setCurrentIndex(7)
        dialog._refresh_month_table()
        return dialog

    def test_replacement_inherits_absent_shift_pattern(self):
        staff_schedule.replace_absences(
            [
                {
                    "staff_name": "Наладчик КИПиА Сменный А",
                    "start": "2026-08-27",
                    "end": "2026-08-30",
                    "absence_type": "Отпуск",
                    "replacement_name": "Наладчик КИПиА Дневной",
                }
            ]
        )
        dialog = self._open_august()
        row = self._row_for(dialog, "Наладчик КИПиА Дневной")
        self.assertEqual(
            [dialog.month_table.item(row, day).text() for day in range(27, 31)],
            ["С", "С", "В", "В"],
        )
        self.assertIn("заменяет Наладчик КИПиА Сменный А", dialog.month_table.item(row, 27).toolTip())
        dialog.close()

    def test_manual_work_and_off_are_visible_in_calendar(self):
        staff_schedule.replace_day_overrides(
            [
                {
                    "date": "2026-08-27",
                    "staff_name": "Наладчик КИПиА Дневной",
                    "status": "work",
                    "replaces_name": "Наладчик КИПиА Сменный А",
                    "reason": "Обмен сменами",
                },
                {
                    "date": "2026-08-28",
                    "staff_name": "Наладчик КИПиА Дневной",
                    "status": "off",
                    "replaces_name": "",
                    "reason": "Отдых после обмена",
                },
            ]
        )
        dialog = self._open_august()
        day_row = self._row_for(dialog, "Наладчик КИПиА Дневной")
        shift_row = self._row_for(dialog, "Наладчик КИПиА Сменный А")
        self.assertEqual(dialog.month_table.item(day_row, 27).text(), "С")
        self.assertEqual(dialog.month_table.item(day_row, 28).text(), "В")
        self.assertIn("Работает вместо", dialog.month_table.item(day_row, 27).toolTip())
        self.assertIn("Смену выполняет", dialog.month_table.item(shift_row, 27).toolTip())
        dialog.close()

    def test_non_contiguous_days_can_be_marked_as_working(self):
        dialog = self._open_august()
        row = self._row_for(dialog, "Наладчик КИПиА Дневной")
        dialog.month_table.clearSelection()
        dialog.month_table.item(row, 27).setSelected(True)
        dialog.month_table.item(row, 29).setSelected(True)
        dialog._update_selection_panel()
        self.assertTrue(dialog.btn_apply_manual.isEnabled())
        self.assertFalse(dialog.btn_apply_range.isEnabled())
        dialog.manual_status_combo.setCurrentIndex(0)
        dialog._apply_manual_schedule()
        overrides = [
            item for item in dialog.day_override_rows
            if item["staff_name"] == "Наладчик КИПиА Дневной"
        ]
        self.assertEqual({item["date"] for item in overrides}, {"2026-08-27", "2026-08-29"})
        self.assertTrue(all(item["status"] == "work" for item in overrides))
        dialog.close()


if __name__ == "__main__":
    unittest.main()
