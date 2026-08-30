from __future__ import annotations

import asyncio
import io
import logging
import os
import subprocess
import threading
import wave
from pathlib import Path
from typing import Final, Literal

from dotenv import load_dotenv

from .database import PROJECT_ROOT
from .tts_pronunciation import normalize_tts_text

logger = logging.getLogger(__name__)

load_dotenv(PROJECT_ROOT / ".env")

TTSLanguage = Literal["en", "hi"]
MAX_TTS_CHARS: Final[int] = 600

# Primary online Bunnelby voices selected during Prompt 9.2 listening tests.
DEFAULT_EDGE_ENGLISH_VOICE: Final[str] = "en-GB-RyanNeural"
DEFAULT_EDGE_HINDI_VOICE: Final[str] = "hi-IN-MadhurNeural"
DEFAULT_EDGE_ENGLISH_RATE: Final[str] = "+4%"
DEFAULT_EDGE_HINDI_RATE: Final[str] = "+8%"
DEFAULT_EDGE_PITCH: Final[str] = "-12Hz"
DEFAULT_EDGE_TIMEOUT_SECONDS: Final[float] = 10.0

# Existing local/offline Piper voices remain the safety fallback.
DEFAULT_ENGLISH_VOICE: Final[str] = "en_US-john-medium"
DEFAULT_HINDI_VOICE: Final[str] = "hi_IN-rohan-medium"
DEFAULT_ENGLISH_LENGTH_SCALE: Final[float] = 1.11
DEFAULT_HINDI_LENGTH_SCALE: Final[float] = 1.12

# Balanced Hindi pause compression from the Prompt 9.2 voice lab. It only reduces
# unusually long silent gaps; short conversational pauses remain intact.
EDGE_HINDI_AUDIO_FILTER: Final[str] = (
    "silenceremove=stop_periods=-1:stop_duration=0.28:"
    "stop_threshold=-40dB:stop_silence=0.14"
)

_voice_cache: dict[TTSLanguage, object] = {}
_voice_cache_paths: dict[TTSLanguage, Path] = {}
_cache_lock = threading.Lock()
_synthesis_locks: Final[dict[TTSLanguage, threading.Lock]] = {
    "en": threading.Lock(),
    "hi": threading.Lock(),
}


class TTSServiceError(RuntimeError):
    """Base exception for optional Bunnelby voice output."""


class TTSDisabledError(TTSServiceError):
    """Raised when speech output is disabled or no enabled provider remains."""


class PiperUnavailableError(TTSServiceError):
    """Raised when the optional Piper runtime is unavailable."""


class VoiceModelMissingError(TTSServiceError):
    """Raised when a configured Piper voice is not installed."""


class TTSSynthesisError(TTSServiceError):
    """Raised when no TTS provider can synthesize valid audio."""


class _EdgeTTSUnavailableError(TTSServiceError):
    """Internal signal that the online Edge voice should fall back to Piper."""


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().casefold()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def tts_enabled() -> bool:
    return _env_bool("TTS_ENABLED", True)


def edge_tts_enabled() -> bool:
    return _env_bool("EDGE_TTS_ENABLED", True)


def piper_enabled() -> bool:
    return _env_bool("PIPER_ENABLED", True)


def preferred_provider() -> Literal["edge", "piper"]:
    configured = os.getenv("TTS_PROVIDER", "edge").strip().casefold()
    if configured == "piper":
        return "piper"
    if configured not in {"", "edge"}:
        logger.warning("Unsupported TTS_PROVIDER=%r; using Edge with Piper fallback", configured)
    return "edge"


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


def edge_voice_name(language: TTSLanguage) -> str:
    if language == "hi":
        return (
            os.getenv("EDGE_TTS_HINDI_VOICE", DEFAULT_EDGE_HINDI_VOICE).strip()
            or DEFAULT_EDGE_HINDI_VOICE
        )
    return (
        os.getenv("EDGE_TTS_ENGLISH_VOICE", DEFAULT_EDGE_ENGLISH_VOICE).strip()
        or DEFAULT_EDGE_ENGLISH_VOICE
    )


def edge_rate(language: TTSLanguage) -> str:
    default = DEFAULT_EDGE_HINDI_RATE if language == "hi" else DEFAULT_EDGE_ENGLISH_RATE
    env_name = "EDGE_TTS_HI_RATE" if language == "hi" else "EDGE_TTS_EN_RATE"
    return os.getenv(env_name, default).strip() or default


def edge_pitch(language: TTSLanguage) -> str:
    env_name = "EDGE_TTS_HI_PITCH" if language == "hi" else "EDGE_TTS_EN_PITCH"
    return os.getenv(env_name, DEFAULT_EDGE_PITCH).strip() or DEFAULT_EDGE_PITCH


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


