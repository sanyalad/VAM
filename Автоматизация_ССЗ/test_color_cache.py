import os
import tempfile
import unittest

import xls_color_cache as color_cache
from ppr_color_service import ColorBatchResult, ColorState, decide_excel_color


class FakeColorSession(color_cache.ExcelColorSession):
    def __init__(self, colored, force_refresh=False):
        super().__init__(force_refresh=force_refresh)
        self.colored = set(colored)
        self.calls = []

    def _run_excel_worker(
        self, fpath, cells_list, cancel_check=None, progress_cb=None
    ):
        checked = set(cells_list)
        self.calls.append(checked)
        return checked, checked & self.colored


class FailingColorSession(color_cache.ExcelColorSession):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def _run_excel_worker(
        self, fpath, cells_list, cancel_check=None, progress_cb=None
    ):
        self.calls += 1
        raise color_cache.ColorCheckError("COM unavailable")


class ExcelColorCacheTests(unittest.TestCase):
    def setUp(self):
        color_cache._file_color_cache.clear()
        color_cache._disk_cache = {}
        color_cache._disk_cache_dirty = False
        fd, self.path = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
        with open(self.path, "wb") as stream:
            stream.write(b"fixture-v1")

    def tearDown(self):
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass
        color_cache._file_color_cache.clear()
        color_cache._disk_cache = None
        color_cache._disk_cache_dirty = False

    def test_new_month_checks_coordinates_missing_from_existing_cache(self):
        july = {("shop", 10, 7), ("shop", 11, 7)}
        august = {("shop", 10, 8), ("shop", 11, 8)}
        july_colored = ("shop", 10, 7)
        august_colored = ("shop", 11, 8)
        session = FakeColorSession({july_colored, august_colored})

        self.assertEqual(session.check_cells(self.path, july), {july_colored})
        self.assertEqual(session.check_cells(self.path, august), {august_colored})
        self.assertEqual(session.calls, [july, august])

        # Repeating August is served from cache without another Excel launch.
        self.assertEqual(session.check_cells(self.path, august), {august_colored})
        self.assertEqual(session.calls, [july, august])

    def test_overlapping_request_checks_only_unknown_coordinates(self):
        first = {("shop", 10, 8), ("shop", 11, 8)}
        second = {("shop", 11, 8), ("shop", 12, 8)}
        colored = ("shop", 12, 8)
        session = FakeColorSession({colored})

        self.assertEqual(session.check_cells(self.path, first), set())
        self.assertEqual(session.check_cells(self.path, second), {colored})
        self.assertEqual(session.calls[1], {("shop", 12, 8)})

    def test_failed_check_is_not_cached_as_uncolored(self):
        requested = {("shop", 10, 8)}
        session = FailingColorSession()

        with self.assertRaises(color_cache.ColorCheckError):
            session.check_cells(self.path, requested)
        with self.assertRaises(color_cache.ColorCheckError):
            session.check_cells(self.path, requested)

        self.assertEqual(session.calls, 2)
        entry = color_cache._file_color_cache[color_cache._cache_key(self.path)]
        self.assertNotIn(("shop", 10, 8), entry["checked"])

    def test_file_change_invalidates_cached_coordinates(self):
        requested = {("shop", 10, 8)}
        session = FakeColorSession(set())
        session.check_cells(self.path, requested)

        with open(self.path, "ab") as stream:
            stream.write(b"-changed")

        session.check_cells(self.path, requested)
        self.assertEqual(len(session.calls), 2)

    def test_force_refresh_rechecks_and_replaces_previous_decision(self):
        requested = {("shop", 10, 8)}
        first = FakeColorSession(set())
        self.assertEqual(first.check_cells(self.path, requested), set())

        refreshed = FakeColorSession(requested, force_refresh=True)
        self.assertEqual(refreshed.check_cells(self.path, requested), requested)
        self.assertEqual(refreshed.calls, [requested])

        cached = FakeColorSession(set())
        self.assertEqual(cached.check_cells(self.path, requested), requested)
        self.assertEqual(cached.calls, [])


class ColorDecisionTests(unittest.TestCase):
    def test_display_format_has_priority_for_conditional_fill(self):
        decision = decide_excel_color(16777215, 13408767, True)
        self.assertEqual(decision.state, ColorState.COLORED)
        self.assertEqual(decision.source, "excel_display_format")

    def test_missing_display_color_is_unknown_not_white(self):
        decision = decide_excel_color(16777215, None, True)
        self.assertEqual(decision.state, ColorState.UNKNOWN)

    def test_batch_with_unknown_coordinate_is_not_ok(self):
        coord = ("shop", 1, 2)
        batch = ColorBatchResult(unknown={coord}, errors=["read failed"])
        self.assertFalse(batch.ok)

    def test_parent_rejects_unknown_worker_result(self):
        coord = ("shop", 1, 2)
        payload = ColorBatchResult(
            unknown={coord}, errors=["DisplayFormat failed"]
        ).to_payload()
        with self.assertRaises(color_cache.ColorCheckError):
            color_cache._validate_worker_payload(payload, {coord}, "fixture.xlsx")


if __name__ == "__main__":
    unittest.main()
