from __future__ import annotations

import re
from typing import Final, Literal

TTSLanguage = Literal["en", "hi"]

_MARKDOWN_RE: Final[re.Pattern[str]] = re.compile(r"[*_`#]+")
_WHITESPACE_RE: Final[re.Pattern[str]] = re.compile(r"\s+")

# Common technical terms Bunnelby says frequently. Keep this list deliberately small and
# deterministic; arbitrary transliteration belongs in a future language model/provider layer.
_HINDI_TERM_MAP: Final[dict[str, str]] = {
    "AI": "ए आई",
    "API": "ए पी आई",
    "CPU": "सी पी यू",
    "GPU": "जी पी यू",
    "RAM": "रैम",
    "URL": "यू आर एल",
    "USB": "यू एस बी",
    "OTP": "ओ टी पी",
    "PDF": "पी डी एफ",
    "Gmail": "जीमेल",
    "GitHub": "गिटहब",
    "Google": "गूगल",
    "Calendar": "कैलेंडर",
    "Bunnelby": "बनलबी",
    "VS Code": "वी एस कोड",
}

_ENGLISH_TERM_MAP: Final[dict[str, str]] = {
    "API": "A P I",
    "CPU": "C P U",
    "GPU": "G P U",
    "URL": "U R L",
    "USB": "U S B",
    "OTP": "O T P",
    "PDF": "P D F",
}

_TIME_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(\d{1,2})(?::([0-5]\d))?\s*(AM|PM)\b",
    re.IGNORECASE,
)


def _replace_terms(text: str, replacements: dict[str, str]) -> str:
    # Longest terms first so "VS Code" is handled before shorter tokens.
    for source in sorted(replacements, key=len, reverse=True):
        text = re.sub(
            rf"(?<![\w]){re.escape(source)}(?![\w])",
            replacements[source],
            text,
            flags=re.IGNORECASE,
        )
    return text


def _normalize_hindi_times(text: str) -> str:
    def replacement(match: re.Match[str]) -> str:
        hour = int(match.group(1))
        minute = int(match.group(2) or "0")
        marker = match.group(3).upper()
        if minute:
            clock = f"{hour} बजकर {minute} मिनट"
        else:
            clock = f"{hour} बजे"
        if marker == "AM":
            return f"सुबह {clock}"
        if hour < 5:
            return f"दोपहर {clock}"
        return f"शाम {clock}"

    return _TIME_RE.sub(replacement, text)


def _normalize_english_times(text: str) -> str:
    def replacement(match: re.Match[str]) -> str:
        hour = int(match.group(1))
        minute = int(match.group(2) or "0")
        marker = match.group(3).upper()
        if minute:
            return f"{hour}:{minute:02d} {marker}"
        return f"{hour} {marker}"

    return _TIME_RE.sub(replacement, text)


def normalize_tts_text(text: str, language: TTSLanguage) -> str:
    """Prepare spoken text for local TTS without changing its factual meaning.

    This function intentionally avoids broad transliteration or rewriting. It removes display-only
    markup and normalizes a small set of frequent technical terms/times that local voices commonly
    mispronounce. Provider-specific phoneme/token handling can be layered on later.
    """
    clean = str(text or "").strip()
    if not clean:
        return ""

    clean = _MARKDOWN_RE.sub("", clean)
    if language == "hi":
        clean = _replace_terms(clean, _HINDI_TERM_MAP)
        clean = _normalize_hindi_times(clean)
    else:
        clean = _replace_terms(clean, _ENGLISH_TERM_MAP)
        clean = _normalize_english_times(clean)

    clean = clean.replace("–", " से " if language == "hi" else " to ")
    clean = clean.replace("—", ", ")
    clean = _WHITESPACE_RE.sub(" ", clean)
    return clean.strip()
