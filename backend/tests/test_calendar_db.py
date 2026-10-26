import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone

import calendar_db


class TestCalendarDB(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_calendar.db")
        calendar_db.init_calendar_db(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_init_and_default_calendars(self):
        cals = calendar_db.list_calendars(self.db_path)
        self.assertGreaterEqual(len(cals), 2)
        names = [c["name"] for c in cals]
        self.assertIn("Personale", names)
        self.assertIn("Homelab", names)

    def test_calendar_crud(self):
        new_cal = calendar_db.save_calendar({
            "name": "Lavoro",
            "color": "#10b981",
            "source": "local",
        }, db_path=self.db_path)
        self.assertIsNotNone(new_cal)
        self.assertEqual(new_cal["name"], "Lavoro")
        self.assertEqual(new_cal["color"], "#10b981")

        # Modifica
        updated = calendar_db.save_calendar({
            "id": new_cal["id"],
            "name": "Lavoro & Progetti",
        }, db_path=self.db_path)
        self.assertEqual(updated["name"], "Lavoro & Progetti")

        # Elimina
        deleted = calendar_db.delete_calendar(new_cal["id"], db_path=self.db_path)
        self.assertTrue(deleted)
        self.assertIsNone(calendar_db.get_calendar(new_cal["id"], db_path=self.db_path))

    def test_event_crud_and_deduplication(self):
        cals = calendar_db.list_calendars(self.db_path)
        cal_id = cals[0]["id"]

        ev = calendar_db.save_event({
            "calendar_id": cal_id,
            "summary": "Meeting con Mario",
            "description": "Discussione architettura",
            "location": "https://meet.google.com/xyz-abc",
            "dtstart": "2026-09-24T10:00:00",
            "dtend": "2026-09-24T11:00:00",
            "category": "meeting",
            "importance": "high",
        }, db_path=self.db_path)

        self.assertIsNotNone(ev)
        self.assertEqual(ev["summary"], "Meeting con Mario")
        self.assertEqual(ev["category"], "meeting")

        # Verifica deduplicazione
        existing = calendar_db.find_existing_event(
            summary="  meeting con mario  ",
            dtstart="2026-09-24T10:00:00",
            db_path=self.db_path,
        )
        self.assertIsNotNone(existing)
        self.assertEqual(existing["uid"], ev["uid"])

        # Update
        updated = calendar_db.save_event({
            "uid": ev["uid"],
            "summary": "Meeting con Mario (Confermato)",
            "dtstart": "2026-09-24T10:00:00",
            "dtend": "2026-09-24T11:30:00",
        }, db_path=self.db_path)
        self.assertEqual(updated["summary"], "Meeting con Mario (Confermato)")

        # List
        events = calendar_db.list_events(
            start_dt="2026-09-24T00:00:00",
            end_dt="2026-09-24T23:59:59",
            db_path=self.db_path,
        )
        self.assertEqual(len(events), 1)

        # Delete
        del_res = calendar_db.delete_event(ev["uid"], db_path=self.db_path)
        self.assertTrue(del_res)
        self.assertIsNone(calendar_db.get_event(ev["uid"], db_path=self.db_path))

    def test_find_free_slots(self):
        cals = calendar_db.list_calendars(self.db_path)
        cal_id = cals[0]["id"]

        # Evento dalle 10:00 alle 11:30
        calendar_db.save_event({
            "calendar_id": cal_id,
            "summary": "Occupato 1",
            "dtstart": "2026-09-25T10:00:00",
            "dtend": "2026-09-25T11:30:00",
        }, db_path=self.db_path)

        # Evento dalle 14:00 alle 15:00
        calendar_db.save_event({
            "calendar_id": cal_id,
            "summary": "Occupato 2",
            "dtstart": "2026-09-25T14:00:00",
            "dtend": "2026-09-25T15:00:00",
        }, db_path=self.db_path)

        slots = calendar_db.find_free_slots(
            target_date="2026-09-25",
            duration_minutes=30,
            start_hour=9,
            end_hour=18,
            db_path=self.db_path,
        )

        # Ci aspettiamo slot: 09:00-10:00 (60m), 11:30-14:00 (150m), 15:00-18:00 (180m)
        self.assertEqual(len(slots), 3)
        self.assertEqual(slots[0]["start"], "09:00")
        self.assertEqual(slots[0]["end"], "10:00")
        self.assertEqual(slots[1]["start"], "11:30")
        self.assertEqual(slots[1]["end"], "14:00")
        self.assertEqual(slots[2]["start"], "15:00")
        self.assertEqual(slots[2]["end"], "18:00")


if __name__ == "__main__":
    unittest.main()
