import os
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

import inventory_db
from ssz_config import CONFIG


class InventoryDailyPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(
            inventory_db, "DB_PATH", os.path.join(self.temp_dir.name, "inventory.db")
        )
        self.db_patch.start()
        self.config_patch = patch.dict(
            CONFIG,
            {
                "inventory_daily_plan_enabled": True,
                "inventory_daily_plan_size": 2,
                "inventory_daily_plan_cooldown_days": 14,
            },
        )
        self.config_patch.start()
        inventory_db.init_db()
        conn = inventory_db._get_conn()
        ws_id = conn.execute("SELECT id FROM workshops ORDER BY id LIMIT 1").fetchone()[0]
        cursor = conn.execute(
            "INSERT INTO locations(workshop_id,name,type) VALUES (?,?,?)",
            (ws_id, "Тестовое место", "general"),
        )
        loc_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO devices(name,serial_number,location_id,lifecycle_status) VALUES (?,?,?,'active')",
            ("КСД-3", "TEST-001", loc_id),
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        self.config_patch.stop()
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_plan_is_created_for_separate_printing(self):
        plan = inventory_db.ensure_daily_inventory_plan(date(2026, 8, 27))
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["status"], "open")
        self.assertTrue(plan[0]["include_in_print"])
        from inventory_plan_printer import build_daily_plan_html
        html = build_daily_plan_html(date(2026, 8, 27), plan)
        self.assertIn("ПЛАН УТОЧНЕНИЯ БАЗЫ ПРИБОРОВ", html)
        self.assertIn("TEST-001", html)
        from ssz_utils import get_default_tasks
        self.assertEqual(len(get_default_tasks(date(2026, 8, 27))), 2)
        inventory_db.update_daily_inventory_task(plan[0]["id"], status="completed")
        self.assertEqual(inventory_db.get_daily_inventory_plan(date(2026, 8, 27))[0]["status"], "completed")

    def test_each_day_contains_only_one_workshop(self):
        conn = inventory_db._get_conn()
        workshops = conn.execute("SELECT id,name FROM workshops ORDER BY id LIMIT 2").fetchall()
        for ws_id, ws_name in workshops:
            loc = conn.execute(
                "INSERT INTO locations(workshop_id,name,type) VALUES (?,?,?)",
                (ws_id, f"Печь для {ws_name}", "furnace"),
            ).lastrowid
            for number in range(3):
                conn.execute(
                    "INSERT INTO devices(name,serial_number,location_id,lifecycle_status) VALUES (?,?,?,'active')",
                    (f"Прибор {ws_id}-{number}", f"WS-{ws_id}-{number}", loc),
                )
        conn.commit()
        conn.close()
        plan = inventory_db.ensure_daily_inventory_plan(date(2026, 8, 28), limit=3)
        self.assertGreater(len(plan), 0)
        self.assertEqual(len({task["workshop_name"] for task in plan}), 1)

    def test_interactive_answer_updates_device(self):
        plan = inventory_db.ensure_daily_inventory_plan(date(2026, 8, 29))
        device_id = plan[0]["device_id"]
        self.assertTrue(
            inventory_db.update_device_details(
                device_id,
                serial_number="NEW-001",
                calibration_date="2027-10-15",
                position="Позиция 7",
            )
        )
        conn = inventory_db._get_conn()
        row = conn.execute(
            "SELECT serial_number,calibration_date,position FROM devices WHERE id=?",
            (device_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(row, ("NEW-001", "2027-10-15", "Позиция 7"))


if __name__ == "__main__":
    unittest.main()
