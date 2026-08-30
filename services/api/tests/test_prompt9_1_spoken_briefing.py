from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from services.api.app.calendar_service import ParsedCalendarRequest
from services.api.app.spoken_briefing import (
    calendar_agenda_briefing,
    calendar_free_busy_briefing,
    calendar_open_slots_briefing,
)


ZONE = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 8, 31, 8, 0, tzinfo=ZONE)


class SpokenBriefingTests(unittest.TestCase):
    def test_agenda_speaks_titles_and_times_instead_of_screen_ack(self):
        start = datetime(2026, 8, 31, 0, 0, tzinfo=ZONE)
        events = [
            {
                "title": "Project Review",
                "all_day": False,
                "start": "2026-08-31T10:00:00+05:30",
                "end": "2026-08-31T11:00:00+05:30",
            },
            {
                "title": "Rahul Meeting",
                "all_day": False,
                "start": "2026-08-31T12:30:00+05:30",
                "end": "2026-08-31T13:00:00+05:30",
            },
        ]

        spoken = calendar_agenda_briefing(start, events, "en", now=NOW)

        self.assertIn("Project Review", spoken)
        self.assertIn("10 AM", spoken)
        self.assertIn("Rahul Meeting", spoken)
        self.assertIn("12:30 PM", spoken)
        self.assertNotIn("on screen", spoken.casefold())
        self.assertNotIn("full agenda", spoken.casefold())

    def test_hinglish_agenda_generates_devanagari_useful_briefing(self):
        start = datetime(2026, 8, 31, 0, 0, tzinfo=ZONE)
        events = [
            {
                "title": "Project Review",
                "all_day": False,
                "start": "2026-08-31T10:00:00+05:30",
                "end": "2026-08-31T11:00:00+05:30",
            }
        ]

        spoken = calendar_agenda_briefing(start, events, "hi", now=NOW)

        self.assertIn("सर", spoken)
        self.assertIn("10 बजे", spoken)
        self.assertIn("Project Review", spoken)
        self.assertNotIn("स्क्रीन", spoken)

    def test_free_afternoon_is_spoken_as_actual_availability(self):
        request = ParsedCalendarRequest(
            action="free_busy",
            start=datetime(2026, 9, 1, 12, 0, tzinfo=ZONE),
            end=datetime(2026, 9, 1, 17, 0, tzinfo=ZONE),
            duration_minutes=60,
            timezone="Asia/Kolkata",
            work_hours=(12, 17),
            daypart="afternoon",
        )

        spoken = calendar_free_busy_briefing(request, [], "en", now=NOW)

        self.assertIn("completely free", spoken)
        self.assertIn("12 PM", spoken)
        self.assertIn("5 PM", spoken)
        self.assertNotIn("screen", spoken.casefold())

    def test_busy_window_mentions_best_free_block(self):
        request = ParsedCalendarRequest(
            action="free_busy",
            start=datetime(2026, 9, 1, 12, 0, tzinfo=ZONE),
            end=datetime(2026, 9, 1, 17, 0, tzinfo=ZONE),
            duration_minutes=60,
            timezone="Asia/Kolkata",
            work_hours=(12, 17),
            daypart="afternoon",
        )
        busy = [
            {
                "start": "2026-09-01T13:00:00+05:30",
                "end": "2026-09-01T14:00:00+05:30",
            }
        ]

        spoken = calendar_free_busy_briefing(request, busy, "en", now=NOW)

        self.assertIn("best free block", spoken)
        self.assertNotIn("screen", spoken.casefold())

    def test_open_slots_speaks_first_real_options(self):
        request = ParsedCalendarRequest(
            action="open_slots",
            start=datetime(2026, 9, 1, 9, 0, tzinfo=ZONE),
            end=datetime(2026, 9, 1, 18, 0, tzinfo=ZONE),
            duration_minutes=30,
            timezone="Asia/Kolkata",
            work_hours=(9, 18),
        )
        slots = [
            {"start": "2026-09-01T09:00:00+05:30", "end": "2026-09-01T09:30:00+05:30"},
            {"start": "2026-09-01T10:30:00+05:30", "end": "2026-09-01T11:00:00+05:30"},
        ]

        spoken = calendar_open_slots_briefing(request, slots, "en", now=NOW)

        self.assertIn("9 AM", spoken)
        self.assertIn("10:30 AM", spoken)
        self.assertNotIn("screen", spoken.casefold())


if __name__ == "__main__":
    unittest.main()
