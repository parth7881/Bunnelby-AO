from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class VADServiceError(RuntimeError):
    """Base exception for Bunnelby local voice-activity detection."""


class VADUnavailableError(VADServiceError):
    """Raised when sherpa-onnx or the Silero VAD model is unavailable."""


@dataclass(frozen=True)
class VADSettings:
    sample_rate: int = 16000
    window_size: int = 512
    threshold: float = 0.35
    min_silence_duration: float = 0.45
    min_speech_duration: float = 0.15
    max_speech_duration: float = 12.0
    buffer_size_seconds: float = 30.0


def _env_float(name: str, default: float, low: float, high: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(low, min(value, high))


def vad_settings() -> VADSettings:
    return VADSettings(
        threshold=_env_float("VAD_THRESHOLD", 0.35, 0.05, 0.95),
        min_silence_duration=_env_float("VAD_MIN_SILENCE_SECONDS", 0.45, 0.10, 2.0),
        min_speech_duration=_env_float("VAD_MIN_SPEECH_SECONDS", 0.15, 0.05, 2.0),
        max_speech_duration=_env_float("VAD_MAX_SPEECH_SECONDS", 12.0, 1.0, 30.0),
    )


def vad_model_path() -> Path:
    configured = os.getenv("VAD_MODEL_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()

    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    root = Path(local_app_data) if local_app_data else Path.home() / ".bunnelby"
    if local_app_data:
        return root / "Bunnelby" / "models" / "vad" / "silero_vad.onnx"
    return root / "models" / "vad" / "silero_vad.onnx"


def create_voice_activity_detector() -> Any:
    """Create a stateful Silero VAD detector backed by sherpa-onnx.

    The detector is intentionally created by the runtime/microphone owner instead of being a
    process-global singleton because VAD maintains stream state. No audio leaves the machine.
    """
    model_path = vad_model_path()
    if not model_path.is_file():
        raise VADUnavailableError(
            f"Silero VAD model is missing at {model_path}."
        )

    try:
        import sherpa_onnx
    except Exception as exc:
        raise VADUnavailableError(
            "sherpa-onnx is not available in the Bunnelby backend environment."
        ) from exc

    settings = vad_settings()
    try:
        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = str(model_path)
        config.silero_vad.threshold = settings.threshold
        config.silero_vad.min_silence_duration = settings.min_silence_duration
        config.silero_vad.min_speech_duration = settings.min_speech_duration
        config.silero_vad.max_speech_duration = settings.max_speech_duration
        config.silero_vad.window_size = settings.window_size
        config.sample_rate = settings.sample_rate
        return sherpa_onnx.VoiceActivityDetector(
            config,
            buffer_size_in_seconds=settings.buffer_size_seconds,
        )
    except Exception as exc:
        raise VADUnavailableError("Silero VAD could not be initialized.") from exc
