from __future__ import annotations

import io
import logging
import os
import threading
import wave
from pathlib import Path
from typing import Final, Literal

from dotenv import load_dotenv

from .database import PROJECT_ROOT

logger = logging.getLogger(__name__)

load_dotenv(PROJECT_ROOT / ".env")

TTSLanguage = Literal["en", "hi"]
MAX_TTS_CHARS: Final[int] = 600
DEFAULT_ENGLISH_VOICE: Final[str] = "en_US-john-medium"
DEFAULT_HINDI_VOICE: Final[str] = "hi_IN-rohan-medium"
DEFAULT_ENGLISH_LENGTH_SCALE: Final[float] = 1.11
DEFAULT_HINDI_LENGTH_SCALE: Final[float] = 1.12

_voice_cache: dict[TTSLanguage, object] = {}
_voice_cache_paths: dict[TTSLanguage, Path] = {}
_cache_lock = threading.Lock()
_synthesis_locks: Final[dict[TTSLanguage, threading.Lock]] = {
    "en": threading.Lock(),
    "hi": threading.Lock(),
}


class TTSServiceError(RuntimeError):
    """Base exception for optional AO voice output."""


class TTSDisabledError(TTSServiceError):
    """Raised when local speech output is disabled."""


class PiperUnavailableError(TTSServiceError):
    """Raised when the optional Piper runtime is unavailable."""


class VoiceModelMissingError(TTSServiceError):
    """Raised when a configured Piper voice is not installed."""


class TTSSynthesisError(TTSServiceError):
    """Raised when Piper cannot synthesize a valid WAV."""


def piper_enabled() -> bool:
    return os.getenv("PIPER_ENABLED", "true").strip().casefold() in {"1", "true", "yes", "on"}


def resolve_voice_directory() -> Path:
    configured = os.getenv("PIPER_VOICE_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()

    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / "AO" / "piper" / "voices"


def voice_name(language: TTSLanguage) -> str:
    if language == "hi":
        return os.getenv("PIPER_HINDI_VOICE", DEFAULT_HINDI_VOICE).strip() or DEFAULT_HINDI_VOICE
    return os.getenv("PIPER_ENGLISH_VOICE", DEFAULT_ENGLISH_VOICE).strip() or DEFAULT_ENGLISH_VOICE


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using %.2f", name, raw, default)
        return default
    if not minimum <= value <= maximum:
        logger.warning("Out-of-range %s=%r; using %.2f", name, raw, default)
        return default
    return value


def length_scale(language: TTSLanguage) -> float:
    if language == "hi":
        return _env_float(
            "PIPER_HI_LENGTH_SCALE",
            DEFAULT_HINDI_LENGTH_SCALE,
            minimum=0.75,
            maximum=1.5,
        )
    return _env_float(
        "PIPER_EN_LENGTH_SCALE",
        DEFAULT_ENGLISH_LENGTH_SCALE,
        minimum=0.75,
        maximum=1.5,
    )


def _model_path(language: TTSLanguage) -> Path:
    return resolve_voice_directory() / f"{voice_name(language)}.onnx"


def _load_voice(language: TTSLanguage) -> object:
    model_path = _model_path(language)
    config_path = model_path.with_suffix(model_path.suffix + ".json")
    if not model_path.is_file() or not config_path.is_file():
        label = "Hindi" if language == "hi" else "English"
        raise VoiceModelMissingError(f"{label} Piper voice is not installed.")

    with _cache_lock:
        cached = _voice_cache.get(language)
        if cached is not None and _voice_cache_paths.get(language) == model_path:
            return cached

        try:
            from piper import PiperVoice
        except (ImportError, ModuleNotFoundError) as exc:
            raise PiperUnavailableError("Piper is not installed in AO's Python environment.") from exc

        try:
            voice = PiperVoice.load(str(model_path), config_path=str(config_path), use_cuda=False)
        except Exception as exc:
            logger.warning("Could not load the %s Piper voice: %s", language, exc)
            raise PiperUnavailableError("The configured Piper voice could not be loaded.") from exc

        _voice_cache[language] = voice
        _voice_cache_paths[language] = model_path
        return voice


def synthesize_speech(
    text: str,
    language: TTSLanguage,
    *,
    length_scale_override: float | None = None,
) -> bytes:
    if not piper_enabled():
        raise TTSDisabledError("Piper voice output is disabled.")

    clean_text = text.strip()
    if not clean_text:
        raise TTSSynthesisError("Speech text is empty.")
    if len(clean_text) > MAX_TTS_CHARS:
        raise TTSSynthesisError("Speech text is too long.")
    if language not in {"en", "hi"}:
        raise TTSSynthesisError("Unsupported speech language.")

    selected_length_scale = (
        length_scale_override if length_scale_override is not None else length_scale(language)
    )
    if not 0.75 <= selected_length_scale <= 1.5:
        raise TTSSynthesisError("Piper length scale is out of range.")

    voice = _load_voice(language)
    wav_buffer = io.BytesIO()
    try:
        from piper import SynthesisConfig

        synthesis_config = SynthesisConfig(length_scale=selected_length_scale)
        with _synthesis_locks[language]:
            with wave.open(wav_buffer, "wb") as wav_file:
                voice.synthesize_wav(  # type: ignore[attr-defined]
                    clean_text,
                    wav_file,
                    syn_config=synthesis_config,
                )
        wav_bytes = wav_buffer.getvalue()
    except Exception as exc:
        logger.warning("Piper synthesis failed for language=%s: %s", language, exc)
        raise TTSSynthesisError("Piper could not synthesize the spoken response.") from exc

    if len(wav_bytes) <= 44 or not wav_bytes.startswith(b"RIFF"):
        raise TTSSynthesisError("Piper returned invalid WAV audio.")
    return wav_bytes


def synthesize_acknowledgment(text: str, language: TTSLanguage) -> bytes:
    """Prompt 6 compatibility wrapper for the generalized speech synthesizer."""
    return synthesize_speech(text, language)
