from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable, Literal, Mapping, Sequence
from zoneinfo import ZoneInfo

from .calendar_service import ParsedCalendarRequest, free_windows, local_timezone

SpokenLanguage = Literal["en", "hi"]


def _as_datetime(value: object, zone: ZoneInfo) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(zone) if value.tzinfo else value.replace(tzinfo=zone)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(zone) if parsed.tzinfo else parsed.replace(tzinfo=zone)


def _clock_en(value: datetime) -> str:
    if value.minute == 0:
        return value.strftime("%I %p").lstrip("0")
    return value.strftime("%I:%M %p").lstrip("0")


def _clock_hi(value: datetime) -> str:
    hour = value.strftime("%I").lstrip("0")
    if value.minute == 0:
        return f"{hour} बजे"
    return f"{hour}:{value.minute:02d} बजे"


def _clock(value: datetime, language: SpokenLanguage) -> str:
    return _clock_hi(value) if language == "hi" else _clock_en(value)


def _day_label(value: datetime, language: SpokenLanguage, *, now: datetime | None = None) -> str:
    zone = value.tzinfo if isinstance(value.tzinfo, ZoneInfo) else local_timezone()
    current = now or datetime.now(zone)
    current = current.astimezone(zone) if current.tzinfo else current.replace(tzinfo=zone)
    delta = (value.date() - current.date()).days
    if language == "hi":
        if delta == 0:
            return "आज"
        if delta == 1:
            return "कल"
        return value.strftime("%A, %d %B")
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    return value.strftime("%A, %B %d").replace(" 0", " ")


