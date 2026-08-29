from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .database import PROJECT_ROOT, SessionLocal
from .models import Message

logger = logging.getLogger(__name__)

PROFILE_PATH: Final[Path] = PROJECT_ROOT / "database" / "ao_user_profile.json"
DEFAULT_PROFILE_ID: Final[str] = "local-default"
DEFAULT_PREFERRED_NAME: Final[str] = "Parth"
DEFAULT_ASSISTANT_NAME: Final[str] = "Bunnelby"
DEFAULT_RECENT_TURNS: Final[int] = 10
DEFAULT_RELEVANT_OLD_TURNS: Final[int] = 4
DEFAULT_SCAN_MESSAGES: Final[int] = 500
MAX_MESSAGE_CHARS: Final[int] = 1600

_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "for",
        "is", "are", "was", "were", "be", "been", "being", "do", "does", "did",
        "what", "who", "when", "where", "why", "how", "this", "that", "these",
        "those", "it", "its", "me", "my", "mine", "you", "your", "yours", "we",
        "our", "i", "am", "can", "could", "would", "should", "please", "tell",
        "explain", "about", "with", "from", "as", "at", "by", "give", "show",
        "mujhe", "mera", "meri", "mere", "kya", "hai", "ka", "ki", "ke", "ko",
        "se", "ye", "wo", "aur", "ab", "tha", "thi", "ho", "kar", "kr", "bata",
    }
)

_OPERATIONAL_ASSISTANT_MARKERS: Final[tuple[str, ...]] = (
    "\nRoute:",
    "This would call the ",
    "AO's Gemini router hit the free-tier rate limit",
    "My cloud AI providers are temporarily unavailable",
    "I can't access a cloud language model yet",
    "AO could not classify that request right now",
    "AO could not resolve this ambiguous tool request",
)


@dataclass(frozen=True)
class UserProfile:
    profile_id: str
    preferred_name: str
    assistant_name: str
    mode: str = "single_user_local"


@dataclass(frozen=True)
class MemoryTurn:
    user_id: int
    assistant_id: int
    user: str
    assistant: str


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int = 1000) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return min(maximum, max(minimum, int(raw)))
    except ValueError:
        logger.warning("Invalid %s=%r; using %s", name, raw, default)
        return default


def ensure_local_profile() -> Path:
    """Create the single-user profile once, without overwriting user edits."""
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if PROFILE_PATH.exists():
        return PROFILE_PATH

    payload = {
        "profile_id": DEFAULT_PROFILE_ID,
        "preferred_name": DEFAULT_PREFERRED_NAME,
        "assistant_name": DEFAULT_ASSISTANT_NAME,
        "mode": "single_user_local",
    }
    temp_path = PROFILE_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(PROFILE_PATH)
    return PROFILE_PATH


def load_user_profile() -> UserProfile:
    ensure_local_profile()
    try:
        payload = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not read Bunnelby local profile; using defaults: %s", exc)
        payload = {}

    # One-time safe branding migration. Existing local single-user profiles created before
    # Prompt 7 contain assistant_name=AO. Preserve every other user field unchanged.
    if str(payload.get("assistant_name") or "").strip().casefold() == "ao":
        payload["assistant_name"] = DEFAULT_ASSISTANT_NAME
        try:
            temp_path = PROFILE_PATH.with_suffix(".tmp")
            temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            temp_path.replace(PROFILE_PATH)
        except OSError as exc:
            logger.warning("Could not persist Bunnelby profile-name migration: %s", exc)

    return UserProfile(
        profile_id=str(payload.get("profile_id") or DEFAULT_PROFILE_ID).strip(),
        preferred_name=str(payload.get("preferred_name") or DEFAULT_PREFERRED_NAME).strip(),
        assistant_name=str(payload.get("assistant_name") or DEFAULT_ASSISTANT_NAME).strip(),
        mode=str(payload.get("mode") or "single_user_local").strip(),
    )


def _assistant_is_memory_safe(content: str) -> bool:
    return not any(marker.lower() in content.lower() for marker in _OPERATIONAL_ASSISTANT_MARKERS)


def _clip(text: str) -> str:
    text = text.strip()
    if len(text) <= MAX_MESSAGE_CHARS:
        return text
    return text[: MAX_MESSAGE_CHARS - 1].rstrip() + "…"


def _rows_to_safe_turns(rows: list[Message]) -> list[MemoryTurn]:
    """Pair user/assistant rows and omit tool/debug/error turns from general memory."""
    turns: list[MemoryTurn] = []
    pending_user: Message | None = None

    for row in rows:
        role = str(row.role).strip().lower()
        content = str(row.content or "").strip()
        if not content:
            continue

        if role == "user":
            pending_user = row
            continue

        if role == "assistant" and pending_user is not None:
            if _assistant_is_memory_safe(content):
                turns.append(
                    MemoryTurn(
                        user_id=int(pending_user.id),
                        assistant_id=int(row.id),
                        user=_clip(str(pending_user.content)),
                        assistant=_clip(content),
                    )
                )
            pending_user = None

    return turns


