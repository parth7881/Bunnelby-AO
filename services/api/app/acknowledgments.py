from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Final, Literal, Mapping

SpokenLanguage = Literal["en", "hi"]
ActionType = Literal[
    "greeting",
    "general_answer",
    "gmail_summary",
    "gmail_empty",
    "calendar_read",
    "calendar_created",
    "file_search",
    "terminal_complete",
    "approval_required",
    "task_complete",
    "error",
    "generic",
]

SUPPORTED_ACTION_TYPES: Final[frozenset[str]] = frozenset(
    {
        "greeting",
        "general_answer",
        "gmail_summary",
        "gmail_empty",
        "calendar_read",
        "calendar_created",
        "file_search",
        "terminal_complete",
        "approval_required",
        "task_complete",
        "error",
        "generic",
    }
)

_DEVANAGARI_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\u0900-\u097f]")
_ROMAN_HINDI_STRONG: Final[frozenset[str]] = frozenset(
    {
        "kya",
        "kaise",
        "mera",
        "mere",
        "meri",
        "mujhe",
        "batao",
        "bata",
        "samjhao",
        "samjha",
        "karo",
        "gaya",
        "gayi",
        "hota",
        "hoti",
        "dekh",
        "dekho",
        "dhundo",
        "dhoondo",
        "yaani",
        "yani",
        "jisme",
        "pehle",
        "phir",
        "jawab",
        "jaankari",
        "karta",
        "karti",
        "karte",
        "lekin",
        "liye",
        "usi",
    }
)
_ROMAN_HINDI_WEAK: Final[frozenset[str]] = frozenset(
    {"hai", "hain", "ho", "kar", "kr", "ka", "ki", "ke", "ko"}
)
_URL_PATTERN: Final[re.Pattern[str]] = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_CODE_BLOCK_PATTERN: Final[re.Pattern[str]] = re.compile(r"```.*?```", re.DOTALL)
_MARKDOWN_LINK_PATTERN: Final[re.Pattern[str]] = re.compile(r"\[([^\]]+)]\([^)]*\)")
_MARKDOWN_PREFIX_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?m)^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)"
)

_ENGLISH_NUMBERS: Final[tuple[str, ...]] = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen", "twenty",
)
_HINDI_NUMBERS: Final[tuple[str, ...]] = (
    "शून्य", "एक", "दो", "तीन", "चार", "पाँच", "छह", "सात", "आठ", "नौ", "दस",
    "ग्यारह", "बारह", "तेरह", "चौदह", "पंद्रह", "सोलह", "सत्रह", "अठारह", "उन्नीस", "बीस",
)

SPOKEN_FALLBACKS: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    "en": {
        "greeting": ("Good to hear from you, sir.", "I'm here, sir."),
        "general_answer": (
            "The complete answer is ready on screen.",
            "I've put the complete answer on screen.",
        ),
        "gmail_summary": ("Your inbox summary is ready.", "I've reviewed your inbox."),
        "gmail_empty": ("Your inbox is clear.", "You have no unread emails, sir."),
        "calendar_read": ("I've checked your calendar.", "Your schedule is ready."),
        "calendar_created": ("The calendar event is ready.", "I've prepared the event."),
        "file_search": ("I found the relevant files.", "The file search is complete."),
        "terminal_complete": ("The check is complete.", "Done."),
        "approval_required": (
            "I need your approval to continue.",
            "That action is waiting for your approval.",
        ),
        "task_complete": ("Done.", "That's ready."),
        "error": (
            "That request failed. Nothing else was affected. Please try again.",
            "I couldn't complete that. Your other services are unaffected.",
        ),
        "generic": ("That's ready.", "I've completed the request."),
    },
    "hi": {
        "greeting": ("मैं यहाँ हूँ, सर।", "जी सर, बताइए।"),
        "general_answer": ("पूरा जवाब स्क्रीन पर उपलब्ध है।", "विस्तृत जवाब स्क्रीन पर तैयार है।"),
        "gmail_summary": ("आपके इनबॉक्स की जानकारी तैयार है।", "मैंने आपका इनबॉक्स देख लिया है।"),
        "gmail_empty": ("आपके इनबॉक्स में कोई नया ईमेल नहीं है।", "आपका इनबॉक्स साफ़ है, सर।"),
        "calendar_read": ("मैंने आपका कैलेंडर देख लिया है।", "आपका शेड्यूल तैयार है।"),
        "calendar_created": ("कैलेंडर इवेंट तैयार है।", "इवेंट तैयार कर दिया है।"),
        "file_search": ("संबंधित फ़ाइलें मिल गई हैं।", "फ़ाइल खोज पूरी हो गई है।"),
        "terminal_complete": ("जाँच पूरी हो गई है।", "हो गया।"),
        "approval_required": (
            "आगे बढ़ने के लिए आपकी अनुमति चाहिए।",
            "यह कार्रवाई आपकी मंज़ूरी का इंतज़ार कर रही है।",
        ),
        "task_complete": ("हो गया, सर।", "काम पूरा हो गया है।"),
        "error": (
            "यह अनुरोध पूरा नहीं हुआ। बाकी सेवाएँ सुरक्षित हैं। कृपया फिर कोशिश करें।",
            "मैं यह पूरा नहीं कर पाया। आपकी दूसरी सेवाओं पर कोई असर नहीं पड़ा।",
        ),
        "generic": ("यह तैयार है।", "काम पूरा हो गया है।"),
    },
}


@dataclass(frozen=True)
class SpokenResponse:
    text: str
    language: SpokenLanguage
    action_type: ActionType