def _edge_timeout_seconds() -> float:
    return _env_float(
        "EDGE_TTS_TIMEOUT_SECONDS",
        DEFAULT_EDGE_TIMEOUT_SECONDS,
        minimum=2.0,
        maximum=30.0,
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
            raise PiperUnavailableError("Piper is not installed in Bunnelby's Python environment.") from exc

        try:
            voice = PiperVoice.load(str(model_path), config_path=str(config_path), use_cuda=False)
        except Exception as exc:
            logger.warning("Could not load the %s Piper voice: %s", language, exc)
            raise PiperUnavailableError("The configured Piper voice could not be loaded.") from exc

        _voice_cache[language] = voice
        _voice_cache_paths[language] = model_path
        return voice


async def _collect_edge_audio(
    clean_text: str,
    language: TTSLanguage,
) -> bytes:
    try:
        import edge_tts
    except (ImportError, ModuleNotFoundError) as exc:
        raise _EdgeTTSUnavailableError("edge-tts is not installed.") from exc

    try:
        communicate = edge_tts.Communicate(
            clean_text,
            edge_voice_name(language),
            rate=edge_rate(language),
            pitch=edge_pitch(language),
        )
        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio":
                data = chunk.get("data")
                if isinstance(data, bytes):
                    chunks.append(data)
        audio = b"".join(chunks)
    except Exception as exc:
        raise _EdgeTTSUnavailableError("Edge neural speech request failed.") from exc

    if not audio:
        raise _EdgeTTSUnavailableError("Edge neural speech returned no audio.")
    return audio


def _ffmpeg_creation_flags() -> int:
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return int(subprocess.CREATE_NO_WINDOW)
    return 0


def _edge_mp3_to_wav(mp3_bytes: bytes, language: TTSLanguage) -> bytes:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
    ]
    if language == "hi":
        command.extend(["-af", EDGE_HINDI_AUDIO_FILTER])
    command.extend(
        [
            "-f",
            "wav",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "24000",
            "-ac",
            "1",
            "pipe:1",
        ]
    )

    try:
        completed = subprocess.run(
            command,
            input=mp3_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=15,
            creationflags=_ffmpeg_creation_flags(),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        raise _EdgeTTSUnavailableError("FFmpeg is unavailable for Edge speech conversion.") from exc

    wav_bytes = completed.stdout
    if completed.returncode != 0 or len(wav_bytes) <= 44 or not wav_bytes.startswith(b"RIFF"):
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        if detail:
            logger.warning("FFmpeg could not convert Edge speech: %s", detail[:240])
        raise _EdgeTTSUnavailableError("Edge speech audio conversion failed.")
    return wav_bytes


def _synthesize_edge(clean_text: str, language: TTSLanguage) -> bytes:
    if not edge_tts_enabled():
        raise _EdgeTTSUnavailableError("Edge neural speech is disabled.")

    async def collect_with_timeout() -> bytes:
        return await asyncio.wait_for(
            _collect_edge_audio(clean_text, language),
            timeout=_edge_timeout_seconds(),
        )

    try:
        mp3_bytes = asyncio.run(collect_with_timeout())
    except asyncio.TimeoutError as exc:
        raise _EdgeTTSUnavailableError("Edge neural speech timed out.") from exc
    except RuntimeError as exc:
        # /tts is currently a synchronous FastAPI route and normally runs in a worker thread.
        # Preserve a clean fallback if that execution model changes and an event loop is present.
        raise _EdgeTTSUnavailableError("Edge neural speech could not start safely.") from exc

    return _edge_mp3_to_wav(mp3_bytes, language)


def _synthesize_piper(
    clean_text: str,
    language: TTSLanguage,
    *,
    length_scale_override: float | None = None,
) -> bytes:
    if not piper_enabled():
        raise TTSDisabledError("Piper fallback is disabled.")

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


def synthesize_speech(
    text: str,
    language: TTSLanguage,
    *,
    length_scale_override: float | None = None,
) -> bytes:
    if not tts_enabled():
        raise TTSDisabledError("Bunnelby voice output is disabled.")

    if language not in {"en", "hi"}:
        raise TTSSynthesisError("Unsupported speech language.")

    clean_text = normalize_tts_text(text, language)
    if not clean_text:
        raise TTSSynthesisError("Speech text is empty.")
    if len(clean_text) > MAX_TTS_CHARS:
        raise TTSSynthesisError("Speech text is too long.")

    if preferred_provider() == "piper":
        return _synthesize_piper(
            clean_text,
            language,
            length_scale_override=length_scale_override,
        )

    try:
        return _synthesize_edge(clean_text, language)
    except _EdgeTTSUnavailableError as exc:
        logger.warning("Edge neural voice unavailable; falling back to Piper: %s", exc)
        return _synthesize_piper(
            clean_text,
            language,
            length_scale_override=length_scale_override,
        )


def synthesize_acknowledgment(text: str, language: TTSLanguage) -> bytes:
    """Prompt 6 compatibility wrapper for the generalized speech synthesizer."""
    return synthesize_speech(text, language)
