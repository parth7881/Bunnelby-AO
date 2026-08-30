from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from .calendar_service import (
    CalendarParseError,
    CalendarServiceError,
    DEFAULT_CALENDAR_ID,
    WEEKDAYS,
    _calendar_service,
    _coerce_datetime,
    _execute_read,
    local_timezone,
)

_SCHEDULE_QUERY_RE = re.compile(
    r"\b(?:my\s+(?:schedule|agenda|timetable|time\s+table)|"
    r"(?:mera|meri|mere)\s+(?:aaj\s+ka\s+)?schedule|"
    r"aaj\s+ka\s+schedule|aaj\s+ki\s+meetings?|"
    r"today\s+my\s+(?:schedule|agenda|timetable|time\s+table)|"
    r"(?:schedule|agenda|timetable|time\s+table)\s+(?:for\s+)?today|"
    r"what(?:'s|\s+is)\s+(?:on\s+)?my\s+(?:schedule|agenda|calendar)|"
    r"what\s+am\s+i\s+doing\s+today|"
    r"what(?:'s|\s+is)\s+scheduled\s+(?:for\s+)?today|"
    r"show\s+(?:me\s+)?(?:my\s+)?(?:schedule|agenda|timetable|time\s+table|calendar\s+events?)|"
    r"check\s+(?:my\s+)?(?:schedule|agenda|timetable|time\s+table|calendar\s+events?)|"
    r"list\s+(?:my\s+)?(?:calendar\s+)?events?|"
    r"calendar\s+events?|events?\s+today|meetings?\s+today)\b",
    re.IGNORECASE,
)

_CREATE_PREFIX_RE = re.compile(
    r"^\s*(?:schedule|book|create|add|set\s+up)\b",
    re.IGNORECASE,
)

_TODAY_RE = re.compile(r"\b(?:today|aaj)\b|आज", re.IGNORECASE)
_TOMORROW_RE = re.compile(r"\btomorrow\b", re.IGNORECASE)


def is_agenda_request(user_message: str) -> bool:
    """Recognize Calendar agenda reads without stealing event-creation commands."""
    text = user_message.strip()
    if not text:
        return False
    # "Schedule Project Review tomorrow..." is a write request, not a request to read
    # the user's schedule. Creation routing must retain the approval gate.
    if _CREATE_PREFIX_RE.search(text):
        return False
    return bool(_SCHEDULE_QUERY_RE.search(text))


def _resolve_agenda_date(
    user_message: str,
    *,
    now: datetime | None = None,
    timezone: ZoneInfo | None = None,
) -> tuple[date, ZoneInfo]:
    zone = timezone or local_timezone()
    current = now.astimezone(zone) if now and now.tzinfo else (now.replace(tzinfo=zone) if now else datetime.now(zone))
    text = user_message.strip()

    if _TODAY_RE.search(text):
        return current.date(), zone
    if _TOMORROW_RE.search(text):
        return current.date() + timedelta(days=1), zone

    weekday_match = re.search(
        r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        text,
        re.IGNORECASE,
    )
    if weekday_match:
        target = WEEKDAYS[weekday_match.group(1).casefold()]
        days_ahead = (target - current.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return current.date() + timedelta(days=days_ahead), zone

    raise CalendarParseError(
        "I couldn't determine the schedule date. Say 'today', 'aaj', 'tomorrow', or a weekday."
    )


def agenda_range(
    user_message: str,
    *,
    now: datetime | None = None,
    timezone: ZoneInfo | None = None,
) -> tuple[datetime, datetime, ZoneInfo]:
    day, zone = _resolve_agenda_date(user_message, now=now, timezone=timezone)
    start = datetime.combine(day, time.min, tzinfo=zone)
    end = start + timedelta(days=1)
    return start, end, zone


def list_events(date_range: Sequence[datetime] | Mapping[str, datetime]) -> list[dict[str, Any]]:
    """List real Google Calendar events in chronological order for the primary calendar."""
    zone = local_timezone()
    if isinstance(date_range, Mapping):
        raw_start = date_range.get("start")
        raw_end = date_range.get("end")
    elif isinstance(date_range, Sequence) and len(date_range) == 2:
        raw_start, raw_end = date_range[0], date_range[1]
    else:
        raise CalendarServiceError("date_range must contain start and end datetimes.")

    if not isinstance(raw_start, datetime) or not isinstance(raw_end, datetime):
        raise CalendarServiceError("Calendar agenda range must use datetimes.")
    start = raw_start.astimezone(zone) if raw_start.tzinfo else raw_start.replace(tzinfo=zone)
    end = raw_end.astimezone(zone) if raw_end.tzinfo else raw_end.replace(tzinfo=zone)
    if end <= start:
        raise CalendarServiceError("Calendar agenda range end must be after start.")

    service = _calendar_service()
    result = _execute_read(
        service.events().list(
            calendarId=DEFAULT_CALENDAR_ID,
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=100,
        )
    )

    events: list[dict[str, Any]] = []
    for item in result.get("items", []) or []:
        if str(item.get("status", "")).casefold() == "cancelled":
            continue

        start_obj = item.get("start") or {}
        end_obj = item.get("end") or {}
        all_day = bool(start_obj.get("date"))
        title = str(item.get("summary") or "(untitled event)").strip()

        if all_day:
            start_value = str(start_obj.get("date") or "")
            end_value = str(end_obj.get("date") or "")
            if not start_value:
                continue
            events.append(
                {
                    "id": str(item.get("id") or ""),
                    "title": title,
                    "all_day": True,
                    "start": start_value,
                    "end": end_value or start_value,
                    "location": str(item.get("location") or "").strip(),
                }
            )
            continue

        start_value = str(start_obj.get("dateTime") or "")
        end_value = str(end_obj.get("dateTime") or "")
        if not start_value or not end_value:
            continue
        event_start = _coerce_datetime(start_value, zone)
        event_end = _coerce_datetime(end_value, zone)
        events.append(
            {
                "id": str(item.get("id") or ""),
                "title": title,
                "all_day": False,
                "start": event_start.isoformat(),
                "end": event_end.isoformat(),
                "location": str(item.get("location") or "").strip(),
            }
        )

    return events


def _clock(value: datetime) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def format_agenda_response(
    start: datetime,
    events: list[dict[str, Any]],
) -> str:
    """Format only verified Google Calendar events; never fill gaps from email or memory."""
    zone = start.tzinfo if isinstance(start.tzinfo, ZoneInfo) else local_timezone()
    date_label = start.strftime("%A, %B %d, %Y").replace(" 0", " ")

    if not events:
        return f"You don't have any Google Calendar events scheduled for {date_label}."

    lines = [f"Your Google Calendar schedule for {date_label}:"]
    for event in events:
        title = str(event.get("title") or "(untitled event)")
        if event.get("all_day"):
            line = f"- All day — {title}"
        else:
            event_start = _coerce_datetime(str(event["start"]), zone)
            event_end = _coerce_datetime(str(event["end"]), zone)
            line = f"- {_clock(event_start)}–{_clock(event_end)} — {title}"
        location = str(event.get("location") or "").strip()
        if location:
            line += f" ({location})"
        lines.append(line)
    return "\n".join(lines)
