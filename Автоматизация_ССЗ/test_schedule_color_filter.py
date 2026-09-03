import os
import tempfile
import unittest
from unittest.mock import patch

from openpyxl import Workbook
from openpyxl.styles import PatternFill
from openpyxl.formatting.rule import FormulaRule

import ssz_schedule
from ssz_safety import PprSafetyError


class FakeColorSession:
    def __init__(self, colored=()):
        self.colored = set(colored)
        self.failures = []
        self.requested = set()

    def check_cells(self, _path, cells, *_args, **_kwargs):
        self.requested.update(cells)
        return set(cells) & self.colored


class ScheduleColorFilterIntegrationTests(unittest.TestCase):
    def test_conditional_format_display_color_is_filtered_by_excel_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "Графики ППР на II пол conditional.xlsx")
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "цех 47"
            for column in range(7, 13):
                sheet.cell(10, column).value = "План"
            sheet.cell(11, 2).value = "Позиция 1"
            sheet.cell(11, 3).value = "Потенциометр"
            sheet.cell(11, 4).value = "КСД-3"
            sheet.cell(11, 5).value = "CF-001"
            sheet.cell(11, 8).value = 27
            sheet.conditional_formatting.add(
                "H11",
                FormulaRule(
                    formula=["TRUE"],
                    fill=PatternFill("solid", fgColor="FFF2CC"),
                ),
            )
            workbook.save(path)

            session = FakeColorSession({("цех 47", 10, 7)})
            config_override = {
                "schedules_dir": temp_dir,
                "prefer_xlsx": True,
                "redistribute_enabled": False,
            }
            with patch.dict(ssz_schedule.CONFIG, config_override), patch.object(
                ssz_schedule, "log_operation"
            ):
                schedule, colored, _moved = ssz_schedule.fetch_month_schedules(
                    8, set(), color_session=session, target_day=27, t_year=2026
                )

            assigned = [task for tasks in schedule.values() for task in tasks]
            self.assertFalse(any("CF-001" in task["work"] for task in assigned))
            matched = next(task for task in colored if "CF-001" in task["work"])
            self.assertEqual(matched["color_source"], "excel_display_format")
            self.assertEqual(matched["source_cell"], "H11")

    def test_colored_ppr_never_reaches_assignment_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "Графики ППР на II пол test.xlsx")
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "цех 47"

            for column in range(7, 13):
                sheet.cell(10, column).value = "План"

            sheet.cell(11, 2).value = "Позиция 1"
            sheet.cell(11, 3).value = "Потенциометр"
            sheet.cell(11, 4).value = "КСП-4"
            sheet.cell(11, 5).value = "COLOR-001"
            sheet.cell(11, 8).value = 7
            sheet.cell(11, 8).fill = PatternFill("solid", fgColor="FFF2CC")

            sheet.cell(12, 2).value = "Позиция 2"
            sheet.cell(12, 3).value = "Потенциометр"
            sheet.cell(12, 4).value = "КСП-4"
            sheet.cell(12, 5).value = "WHITE-002"
            sheet.cell(12, 8).value = 8
            workbook.save(path)

            parsed = ssz_schedule._worksheet_to_dataframe(sheet)
            plan_row, plan_columns = ssz_schedule._find_plan_layout(parsed)
            self.assertEqual(plan_row, 9)
            self.assertEqual(plan_columns, [6, 7, 8, 9, 10, 11])
            self.assertEqual(
                ssz_schedule._collect_plan_cell_coords(
                    parsed, sheet.title, plan_row, plan_columns
                ),
                {(sheet.title, 10, 7), (sheet.title, 11, 7)},
            )

            config_override = {
                "schedules_dir": temp_dir,
                "prefer_xlsx": True,
                "redistribute_enabled": False,
            }
            with patch.dict(ssz_schedule.CONFIG, config_override), patch.object(
                ssz_schedule, "log_operation"
            ):
                color_session = FakeColorSession()
                schedule, colored, moved = ssz_schedule.fetch_month_schedules(
                    8,
                    set(),
                    report=ssz_schedule.AnalysisReport(),
                    color_session=color_session,
                    target_day=8,
                    t_year=2026,
                )

            all_assigned = [task for tasks in schedule.values() for task in tasks]
            self.assertEqual(len(colored), 1)
            self.assertIn("COLOR-001", colored[0]["work"])
            self.assertEqual(colored[0]["color_state"], "colored")
            self.assertEqual(colored[0]["source_cell"], "H11")
            self.assertEqual(colored[0]["plan_date"], "2026-08-07")
            self.assertIsNone(colored[0]["assigned_date"])

            self.assertFalse(any("COLOR-001" in task["work"] for task in all_assigned))
            white = next(task for task in all_assigned if "WHITE-002" in task["work"])
            self.assertEqual(white["color_state"], "uncolored")
            self.assertEqual(white["color_source"], "excel_display_format")
            self.assertTrue(white["analysis_id"])
            self.assertTrue(white["source_fingerprint"]["sha256"])
            self.assertEqual(white["source_cell"], "H12")
            self.assertEqual(white["assigned_date"], "2026-08-08")
            self.assertEqual(moved, [])

            with patch.dict(ssz_schedule.CONFIG, config_override):
                with self.assertRaises(PprSafetyError):
                    ssz_schedule.fetch_month_schedules(
                        8, set(), color_session=None, target_day=8, t_year=2026
                    )


if __name__ == "__main__":
    unittest.main()
