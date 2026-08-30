from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from services.api.app import message_dispatch
from services.api.app.calendar_service import CalendarParseError, parse_calendar_request


ZONE = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 8, 31, 10, 0, tzinfo=ZONE)


class CalendarTimeNormalizationTests(unittest.TestCase):
    def test_this_afternoon_becomes_today_and_preserves_daypart(self) -> None:
        normalized = message_dispatch._normalize_calendar_time_language(
            "What does my calendar look like this afternoon?"
        )
        self.assertIn("today", normalized.casefold())
        self.assertIn("this afternoon", normalized.casefold())
        parsed = parse_calendar_request(normalized, now=NOW, timezone=ZONE)
        self.assertEqual(parsed.start.date(), NOW.date())
        self.assertEqual(parsed.start.hour, 12)
        self.assertEqual(parsed.end.hour, 17)

    def test_this_evening_becomes_today(self) -> None:
        normalized = message_dispatch._normalize_calendar_time_language(
            "Am I free this evening?"
        )
        parsed = parse_calendar_request(normalized, now=NOW, timezone=ZONE)
        self.assertEqual(parsed.start.date(), NOW.date())
        self.assertEqual(parsed.start.hour, 17)
        self.assertEqual(parsed.end.hour, 20)

    def test_tonight_becomes_today(self) -> None:
        normalized = message_dispatch._normalize_calendar_time_language(
            "Check my calendar tonight"
        )
        parsed = parse_calendar_request(normalized, now=NOW, timezone=ZONE)
        self.assertEqual(parsed.start.date(), NOW.date())
        self.assertEqual(parsed.start.hour, 18)
        self.assertEqual(parsed.end.hour, 22)

    def test_aaj_alias_becomes_today(self) -> None:
        normalized = message_dispatch._normalize_calendar_time_language(
            "aaj afternoon me free hu?"
        )
        parsed = parse_calendar_request(normalized, now=NOW, timezone=ZONE)
        self.assertEqual(parsed.start.date(), NOW.date())
        self.assertEqual(parsed.start.hour, 12)

    def test_explicit_tomorrow_is_not_overridden(self) -> None:
        normalized = message_dispatch._normalize_calendar_time_language(
            "Am I free tomorrow afternoon?"
        )
        self.assertNotIn("today", normalized.casefold())
        parsed = parse_calendar_request(normalized, now=NOW, timezone=ZONE)
        self.assertEqual(parsed.start.date().isoformat(), "2026-09-01")

    def test_genuinely_ambiguous_read_still_fails_closed(self) -> None:
        normalized = message_dispatch._normalize_calendar_time_language(
            "Check my calendar later"
        )
        with self.assertRaises(CalendarParseError):
            parse_calendar_request(normalized, now=NOW, timezone=ZONE)

    def test_calendar_write_with_broad_daypart_still_requires_exact_clock(self) -> None:
        normalized = message_dispatch._normalize_calendar_time_language(
            "Schedule project review this afternoon"
        )
        with self.assertRaises(CalendarParseError) as raised:
            parse_calendar_request(normalized, now=NOW, timezone=ZONE)
        self.assertIn("exact event start time", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
