"""Non-printing regression checks for the SSZ print confirmation logic."""

import unittest
from unittest.mock import patch

import printer_utils


class PrintConfirmationTests(unittest.TestCase):
    def test_empty_queue_is_not_reported_as_success(self):
        """Excel can return without Windows accepting the job."""
        with patch.object(printer_utils.time, "time", side_effect=[0, 21]), patch.object(
            printer_utils.time, "sleep"
        ), patch.object(printer_utils, "_job_has_document_hint", return_value=False), patch.object(
            printer_utils, "count_print_jobs", return_value=0
        ):
            self.assertFalse(printer_utils._wait_print_job_finished("printer", "ССЗ.xlsx", 0))

    def test_observed_job_is_confirmed_after_leaving_queue(self):
        with patch.object(printer_utils.time, "time", side_effect=[0, 1, 2, 1.5]), patch.object(
            printer_utils.time, "sleep"
        ), patch.object(printer_utils, "_job_has_document_hint", side_effect=[False, False]), patch.object(
            printer_utils, "count_print_jobs", side_effect=[1, 0]
        ):
            self.assertTrue(printer_utils._wait_print_job_finished("printer", "ССЗ.xlsx", 0))


if __name__ == "__main__":
    unittest.main()