# Prompt 6 compatibility for callers that still import this name.
SpokenAcknowledgment = SpokenResponse


def detect_spoken_language(user_message: str) -> SpokenLanguage:
    """Detect English versus Hindi/Hinglish locally without an LLM call."""
    if _DEVANAGARI_PATTERN.search(user_message):
        return "hi"

    tokens = set(re.findall(r"[a-z]+", user_message.casefold()))
    if tokens & _ROMAN_HINDI_STRONG:
        return "hi"
    if len(tokens & _ROMAN_HINDI_WEAK) >= 2:
        return "hi"
    return "en"


def _number_for_speech(value: int, language: SpokenLanguage) -> str:
    numbers = _HINDI_NUMBERS if language == "hi" else _ENGLISH_NUMBERS
    if 0 <= value < len(numbers):
        return numbers[value]
    return str(value)


def _stable_choice(
    user_message: str,
    language: SpokenLanguage,
    action_type: ActionType,
) -> str:
    phrases = SPOKEN_FALLBACKS[language][action_type]
    key = f"{language}|{action_type}|{user_message.strip().casefold()}"
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return phrases[int.from_bytes(digest[:2], "big") % len(phrases)]


def _tool_result_text(
    language: SpokenLanguage,
    action_type: ActionType,
    metadata: Mapping[str, object],
) -> str | None:
    if action_type not in {"gmail_summary", "gmail_empty"}:
        return None

    raw_count = metadata.get("email_count")
    if not isinstance(raw_count, int) or raw_count < 0:
        return None

    if raw_count == 0 or action_type == "gmail_empty":
        if language == "hi":
            return "आपके इनबॉक्स में कोई अनरीड ईमेल नहीं है।"
        return "You have no unread inbox emails."

    count = _number_for_speech(raw_count, language)
    unread_only = bool(metadata.get("unread_only"))
    if language == "hi":
        if unread_only:
            return f"मौजूदा इनबॉक्स जाँच में {count} अनरीड ईमेल मिले हैं। पूरी समरी स्क्रीन पर है।"
        return f"मुझे {count} हाल के ईमेल मिले हैं। पूरी समरी स्क्रीन पर है।"

    noun = "email" if raw_count == 1 else "emails"
    if unread_only:
        return f"I found {count} unread {noun} in the current inbox scan. The complete summary is on screen."
    return f"I found {count} recent inbox {noun}. The complete summary is on screen."


def normalize_spoken_text(
    text: str,
    language: SpokenLanguage,
    *,
    max_words: int = 65,
) -> str:
    """Remove screen-only syntax and make a bounded string safe for local TTS."""
    cleaned = _CODE_BLOCK_PATTERN.sub(" ", text)
    cleaned = _MARKDOWN_LINK_PATTERN.sub(r"\1", cleaned)
    cleaned = _URL_PATTERN.sub(" ", cleaned)
    cleaned = _MARKDOWN_PREFIX_PATTERN.sub("", cleaned)
    cleaned = cleaned.replace("`", "").replace("**", "").replace("__", "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if language == "hi":
        replacements = {
            "RAG": "आर ए जी",
            "AI": "ए आई",
            "API": "ए पी आई",
            "LLM": "एल एल एम",
            "Gmail": "जीमेल",
            "GitHub": "गिटहब",
            "Python": "पाइथन",
        }
    else:
        replacements = {"RAG": "R A G", "API": "A P I", "LLM": "L L M"}

    for source, replacement in replacements.items():
        cleaned = re.sub(rf"\b{re.escape(source)}\b", replacement, cleaned, flags=re.IGNORECASE)

    # "Sir" is deliberate, never repeated within one concise turn.
    seen_sir = False

    def keep_first_sir(match: re.Match[str]) -> str:
        nonlocal seen_sir
        if seen_sir:
            return ""
        seen_sir = True
        return match.group(0)

    cleaned = re.sub(r"\bsir\b", keep_first_sir, cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+([,.;:!?।])", r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,")

    words = cleaned.split()
    if len(words) > max_words:
        cleaned = " ".join(words[:max_words]).rstrip(" ,;:")
        if cleaned and cleaned[-1] not in ".!?।":
            cleaned += "."
    return cleaned


def select_spoken_response(
    user_message: str,
    action_type: str,
    *,
    preferred_text: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> SpokenResponse:
    """Choose useful speech without a second model request.

    Normal conversation uses the concise text produced alongside the screen reply.
    Tool actions prefer deterministic result-aware language based on confirmed data.
    """
    language = detect_spoken_language(user_message)
    safe_action: ActionType = (
        action_type if action_type in SUPPORTED_ACTION_TYPES else "generic"
    )  # type: ignore[assignment]

    tool_text = _tool_result_text(language, safe_action, metadata or {})
    safe_preferred = preferred_text
    if language == "hi" and safe_preferred and not _DEVANAGARI_PATTERN.search(safe_preferred):
        # Rohan is clearest with Devanagari. A malformed/mismatched model response
        # falls back locally instead of feeding arbitrary Roman Hindi or English.
        safe_preferred = None
    candidate = tool_text or safe_preferred or _stable_choice(user_message, language, safe_action)
    text = normalize_spoken_text(candidate, language)
    if not text:
        text = _stable_choice(user_message, language, safe_action)
    return SpokenResponse(text=text, language=language, action_type=safe_action)


def select_acknowledgment(user_message: str, action_type: str) -> SpokenAcknowledgment:
    """Backwards-compatible Prompt 6 wrapper."""
    return select_spoken_response(user_message, action_type)
