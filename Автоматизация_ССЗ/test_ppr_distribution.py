import calendar
import os
import tempfile
import unittest
from collections import Counter
from unittest.mock import patch

from ssz_config import CONFIG
from ssz_schedule import (
    get_filtered_history,
    make_signature,
    record_cancelled_tasks,
    record_completed_tasks,
    record_issued_tasks,
    record_not_completed_tasks,
    redistribute_schedule,
)


def make_tasks(count, plan_day=1):
    return [
        {
            "task_kind": "ppr",
            "place": "Цех № 47",
            "plan_day": plan_day,
            "original_day": plan_day,
            "assigned_day": plan_day,
            "work": f"ППР прибору №{i}",
            "color_state": "uncolored",
        }
        for i in range(count)
    ]


class PprDistributionTests(unittest.TestCase):
    def setUp(self):
        import data_manager
        import staff_schedule

        self.temp_db_dir = tempfile.TemporaryDirectory(prefix="ppr_distribution_")
        self.old_db_path = data_manager.DB_PATH
        data_manager.DB_PATH = os.path.join(self.temp_db_dir.name, "app_data.db")
        data_manager.init_db()
        staff_schedule.invalidate_schedule_cache(reset_seed=True)
        self.old_enabled = CONFIG.get("redistribute_enabled")
        self.old_max = CONFIG.get("max_ppr_per_day")
        self.old_overflow = CONFIG.get("overflow_executor")
        self.old_overrides = CONFIG.get("executor_overrides")
        CONFIG["redistribute_enabled"] = True
        CONFIG["max_ppr_per_day"] = 2
        CONFIG["overflow_executor"] = "Наладчик КИПиА Войтов А.М."
        CONFIG["executor_overrides"] = []
        # Эти тесты проверяют только алгоритм ёмкости. Реальный табель и
        # отпуска проверяются отдельно в test_staff_schedule.py.
        self.staff_patches = (
            patch("staff_schedule.resolve_duty_executor", side_effect=lambda _day, name: name),
            patch("staff_schedule.get_day_executors", return_value=[]),
            patch("staff_schedule.is_staff_available", return_value=True),
        )
        for item in self.staff_patches:
            item.start()

    def tearDown(self):
        import data_manager
        import staff_schedule

        for item in reversed(self.staff_patches):
            item.stop()
        CONFIG["redistribute_enabled"] = self.old_enabled
        CONFIG["max_ppr_per_day"] = self.old_max
        CONFIG["overflow_executor"] = self.old_overflow
        CONFIG["executor_overrides"] = self.old_overrides
        data_manager.DB_PATH = self.old_db_path
        staff_schedule.invalidate_schedule_cache(reset_seed=True)
        self.temp_db_dir.cleanup()

    def distribute(self, year, month, count, target_day=1):
        sch = {d: [] for d in range(1, 32)}
        sch[1] = make_tasks(count)
        moved = []
        redistribute_schedule(sch, moved, month, target_day, t_year=year)
        return sch, moved

    def assert_person_limit(self, sch):
        for day, tasks in sch.items():
            counts = Counter(t["executor"] for t in tasks)
            self.assertTrue(all(n <= 2 for n in counts.values()), (day, counts))

    def test_february_has_only_real_dates(self):
        sch, _ = self.distribute(2026, 2, 60)
        self.assertEqual(list(sch), list(range(1, 29)))
        self.assertEqual(sum(map(len, sch.values())), 60)
        self.assert_person_limit(sch)

    def test_colored_or_unknown_task_cannot_enter_distribution(self):
        sch = {d: [] for d in range(1, 32)}
        task = make_tasks(1, plan_day=27)[0]
        task["color_state"] = "colored"
        sch[27] = [task]
        with self.assertRaisesRegex(RuntimeError, "без подтверждённого допуска"):
            redistribute_schedule(sch, [], 8, target_day=27, t_year=2026)

    def test_august_63_uses_one_reserve_slot(self):
        sch, _ = self.distribute(2026, 8, 63)
        self.assertEqual(sum(map(len, sch.values())), 63)
        self.assert_person_limit(sch)
        reserve = sum(
            t["executor"] == "Наладчик КИПиА Войтов А.М."
            for tasks in sch.values() for t in tasks
        )
        self.assertEqual(reserve, 1)

    def test_july_74_keeps_every_task_in_month(self):
        sch, _ = self.distribute(2026, 7, 74)
        self.assertEqual(sum(map(len, sch.values())), 74)
        self.assertEqual(max(sch), calendar.monthrange(2026, 7)[1])
        self.assert_person_limit(sch)

    def test_target_day_fills_requested_period_and_never_moves_into_past(self):
        later, _ = self.distribute(2026, 8, 63, target_day=20)
        self.assertEqual(sum(map(len, later.values())), 63)
        self.assertFalse(any(later[d] for d in range(1, 20)))
        self.assertEqual(len(later[20]), 6)
        self.assert_person_limit(later)

    def test_tasks_stay_on_plan_day_until_its_capacity_is_exhausted(self):
        sch = {d: [] for d in range(1, 32)}
        sch[27] = make_tasks(5, plan_day=27)
        moved = []
        redistribute_schedule(sch, moved, 8, target_day=8, t_year=2026)
        self.assertEqual(len(sch[27]), 2)
        self.assertEqual(len(sch[26]), 2)
        self.assertEqual(len(sch[28]), 1)
        self.assertFalse(any(sch[d] for d in range(1, 8)))

    def test_overflow_cannot_displace_tasks_from_their_own_plan_day(self):
        sch = {d: [] for d in range(1, 32)}
        sch[10] = make_tasks(3, plan_day=10)
        sch[11] = make_tasks(2, plan_day=11)
        moved = []
        redistribute_schedule(sch, moved, 8, target_day=1, t_year=2026)
        self.assertEqual(len(sch[10]), 2)
        self.assertEqual(len(sch[11]), 2)
        self.assertEqual(len(sch[9]), 1)
        self.assertTrue(all(task["plan_day"] == 11 for task in sch[11]))

    def test_overloaded_twelfth_uses_free_tenth_after_plan_dates_reserved(self):
        sch = {d: [] for d in range(1, 32)}
        sch[11] = make_tasks(2, plan_day=11)
        sch[12] = make_tasks(5, plan_day=12)
        sch[13] = make_tasks(2, plan_day=13)
        moved = []
        redistribute_schedule(sch, moved, 8, target_day=10, t_year=2026)
        self.assertEqual(len(sch[10]), 2)
        self.assertEqual(len(sch[11]), 2)
        self.assertEqual(len(sch[12]), 2)
        self.assertEqual(len(sch[13]), 2)
        self.assertEqual(len(sch[14]), 1)
        self.assertTrue(all(task["plan_day"] == 12 for task in sch[10]))

    def test_legacy_history_is_scoped_to_its_month(self):
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        try:
            old = "[17.06.2026] | Цех № 47 | План: 17 | Выполнить ППР прибору X."
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(old + "\n")
            with patch("ssz_schedule.get_history_file", return_value=path):
                _, completed = get_filtered_history(set())
            june = make_signature(
                "Цех № 47", 17, "Выполнить ППР прибору X.",
                plan_month=6, plan_year=2026,
            )
            august = make_signature(
                "Цех № 47", 17, "Выполнить ППР прибору X.",
                plan_month=8, plan_year=2026,
            )
            self.assertIn(june, completed)
            self.assertNotIn(august, completed)
        finally:
            os.remove(path)

    def test_print_completion_is_idempotent(self):
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        task = make_tasks(1, plan_day=8)[0]
        task.update(
            {
                "plan_month": 8,
                "plan_year": 2026,
                "assigned_day": 10,
                "executor": "Наладчик КИПиА Войтов А.М.",
            }
        )
        try:
            with patch("ssz_schedule.get_history_file", return_value=path):
                first = record_issued_tasks([("10.08.2026", [task])])
                second = record_issued_tasks([("10.08.2026", [task])])
                # Даже при повторной выдаче на другую дату это тот же месячный ППР.
                repeated = dict(task, assigned_day=12)
                third = record_issued_tasks([("12.08.2026", [repeated])])
                completed = record_completed_tasks([("10.08.2026", [task])])
                completed_again = record_completed_tasks([("10.08.2026", [task])])
            self.assertEqual(first, {"added": 1, "updated": 0, "skipped": 0})
            self.assertEqual(second, {"added": 0, "updated": 0, "skipped": 1})
            self.assertEqual(third, {"added": 0, "updated": 0, "skipped": 1})
            self.assertEqual(completed, {"added": 0, "updated": 1, "skipped": 0})
            self.assertEqual(completed_again, {"added": 0, "updated": 0, "skipped": 1})
            with open(path, "r", encoding="utf-8") as stream:
                lines = stream.readlines()
                self.assertEqual(len(lines), 1)
                self.assertIn("Статус: Выполнено", lines[0])
        finally:
            os.remove(path)

    def test_not_completed_returns_task_to_schedule_and_can_be_reissued(self):
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        task = make_tasks(1, plan_day=8)[0]
        task.update({"plan_month": 8, "plan_year": 2026, "executor": "Исполнитель"})
        try:
            with patch("ssz_schedule.get_history_file", return_value=path):
                record_issued_tasks([("08.08.2026", [task])])
                failed = record_not_completed_tasks([("08.08.2026", [task])])
                _kept, blocked = get_filtered_history(set())
                canonical = make_signature(
                    task["place"], 8, task["work"], plan_month=8, plan_year=2026
                )
                self.assertNotIn(canonical, blocked)
                reissued = record_issued_tasks([("10.08.2026", [dict(task, assigned_day=10)])])
                _kept, blocked_after = get_filtered_history(set())
            self.assertEqual(failed["updated"], 1)
            self.assertEqual(reissued["updated"], 1)
            self.assertIn(canonical, blocked_after)
            with open(path, "r", encoding="utf-8") as stream:
                line = stream.read()
            self.assertIn("[10.08.2026]", line)
            self.assertIn("Статус: Выдано", line)
        finally:
            os.remove(path)

    def test_cancelled_wrong_assignment_can_be_reissued_to_correct_executor(self):
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        task = make_tasks(1, plan_day=13)[0]
        task.update({"plan_month": 8, "plan_year": 2026, "executor": "Дмитриев"})
        try:
            with patch("ssz_schedule.get_history_file", return_value=path):
                record_issued_tasks([("29.08.2026", [task])])
                record_cancelled_tasks([("29.08.2026", [task])])
                corrected = dict(task, executor="Таратов", assigned_day=29)
                result = record_issued_tasks([("29.08.2026", [corrected])])
            self.assertEqual(result["updated"], 1)
            with open(path, "r", encoding="utf-8") as stream:
                line = stream.read()
            self.assertIn("Исполнитель: Таратов", line)
            self.assertIn("Статус: Выдано", line)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
