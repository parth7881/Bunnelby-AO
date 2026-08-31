from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class WakeWordError(RuntimeError):
    """Base exception for Bunnelby's local wake-word subsystem."""


class WakeWordUnavailableError(WakeWordError):
    """Raised when the wake-word model/configuration is unavailable or invalid."""


@dataclass(frozen=True)
class WakeWordSettings:
    sample_rate: int = 16000
    num_threads: int = 1
    max_active_paths: int = 4
    num_trailing_blanks: int = 1
    keywords_score: float = 1.5
    keywords_threshold: float = 0.25
    provider: str = "cpu"


def _env_float(name: str, default: float, low: float, high: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(low, min(value, high))


def _env_int(name: str, default: int, low: int, high: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(low, min(value, high))


def wake_word_settings() -> WakeWordSettings:
    return WakeWordSettings(
        num_threads=_env_int("WAKE_WORD_THREADS", 1, 1, 4),
        max_active_paths=_env_int("WAKE_WORD_MAX_ACTIVE_PATHS", 4, 1, 16),
        num_trailing_blanks=_env_int("WAKE_WORD_TRAILING_BLANKS", 1, 0, 16),
        keywords_score=_env_float("WAKE_WORD_SCORE", 1.5, 0.1, 10.0),
        keywords_threshold=_env_float("WAKE_WORD_THRESHOLD", 0.25, 0.01, 0.99),
    )


def wake_word_model_dir() -> Path:
    configured = os.getenv("WAKE_WORD_MODEL_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()

    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    root = Path(local_app_data) if local_app_data else Path.home() / ".bunnelby"
    if local_app_data:
        return root / "Bunnelby" / "models" / "wakeword" / "gigaspeech-kws-mobile"
    return root / "models" / "wakeword" / "gigaspeech-kws-mobile"


def _required_paths(model_dir: Path) -> dict[str, Path]:
    return {
        "tokens": model_dir / "tokens.txt",
        "encoder": model_dir / "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
        "decoder": model_dir / "decoder-epoch-12-avg-2-chunk-16-left-64.onnx",
        "joiner": model_dir / "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
        "keywords": model_dir / "bunnelby.keywords.txt",
    }


def validate_wake_word_model(model_dir: Path | None = None) -> dict[str, Path]:
    resolved = model_dir or wake_word_model_dir()
    if not resolved.is_dir():
        raise WakeWordUnavailableError(f"Wake-word model directory is missing at {resolved}.")

    paths = _required_paths(resolved)
    missing = [name for name, path in paths.items() if not path.is_file() or path.stat().st_size <= 0]
    if missing:
        raise WakeWordUnavailableError(
            "Wake-word model is incomplete; missing/empty files: " + ", ".join(sorted(missing))
        )

    keyword_text = paths["keywords"].read_text(encoding="utf-8").strip()
    if not keyword_text:
        raise WakeWordUnavailableError("Wake-word keyword file is empty.")
    if len(keyword_text) > 4096:
        raise WakeWordUnavailableError("Wake-word keyword file is unexpectedly large.")

    return paths


def create_keyword_spotter() -> Any:
    """Create Bunnelby's local streaming keyword spotter.

    The runtime is intentionally CPU-only and local. The model is never downloaded from this
    function; installation/bootstrap is an explicit setup operation so an always-on microphone
    process cannot unexpectedly access the network.
    """
    paths = validate_wake_word_model()

    try:
        import sherpa_onnx
    except Exception as exc:
        raise WakeWordUnavailableError(
            "sherpa-onnx is not available in the Bunnelby backend environment."
        ) from exc

    settings = wake_word_settings()
    try:
        return sherpa_onnx.KeywordSpotter(
            tokens=str(paths["tokens"]),
            encoder=str(paths["encoder"]),
            decoder=str(paths["decoder"]),
            joiner=str(paths["joiner"]),
            num_threads=settings.num_threads,
            max_active_paths=settings.max_active_paths,
            num_trailing_blanks=settings.num_trailing_blanks,
            keywords_file=str(paths["keywords"]),
            keywords_score=settings.keywords_score,
            keywords_threshold=settings.keywords_threshold,
            provider=settings.provider,
        )
    except Exception as exc:
        raise WakeWordUnavailableError("Wake-word model could not be initialized.") from exc


def detect_keyword_from_samples(
    keyword_spotter: Any,
    stream: Any,
    samples: Any,
    *,
    sample_rate: int = 16000,
) -> str:
    """Feed one PCM float chunk and return a detected keyword, or an empty string.

    Callers own the microphone and stream lifecycle. The stream is reset immediately after a
    detection so one spoken wake phrase cannot repeatedly trigger the same activation.
    """
    if sample_rate != wake_word_settings().sample_rate:
        raise WakeWordError("Wake-word audio must be 16 kHz mono PCM float samples.")

    stream.accept_waveform(sample_rate, samples)
    detected = ""
    while keyword_spotter.is_ready(stream):
        keyword_spotter.decode_stream(stream)
        result = str(keyword_spotter.get_result(stream) or "").strip()
        if result:
            detected = result
            keyword_spotter.reset_stream(stream)
            break
    return detected
