"""Test della risoluzione deterministica di id e alias dei template di automazione."""
import json
from unittest.mock import patch

import pytest

from app.automations.db import schema as schema_db
from app.core.config import settings
from app.registry import automations_tool
from app.registry.automations_tool import AutomationRegistry, _resolve_template


@pytest.fixture
def templates_dir(tmp_path):
    for stem, tpl_id in (
        ("daily_email_briefing", "tpl-daily-email-briefing"),
        ("email_to_calendar_sync", "tpl-email-to-calendar-sync"),
        ("github_issue_repair", "tpl-github-issue-repair"),
    ):
        (tmp_path / f"{stem}.json").write_text(json.dumps({"id": tpl_id, "name": stem}), encoding="utf-8")
    with patch.object(automations_tool, "TEMPLATES_DIR", tmp_path):
        yield tmp_path


@pytest.mark.parametrize("requested,expected", [
    ("tpl-email-to-calendar-sync", "tpl-email-to-calendar-sync"),
    ("tpl-daily-email-briefing", "tpl-daily-email-briefing"),
    ("tpl_daily_email_briefing", "tpl-daily-email-briefing"),
    ("email_to_calendar_sync", "tpl-email-to-calendar-sync"),
    ("tpl_email_briefing", "tpl-daily-email-briefing"),
    ("repair", "tpl-github-issue-repair"),
])
def test_resolve_template(templates_dir, requested, expected):
    assert _resolve_template(requested)["id"] == expected


@pytest.mark.parametrize("requested", ["email", "tpl-unknown", ""])
def test_resolve_template_rejects_ambiguous_or_unknown(templates_dir, requested):
    assert _resolve_template(requested) is None


def test_exact_id_wins_regardless_of_file_order(templates_dir):
    # Un file che ordina prima e che matcherebbe per alias non deve oscurare l'id esatto
    (templates_dir / "a_email_digest.json").write_text(
        json.dumps({"id": "tpl-email-digest", "name": "digest"}), encoding="utf-8"
    )
    assert _resolve_template("tpl-email-to-calendar-sync")["id"] == "tpl-email-to-calendar-sync"


def test_details_falls_back_to_resolved_template(templates_dir):
    schema_db.init_automations_db(settings.automations_db_path)
    details = AutomationRegistry().execute_tool("get_automation_details", {"automation_id": "tpl_email_briefing"})
    assert details["id"] == "tpl-daily-email-briefing"
    assert details["_is_template"] is True
