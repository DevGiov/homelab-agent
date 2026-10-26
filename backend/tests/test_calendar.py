"""Unit test completi per Calendar Router, Sync ed integrazione Automations."""

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import config
import calendar_db
import calendar_sync
from api import api
from automations.db import init_automations_db, save_definition
from automations.models import AutomationDefinition, ExecutionPolicy, RunStatus, StepType, WorkflowSpec, WorkflowStepDefinition
from automations.runner import AutomationRunner
from registry.calendar_tool import CalendarRegistry


class TestCalendarSync(unittest.TestCase):
    def test_parse_ical_content(self):
        sample_ics = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:test-uid-123@google.com
SUMMARY:Colloquio Tecnico
DESCRIPTION:Intervista con HR
LOCATION:Google Meet
DTSTART:20261015T090000Z
DTEND:20261015T100000Z
STATUS:CONFIRMED
END:VEVENT
END:VCALENDAR"""

        events = calendar_sync.parse_ical_text(sample_ics)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["summary"], "Colloquio Tecnico")
        self.assertEqual(ev["description"], "Intervista con HR")
        self.assertEqual(ev["location"], "Google Meet")
        self.assertEqual(ev["external_uid"], "test-uid-123@google.com")
        self.assertEqual(ev["dtstart"], "2026-10-15T09:00:00")
        self.assertEqual(ev["dtend"], "2026-10-15T10:00:00")


class TestCalendarAPI(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_api_calendar.db")
        calendar_db.init_calendar_db(self.db_path)
        self.orig_db_path = calendar_db.get_db_path
        calendar_db.get_db_path = lambda: self.db_path
        self.client = TestClient(api)
        self.headers = {"X-API-Key": config.API_SECRET_KEY} if config.API_SECRET_KEY else {}

    def tearDown(self):
        calendar_db.get_db_path = self.orig_db_path
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_api_list_calendars(self):
        res = self.client.get("/v1/calendar/calendars", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        cals = res.json()
        self.assertGreaterEqual(len(cals), 2)

    def test_api_create_and_list_event(self):
        payload = {
            "summary": "Riunione Condominio",
            "dtstart": "2026-12-01T21:00:00",
            "duration": "1h30m",
            "location": "Sala Condominiale",
        }
        res = self.client.post("/v1/calendar/events", json=payload, headers=self.headers)
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["status"], "created")
        event_id = data["event"]["id"]

        # Get by id
        get_res = self.client.get(f"/v1/calendar/events/{event_id}", headers=self.headers)
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.json()["summary"], "Riunione Condominio")

        # Check availability
        avail_res = self.client.get("/v1/calendar/availability", params={
            "start_time": "2026-12-01T21:15:00",
            "duration": "30m"
        }, headers=self.headers)
        self.assertEqual(avail_res.status_code, 200)
        self.assertFalse(avail_res.json()["available"])

    def test_import_ics_events(self):
        sample_ics = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Example Corp.//EN
BEGIN:VEVENT
UID:sample_ics_event_1
SUMMARY:Incontro Standup Importato
DTSTART:20261115T090000Z
DTEND:20261115T093000Z
DESCRIPTION:Descrizione evento da file ics
LOCATION:Sala Conferenze
END:VEVENT
END:VCALENDAR"""

        res = self.client.post("/v1/calendar/import/ics", json={
            "ics_content": sample_ics,
            "calendar_name": "Test ICS Import",
            "color": "#10b981",
        }, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["imported_count"], 1)

        # Verifica presenza evento
        events = calendar_db.list_events(query="Incontro Standup Importato")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["summary"], "Incontro Standup Importato")


class TestCalendarAutomation(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.auto_db_path = os.path.join(self.test_dir, "test_automations.db")
        self.cal_db_path = os.path.join(self.test_dir, "test_cal_auto.db")
        
        self.original_auto_db = config.AUTOMATIONS_DB_PATH
        config.AUTOMATIONS_DB_PATH = self.auto_db_path
        init_automations_db(self.auto_db_path)

        calendar_db.init_calendar_db(self.cal_db_path)
        self.orig_db_path = calendar_db.get_db_path
        calendar_db.get_db_path = lambda: self.cal_db_path

    def tearDown(self):
        calendar_db.get_db_path = self.orig_db_path
        config.AUTOMATIONS_DB_PATH = self.original_auto_db
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_automation_runner_calendar_step(self):
        definition = AutomationDefinition(
            id="auto_cal_test",
            name="Test Auto Calendar Event",
            description="Crea un evento da automazione",
            enabled=True,
            workflow=WorkflowSpec(
                initial_step_id="step_cal_1",
                steps=[
                    WorkflowStepDefinition(
                        step_id="step_cal_1",
                        name="Crea Appuntamento",
                        type=StepType.DETERMINISTIC_ACTION,
                        action_or_tool="calendar_create_event",
                        parameters={
                            "summary": "Evento da Automazione",
                            "dtstart": "2026-10-20T11:00:00",
                            "duration": "45m",
                            "location": "Remoto",
                        }
                    )
                ]
            ),
            permission_policy=ExecutionPolicy(
                allowed_registries=["calendar", "automations"]
            )
        )
        saved = save_definition(definition.model_dump(), db_path=self.auto_db_path)
        auto_id = saved["id"]
        
        runner = AutomationRunner(db_path=self.auto_db_path)
        run = runner.start_run(auto_id)
        completed_run = runner.execute_run(run.run_id)
        
        self.assertEqual(completed_run.status, RunStatus.COMPLETED)
        self.assertEqual(len(completed_run.step_runs), 1)
        step_output = completed_run.step_runs[0].output_payload
        self.assertIn(step_output["status"], ["success", "created"])
        self.assertEqual(step_output["event"]["summary"], "Evento da Automazione")

        # Verify event persisted in calendar_db
        events = calendar_db.list_events(query="Evento da Automazione")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["source_type"], "automation")


if __name__ == "__main__":
    unittest.main()
