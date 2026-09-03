import pathlib
import unittest


class WorkerSourceSafetyTests(unittest.TestCase):
    def test_debug_instrumentation_is_not_present(self):
        source = pathlib.Path(__file__).with_name("ssz_worker.py").read_text(encoding="utf-8")
        self.assertNotIn("test_gui_crash.log", source)


if __name__ == "__main__":
    unittest.main()