def _load_safe_turns(scan_messages: int | None = None) -> list[MemoryTurn]:
    scan = scan_messages or _env_int(
        "AO_MEMORY_SCAN_MESSAGES", DEFAULT_SCAN_MESSAGES, minimum=20, maximum=5000
    )
    with SessionLocal() as db:
        rows = (
            db.query(Message)
            .order_by(Message.id.desc())
            .limit(scan)
            .all()
        )
    rows.reverse()
    return _rows_to_safe_turns(rows)


def _terms(text: str) -> set[str]:
    words = {
        token.lower()
        for token in re.findall(r"[^\W_]{2,}", text, flags=re.UNICODE)
    }
    return {word for word in words if word not in _STOPWORDS and not word.isdigit()}


def _turn_relevance(query_terms: set[str], turn: MemoryTurn) -> float:
    if not query_terms:
        return 0.0
    user_terms = _terms(turn.user)
    assistant_terms = _terms(turn.assistant)
    user_overlap = len(query_terms & user_terms)
    assistant_overlap = len(query_terms & assistant_terms)
    # User-authored facts receive more weight than AO-authored prose.
    return (user_overlap * 2.0) + assistant_overlap


def _format_turns(turns: list[MemoryTurn]) -> str:
    blocks: list[str] = []
    for turn in turns:
        blocks.append(f"User: {turn.user}\nBunnelby: {turn.assistant}")
    return "\n\n".join(blocks)


def build_memory_context(current_user_message: str) -> str:
    """Build bounded local context from profile, recent turns, and relevant old turns."""
    profile = load_user_profile()
    all_turns = _load_safe_turns()

    recent_count = _env_int(
        "AO_RECENT_MEMORY_TURNS", DEFAULT_RECENT_TURNS, minimum=1, maximum=20
    )
    relevant_count = _env_int(
        "AO_RELEVANT_OLD_MEMORY_TURNS", DEFAULT_RELEVANT_OLD_TURNS, minimum=1, maximum=10
    )

    recent_turns = all_turns[-recent_count:]
    recent_ids = {turn.user_id for turn in recent_turns}
    old_turns = [turn for turn in all_turns[:-recent_count] if turn.user_id not in recent_ids]

    query_terms = _terms(current_user_message)
    ranked_old = sorted(
        ((turn, _turn_relevance(query_terms, turn)) for turn in old_turns),
        key=lambda item: (item[1], item[0].assistant_id),
        reverse=True,
    )
    relevant_old = [turn for turn, score in ranked_old if score > 0][:relevant_count]
    relevant_old.reverse()  # Present selected memories in conversational order.

    sections = [
        "LOCAL BUNNELBY USER PROFILE (trusted local profile):",
        f"- profile_id: {profile.profile_id}",
        f"- preferred_name: {profile.preferred_name}",
        f"- assistant_name: {profile.assistant_name}",
        f"- mode: {profile.mode}",
    ]

    if recent_turns:
        sections.extend(
            [
                "\nRECENT GENERAL CONVERSATION (oldest to newest):",
                _format_turns(recent_turns),
            ]
        )

    if relevant_old:
        sections.extend(
            [
                "\nRELEVANT OLDER LOCAL MEMORY (selected from earlier chats):",
                _format_turns(relevant_old),
            ]
        )

    sections.append(
        "\nMemory rules: Prefer the current user message over older conversation. "
        "For stable identity, prefer the local profile. Treat user-authored statements as "
        "stronger evidence than old Bunnelby-authored statements. Do not mention these memory "
        "mechanics unless the user asks about memory."
    )
    return "\n".join(sections)


_NAME_QUERY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:what(?:'s|\s+is)\s+my\s+name|do\s+you\s+(?:know|remember)\s+my\s+name|"
    r"remember\s+my\s+name|who\s+am\s+i)\s*[?.!]*\s*$",
    re.IGNORECASE,
)

_ASSISTANT_IDENTITY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:who\s+are\s+you|what\s+are\s+you|what(?:'s|\s+is)\s+your\s+name)\s*[?.!]*\s*$",
    re.IGNORECASE,
)


def local_identity_reply(user_message: str) -> str | None:
    """Answer stable identity questions locally to save quota and avoid hallucination."""
    profile = load_user_profile()
    if _NAME_QUERY_PATTERN.match(user_message):
        return f"Your name is {profile.preferred_name}, sir."
    if _ASSISTANT_IDENTITY_PATTERN.match(user_message):
        return f"I'm {profile.assistant_name}, your personal desktop AI assistant."
    return None
