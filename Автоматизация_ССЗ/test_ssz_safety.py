import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from openpyxl import Workbook

import ssz_window
from ssz_safety import (
    PprSafetyError,
    build_audit_payload,
    source_fingerprint,
    utc_now_iso,
    validate_ppr_tasks_for_generation,
    write_audit_sheet,
    read_audit_sheet,
)


class FakeExcelColorSession:
    colored = set()

    def __init__(self, force_refresh=False):
        self.force_refresh = force_refresh

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def check_cells(self, _path, coords, **_kwargs):
        return set(coords) & set(self.colored)


def make_task(source_path):
    return {
        "task_kind": "ppr",
        "plan_day": 27,
        "plan_date": "2026-08-27",
        "assigned_date": "2026-08-27",
        "work": "Выполнить ППР прибору TEST-001.",
        "place": "Цех № 47",
        "color_state": "uncolored",
        "color_source": "excel_display_format",
        "color_checked_at": utc_now_iso(),
        "analysis_id": "analysis-test",
        "source_file": source_path,
        "source_sheet": "цех 47",
        "source_cell": "I99",
        "source_fingerprint": source_fingerprint(source_path),
    }


class PprSafetyTests(unittest.TestCase):
    def test_generation_rejects_unproven_ppr(self):
        with self.assertRaises(PprSafetyError):
            validate_ppr_tasks_for_generation(
                [{"task_kind": "ppr", "plan_day": 27, "work": "ППР TEST"}]
            )

    def test_print_rechecks_exact_source_cell_and_blocks_colored_ppr(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "schedule.xlsx")
            source_wb = Workbook()
            source_wb.save(source)
            task = make_task(source)

            output = os.path.join(temp_dir, "ssz.xlsx")
            wb = Workbook()
            ws = wb.active
            ws.cell(3, 1, "27.08.2026")
            ws.cell(3, 3, task["work"])
            ws.cell(3, 4, task["place"])
            ws.cell(3, 8, "Исполнитель")
            write_audit_sheet(wb, build_audit_payload(datetime(2026, 8, 27), [task]))
            wb.save(output)

            FakeExcelColorSession.colored = {("цех 47", 98, 8)}
            with patch.object(ssz_window, "ExcelColorSession", FakeExcelColorSession):
                with self.assertRaisesRegex(PprSafetyError, "закрашенные ППР"):
                    ssz_window.validate_ssz_files_for_print([output])

            FakeExcelColorSession.colored = set()
            with patch.object(ssz_window, "ExcelColorSession", FakeExcelColorSession):
                self.assertTrue(ssz_window.validate_ssz_files_for_print([output]))

    def test_writer_embeds_hidden_manifest_and_print_accepts_fresh_uncolored_ppr(self):
        project_dir = os.getcwd()
        with open(os.path.join(project_dir, "Шаблон_ССЗ.xlsx"), "rb") as stream:
            template_bytes = stream.read()
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "schedule.xlsx")
            source_wb = Workbook()
            source_wb.save(source)
            task = make_task(source)
            try:
                os.chdir(temp_dir)
                output = ssz_window.write_excel_document(
                    datetime(2026, 8, 27),
                    [task],
                    "Исполнитель",
                    template_bytes=template_bytes,
                )
                wb = ssz_window.load_workbook(output, read_only=True, data_only=True)
                try:
                    audit = read_audit_sheet(wb)
                    self.assertEqual(len(audit["ppr_tasks"]), 1)
                    self.assertEqual(wb["_SSZ_AUDIT"].sheet_state, "veryHidden")
                finally:
                    wb.close()
                FakeExcelColorSession.colored = set()
                with patch.object(ssz_window, "ExcelColorSession", FakeExcelColorSession):
                    self.assertTrue(ssz_window.validate_ssz_files_for_print([output]))
            finally:
                os.chdir(project_dir)

    def test_generation_blocks_when_source_changed_after_analysis(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "schedule.xlsx")
            wb = Workbook()
            wb.save(source)
            task = make_task(source)
            with open(source, "ab") as stream:
                stream.write(b"changed")
            with self.assertRaisesRegex(PprSafetyError, "изменился после анализа"):
                validate_ppr_tasks_for_generation([task])

    def test_print_blocks_legacy_file_with_ppr_and_no_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = os.path.join(temp_dir, "legacy.xlsx")
            wb = Workbook()
            ws = wb.active
            ws.cell(3, 1, "27.08.2026")
            ws.cell(3, 3, "Выполнить ППР прибору OLD.")
            ws.cell(3, 4, "Цех № 47")
            ws.cell(3, 8, "Исполнитель")
            wb.save(output)
            with self.assertRaisesRegex(PprSafetyError, "нет паспорта"):
                ssz_window.validate_ssz_files_for_print([output])


if __name__ == "__main__":
    unittest.main()
