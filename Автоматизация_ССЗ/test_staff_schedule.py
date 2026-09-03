import os
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

import data_manager
import staff_schedule
from ssz_config import CONFIG
from ssz_utils import get_day_executors, get_executor


class StaffScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "app.db")
        self.db_patch = patch.object(data_manager, "DB_PATH", self.db_path)
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
        staff_schedule.ensure_staff_seeded()

    def tearDown(self):
        self.config_patch.stop()
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_vacation_replacement_changes_duty_executor(self):
        staff_schedule.replace_absences([
            {
                "staff_name": "Наладчик КИПиА Сменный А",
                "start": "2026-08-27",
                "end": "2026-08-28",
                "absence_type": "Отпуск",
                "replacement_name": "Наладчик КИПиА Резерв",
            }
        ])
        self.assertEqual(get_executor(date(2026, 8, 27)), "Наладчик КИПиА Резерв")

    def test_missing_replacement_blocks_generation_date(self):
        staff_schedule.replace_absences([
            {
                "staff_name": "Наладчик КИПиА Сменный А",
                "start": "2026-08-27",
                "end": "2026-08-27",
                "absence_type": "Больничный",
                "replacement_name": "",
            }
        ])
        with self.assertRaisesRegex(RuntimeError, "замена не назначена"):
            get_executor(date(2026, 8, 27))

    def test_day_staff_is_available_only_on_workdays(self):
        self.assertIn("Наладчик КИПиА Дневной", get_day_executors(date(2026, 8, 27)))
        self.assertEqual(get_day_executors(date(2026, 8, 29)), [])

    def test_dmitriev_is_migrated_into_staff_register(self):
        names = {member["name"] for member in staff_schedule.list_staff()}
        self.assertIn("Наладчик КИПиА Дмитриев И.С.", names)

    def test_manual_shift_swap_changes_duty_executor(self):
        staff_schedule.replace_day_overrides([
            {
                "date": "2026-08-27",
                "staff_name": "Наладчик КИПиА Дневной",
                "status": "work",
                "replaces_name": "Наладчик КИПиА Сменный А",
                "reason": "Обмен сменами",
            }
        ])
        self.assertEqual(get_executor(date(2026, 8, 27)), "Наладчик КИПиА Дневной")
        self.assertNotIn("Наладчик КИПиА Дневной", get_day_executors(date(2026, 8, 27)))

    def test_manual_day_off_removes_day_employee(self):
        staff_schedule.replace_day_overrides([
            {
                "date": "2026-08-27",
                "staff_name": "Наладчик КИПиА Дневной",
                "status": "off",
                "replaces_name": "",
                "reason": "Отдых после обмена",
            }
        ])
        self.assertNotIn("Наладчик КИПиА Дневной", get_day_executors(date(2026, 8, 27)))

    def test_manual_day_off_without_shift_replacement_blocks_generation(self):
        staff_schedule.replace_day_overrides([
            {
                "date": "2026-08-27",
                "staff_name": "Наладчик КИПиА Сменный А",
                "status": "off",
                "replaces_name": "",
                "reason": "Обмен не заполнен",
            }
        ])
        with self.assertRaisesRegex(RuntimeError, "заменяющий не назначен"):
            get_executor(date(2026, 8, 27))

    def test_two_people_cannot_replace_same_shift(self):
        rows = [
            {
                "date": "2026-08-27", "staff_name": name, "status": "work",
                "replaces_name": "Наладчик КИПиА Сменный А", "reason": "",
            }
            for name in ("Наладчик КИПиА Дневной", "Наладчик КИПиА Резерв")
        ]
        with self.assertRaisesRegex(ValueError, "несколько человек"):
            staff_schedule.replace_day_overrides(rows)


if __name__ == "__main__":
    unittest.main()
