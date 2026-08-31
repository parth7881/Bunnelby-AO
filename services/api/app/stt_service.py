from __future__ import annotations

import logging
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_STT_MODEL = "small"
DEFAULT_STT_DEVICE = "cpu"
DEFAULT_STT_COMPUTE_TYPE = "int8"
DEFAULT_STT_CPU_THREADS = 4
DEFAULT_STT_BEAM_SIZE = 5
DEFAULT_STT_MAX_AUDIO_BYTES = 12 * 1024 * 1024
SUPPORTED_LANGUAGE_HINTS = {"auto", "en", "hi"}

_CONTENT_TYPE_SUFFIXES = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "application/octet-stream": ".bin",
}


class STTServiceError(RuntimeError):
    """Base exception for local speech-to-text failures."""


class STTDisabledError(STTServiceError):
    """Raised when local STT is disabled by configuration."""


class STTUnavailableError(STTServiceError):
    """Raised when faster-whisper or its model cannot be loaded."""


class STTAudioError(STTServiceError):
    """Raised when the supplied audio payload is invalid or unsupported."""


class STTTranscriptionError(STTServiceError):
    """Raised when inference fails after the model has loaded."""


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    language: str
    language_probability: float
    duration_seconds: float


_model_lock = threading.Lock()
_model: Any | None = None
_model_signature: tuple[str, str, str, int, str] | None = None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() not in {"0", "false", "no", "off"}


def stt_enabled() -> bool:
    return _env_bool("STT_ENABLED", True)


def stt_model_name() -> str:
    return os.getenv("STT_MODEL", DEFAULT_STT_MODEL).strip() or DEFAULT_STT_MODEL


def stt_device() -> str:
    return os.getenv("STT_DEVICE", DEFAULT_STT_DEVICE).strip() or DEFAULT_STT_DEVICE


def stt_compute_type() -> str:
    return os.getenv("STT_COMPUTE_TYPE", DEFAULT_STT_COMPUTE_TYPE).strip() or DEFAULT_STT_COMPUTE_TYPE


def stt_cpu_threads() -> int:
    raw = os.getenv("STT_CPU_THREADS", str(DEFAULT_STT_CPU_THREADS)).strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_STT_CPU_THREADS
    return max(1, min(value, 16))


def stt_beam_size() -> int:
    raw = os.getenv("STT_BEAM_SIZE", str(DEFAULT_STT_BEAM_SIZE)).strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_STT_BEAM_SIZE
    return max(1, min(value, 10))


def stt_max_audio_bytes() -> int:
    raw = os.getenv("STT_MAX_AUDIO_BYTES", str(DEFAULT_STT_MAX_AUDIO_BYTES)).strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_STT_MAX_AUDIO_BYTES
    return max(64 * 1024, min(value, 100 * 1024 * 1024))


def stt_model_root() -> Path:
    configured = os.getenv("STT_MODEL_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser()
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "Bunnelby" / "models" / "stt"
    return Path.home() / ".bunnelby" / "models" / "stt"


def _model_config_signature() -> tuple[str, str, str, int, str]:
    return (
        stt_model_name(),
        stt_device(),
        stt_compute_type(),
        stt_cpu_threads(),
        str(stt_model_root()),
    )


def _load_model() -> Any:
    global _model, _model_signature

    signature = _model_config_signature()
    if _model is not None and _model_signature == signature:
        return _model

    with _model_lock:
        if _model is not None and _model_signature == signature:
            return _model

        try:
            from faster_whisper import WhisperModel
        except Exception as exc:
            raise STTUnavailableError(
                "faster-whisper is not available in the Bunnelby backend environment."
            ) from exc

        model_root = stt_model_root()
        try:
            model_root.mkdir(parents=True, exist_ok=True)
            model = WhisperModel(
                stt_model_name(),
                device=stt_device(),
                compute_type=stt_compute_type(),
                cpu_threads=stt_cpu_threads(),
                num_workers=1,
                download_root=str(model_root),
            )
        except Exception as exc:
            logger.warning("Bunnelby STT model load failed: %s", exc)
            raise STTUnavailableError(
                "The local speech recognition model could not be loaded."
            ) from exc

        _model = model
        _model_signature = signature
        logger.info(
            "Bunnelby STT ready: model=%s device=%s compute=%s threads=%s",
            stt_model_name(),
            stt_device(),
            stt_compute_type(),
            stt_cpu_threads(),
        )
        return model


def _suffix_for_content_type(content_type: str | None) -> str:
    normalized = (content_type or "application/octet-stream").split(";", 1)[0].strip().casefold()
    return _CONTENT_TYPE_SUFFIXES.get(normalized, ".bin")


def _validate_language_hint(language: str | None) -> str:
    normalized = (language or "auto").strip().casefold()
    if normalized not in SUPPORTED_LANGUAGE_HINTS:
        raise STTAudioError("STT language must be 'auto', 'en', or 'hi'.")
    return normalized


def _normalize_text(parts: list[str]) -> str:
    return " ".join(part.strip() for part in parts if part and part.strip()).strip()


def transcribe_audio(
    audio_bytes: bytes,
    *,
    content_type: str | None = None,
    language: str | None = "auto",
) -> TranscriptionResult:
    """Transcribe one short local utterance and delete the temporary audio immediately.

    The model is loaded lazily and cached in-process. The first invocation may download the
    configured model into Bunnelby's local model directory; subsequent inference is local.
    """
    if not stt_enabled():
        raise STTDisabledError("Local speech recognition is disabled.")
    if not isinstance(audio_bytes, (bytes, bytearray)) or not audio_bytes:
        raise STTAudioError("Audio payload is empty.")
    if len(audio_bytes) > stt_max_audio_bytes():
        raise STTAudioError("Audio payload is too large for a single Bunnelby utterance.")

    language_hint = _validate_language_hint(language)
    model = _load_model()
    temp_path: str | None = None

    try:
        suffix = _suffix_for_content_type(content_type)
        with tempfile.NamedTemporaryFile(prefix="bunnelby-stt-", suffix=suffix, delete=False) as handle:
            handle.write(bytes(audio_bytes))
            temp_path = handle.name

        try:
            segments, info = model.transcribe(
                temp_path,
                language=None if language_hint == "auto" else language_hint,
                task="transcribe",
                beam_size=stt_beam_size(),
                temperature=0.0,
                condition_on_previous_text=False,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 350},
                word_timestamps=False,
            )
            text = _normalize_text([str(segment.text) for segment in segments])
        except STTServiceError:
            raise
        except Exception as exc:
            logger.warning("Bunnelby STT inference failed: %s", exc)
            raise STTTranscriptionError("Local speech recognition failed for this audio.") from exc

        detected_language = str(getattr(info, "language", "") or language_hint or "auto")
        probability = float(getattr(info, "language_probability", 0.0) or 0.0)
        duration = float(getattr(info, "duration", 0.0) or 0.0)
        return TranscriptionResult(
            text=text,
            language=detected_language,
            language_probability=max(0.0, min(probability, 1.0)),
            duration_seconds=max(0.0, duration),
        )
    finally:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                logger.debug("Could not remove temporary STT audio file: %s", temp_path)


def _reset_model_cache_for_tests() -> None:
    global _model, _model_signature
    with _model_lock:
        _model = None
        _model_signature = None
