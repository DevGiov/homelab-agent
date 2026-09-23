import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta

import calendar_db
from registry.calendar_tool import CalendarRegistry
from registry.manager import ToolRegistryManager


class TestCalendarTool(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_calendar.db")
        calendar_db.init_calendar_db(self.db_path)
        self.orig_db_path = calendar_db.get_db_path
        calendar_db.get_db_path = lambda: self.db_path
        self.registry = CalendarRegistry()

    def tearDown(self):
        calendar_db.get_db_path = self.orig_db_path
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_get_tools_definition(self):
        tools = self.registry.get_tools()
        names = [t["name"] for t in tools]
        self.assertIn("calendar_list_calendars", names)
        self.assertIn("calendar_list_events", names)
        self.assertIn("calendar_get_event", names)
        self.assertIn("calendar_create_event", names)
        self.assertIn("calendar_update_event", names)
        self.assertIn("calendar_delete_event", names)
        self.assertIn("calendar_check_availability", names)

    def test_create_and_deduplicate_event(self):
        # 1. Creazione con durata naturale '45m'
        res = self.registry.execute_tool("calendar_create_event", {
            "summary": "Sync Team",
            "start_time": "2026-09-25T11:00:00",
            "duration": "45m",
            "location": "Google Meet",
            "description": "Allineamento settimanale",
        })
        self.assertEqual(res["status"], "created")
        self.assertFalse(res["duplicate"])
        self.assertIn("#event-", res["markdown_link"])
        self.assertEqual(res["dtend"], "2026-09-25T11:45:00")

        # 2. Creazione duplicata -> deduplicazione
        dup_res = self.registry.execute_tool("calendar_create_event", {
            "summary": "  sync team  ",
            "start_time": "2026-09-25T11:00:00",
        })
        self.assertEqual(dup_res["status"], "already_exists")
        self.assertTrue(dup_res["duplicate"])
        self.assertEqual(dup_res["uid"], res["uid"])

    def test_batch_create(self):
        batch = [
            {"summary": "Attività 1", "start_time": "2026-09-26T09:00:00", "duration": "30m"},
            {"summary": "Attività 2", "start_time": "2026-09-26T10:00:00", "duration": "1h"},
        ]
        res = self.registry.execute_tool("calendar_create_event", {"events": batch})
        self.assertEqual(res["status"], "batch_completed")
        self.assertEqual(res["total"], 2)
        self.assertEqual(res["created_count"], 2)

    def test_list_and_get_events(self):
        self.registry.execute_tool("calendar_create_event", {
            "summary": "Call di Progetto",
            "start_time": "2026-09-27T15:00:00",
            "duration": "1h",
            "category": "meeting",
        })

        list_res = self.registry.execute_tool("calendar_list_events", {
            "start_date": "2026-09-27",
            "end_date": "2026-09-27",
        })
        self.assertEqual(list_res["status"], "success")
        self.assertEqual(list_res["count"], 1)
        uid = list_res["events"][0]["uid"]

        get_res = self.registry.execute_tool("calendar_get_event", {"event_id": uid})
        self.assertEqual(get_res["status"], "success")
        self.assertEqual(get_res["event"]["summary"], "Call di Progetto")

    def test_update_and_delete_event(self):
        create_res = self.registry.execute_tool("calendar_create_event", {
            "summary": "Evento Da Modificare",
            "start_time": "2026-09-28T14:00:00",
        })
        uid = create_res["uid"]

        # Update
        update_res = self.registry.execute_tool("calendar_update_event", {
            "event_id": uid,
            "summary": "Evento Modificato",
        })
        self.assertEqual(update_res["status"], "updated")
        self.assertEqual(update_res["summary"], "Evento Modificato")

        # Delete
        del_res = self.registry.execute_tool("calendar_delete_event", {"event_id": uid})
        self.assertEqual(del_res["status"], "deleted")

        get_res = self.registry.execute_tool("calendar_get_event", {"event_id": uid})
        self.assertEqual(get_res["status"], "not_found")

    def test_tool_registry_manager_integration(self):
        manager = ToolRegistryManager()
        tools = manager.get_tools_for_mode(["calendar"])
        tool_names = [t["name"] for t in tools]
        self.assertIn("calendar_create_event", tool_names)
        self.assertIn("calendar_check_availability", tool_names)


if __name__ == "__main__":
    unittest.main()