def _join_natural(items: Sequence[str], language: SpokenLanguage) -> str:
    cleaned = [item.strip() for item in items if item and item.strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    conjunction = " और " if language == "hi" else " and "
    if len(cleaned) == 2:
        return conjunction.join(cleaned)
    separator = ", "
    return separator.join(cleaned[:-1]) + conjunction + cleaned[-1]


def _timed_events(
    events: Iterable[Mapping[str, Any]],
    zone: ZoneInfo,
) -> list[tuple[datetime, datetime, str]]:
    values: list[tuple[datetime, datetime, str]] = []
    for event in events:
        if event.get("all_day"):
            continue
        start = _as_datetime(event.get("start"), zone)
        end = _as_datetime(event.get("end"), zone)
        if start is None or end is None or end <= start:
            continue
        values.append((start, end, str(event.get("title") or "untitled event").strip()))
    return sorted(values, key=lambda item: item[0])


def _largest_day_gap(
    start: datetime,
    timed: Sequence[tuple[datetime, datetime, str]],
) -> tuple[datetime, datetime] | None:
    """Return the largest useful free block inside 09:00-18:00 for that day."""
    zone = start.tzinfo if isinstance(start.tzinfo, ZoneInfo) else local_timezone()
    work_start = start.replace(hour=9, minute=0, second=0, microsecond=0).astimezone(zone)
    work_end = start.replace(hour=18, minute=0, second=0, microsecond=0).astimezone(zone)
    cursor = work_start
    gaps: list[tuple[datetime, datetime]] = []

    for event_start, event_end, _title in timed:
        if event_end <= work_start or event_start >= work_end:
            continue
        clipped_start = max(event_start, work_start)
        clipped_end = min(event_end, work_end)
        if clipped_start > cursor:
            gaps.append((cursor, clipped_start))
        cursor = max(cursor, clipped_end)
    if cursor < work_end:
        gaps.append((cursor, work_end))

    useful = [gap for gap in gaps if gap[1] - gap[0] >= timedelta(minutes=60)]
    return max(useful, key=lambda gap: gap[1] - gap[0], default=None)


def calendar_agenda_briefing(
    start: datetime,
    events: Sequence[Mapping[str, Any]],
    language: SpokenLanguage,
    *,
    now: datetime | None = None,
) -> str:
    """Speak verified Calendar events as a natural briefing, never as a UI acknowledgment."""
    zone = start.tzinfo if isinstance(start.tzinfo, ZoneInfo) else local_timezone()
    day = _day_label(start, language, now=now)
    if not events:
        return (
            f"सर, {day} आपके कैलेंडर में कोई इवेंट नहीं है।"
            if language == "hi"
            else f"Sir, you don't have any Calendar events scheduled {day}."
        )

    all_day = [str(event.get("title") or "untitled event").strip() for event in events if event.get("all_day")]
    timed = _timed_events(events, zone)
    clauses: list[str] = []

    for event_start, _event_end, title in timed[:4]:
        if language == "hi":
            clauses.append(f"{_clock(event_start, language)} {title} है")
        else:
            clauses.append(f"{title} at {_clock(event_start, language)}")

    if all_day:
        title = all_day[0]
        clauses.insert(0, f"{title} पूरे दिन है" if language == "hi" else f"{title} is all day")

    remaining = max(0, len(events) - min(4, len(timed)) - (1 if all_day else 0))
    schedule = _join_natural(clauses, language)

    if language == "hi":
        opening = f"सर, {day} आपके {len(events)} शेड्यूल्ड काम हैं।"
        body = f" {schedule}।" if schedule else ""
        extra = f" इसके अलावा {remaining} और इवेंट हैं।" if remaining else ""
    else:
        noun = "item" if len(events) == 1 else "items"
        opening = f"Sir, you have {len(events)} scheduled {noun} {day}."
        body = f" {schedule}." if schedule else ""
        extra = f" There {'is' if remaining == 1 else 'are'} {remaining} more." if remaining else ""

    gap = _largest_day_gap(start, timed)
    gap_text = ""
    if gap is not None and timed:
        gap_start, gap_end = gap
        if language == "hi":
            gap_text = f" आपका सबसे बड़ा खाली समय {_clock(gap_start, language)} से {_clock(gap_end, language)} तक है।"
        else:
            gap_text = f" Your largest free block is from {_clock(gap_start, language)} to {_clock(gap_end, language)}."

    return (opening + body + extra + gap_text).strip()


def calendar_free_busy_briefing(
    request: ParsedCalendarRequest,
    busy: Sequence[Mapping[str, str]],
    language: SpokenLanguage,
    *,
    now: datetime | None = None,
) -> str:
    zone = ZoneInfo(request.timezone)
    start = request.start.astimezone(zone)
    end = request.end.astimezone(zone)
    day = _day_label(start, language, now=now)
    window_name = request.daypart or ""

    if not busy:
        if language == "hi":
            part = f" {window_name}" if window_name else ""
            return f"सर, {day}{part} आप {_clock(start, language)} से {_clock(end, language)} तक पूरी तरह फ्री हैं।"
        part = f" {window_name}" if window_name else ""
        return f"Sir, you're completely free {day}{part}, from {_clock(start, language)} to {_clock(end, language)}."

    windows = free_windows(start, end, list(busy))
    if not windows:
        return (
            f"सर, {day} {_clock(start, language)} से {_clock(end, language)} तक आपका कैलेंडर व्यस्त है।"
            if language == "hi"
            else f"Sir, you're busy {day} from {_clock(start, language)} to {_clock(end, language)}."
        )

    longest = max(windows, key=lambda item: item[1] - item[0])
    if language == "hi":
        return (
            f"सर, {day} आपका कैलेंडर कुछ समय व्यस्त है, लेकिन सबसे अच्छा खाली समय "
            f"{_clock(longest[0], language)} से {_clock(longest[1], language)} तक है।"
        )
    return (
        f"Sir, your calendar is partly busy {day}, but your best free block is from "
        f"{_clock(longest[0], language)} to {_clock(longest[1], language)}."
    )


def calendar_open_slots_briefing(
    request: ParsedCalendarRequest,
    slots: Sequence[Mapping[str, str]],
    language: SpokenLanguage,
    *,
    now: datetime | None = None,
) -> str:
    zone = ZoneInfo(request.timezone)
    day = _day_label(request.start.astimezone(zone), language, now=now)
    if not slots:
        return (
            f"सर, {day} उस समय सीमा में मुझे कोई खुला स्लॉट नहीं मिला।"
            if language == "hi"
            else f"Sir, I couldn't find an open slot in that window {day}."
        )

    starts: list[str] = []
    for slot in slots[:3]:
        value = _as_datetime(slot.get("start"), zone)
        if value is not None:
            starts.append(_clock(value, language))
    if not starts:
        return (
            f"सर, {day} उपलब्धता मिली है।"
            if language == "hi"
            else f"Sir, I found availability {day}."
        )

    joined = _join_natural(starts, language)
    if language == "hi":
        return f"सर, {day} आपके लिए अच्छे खुले स्लॉट {joined} से शुरू होते हैं।"
    return f"Sir, the first good openings {day} start at {joined}."
