from __future__ import annotations

import argparse
import hashlib
import io
import os
import sys
import tempfile
import time
import wave
from pathlib import Path

# When this file is launched directly (python services/api/scripts/...), Python puts only
# the script directory on sys.path. Add the repository root so `services.api...` imports
# work consistently from the documented repo-root command.
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np

from services.api.app.secure_http import SecureHTTPError, request_https
from services.api.app.stt_service import transcribe_audio
from services.api.app.vad_service import create_voice_activity_detector, vad_model_path, vad_settings

SILERO_VAD_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"
)
SILERO_VAD_ALLOWED_HOSTS = frozenset({"github.com", "release-assets.githubusercontent.com"})
SILERO_VAD_SHA256 = "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6"
SILERO_VAD_SIZE_BYTES = 643_854
SILERO_VAD_MAX_BYTES = 1024 * 1024


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _vad_model_is_verified(path: Path) -> bool:
    try:
        return (
            path.is_file()
            and path.stat().st_size == SILERO_VAD_SIZE_BYTES
            and _sha256_file(path) == SILERO_VAD_SHA256
        )
    except OSError:
        return False


def _download_verified_vad_model() -> bytes:
    try:
        response = request_https(
            SILERO_VAD_URL,
            allowed_hosts=SILERO_VAD_ALLOWED_HOSTS,
            method="GET",
            headers={"Accept": "application/octet-stream", "User-Agent": "Bunnelby-Desktop/1.0"},
            timeout_seconds=60,
            max_response_bytes=SILERO_VAD_MAX_BYTES,
            max_redirects=2,
        )
    except SecureHTTPError as exc:
        raise RuntimeError("Unable to securely obtain the Silero VAD model.") from exc

    if response.status < 200 or response.status >= 300:
        raise RuntimeError("Unable to securely obtain the Silero VAD model.")
    if len(response.body) != SILERO_VAD_SIZE_BYTES:
        raise RuntimeError("Downloaded Silero VAD model size did not match the trusted release asset.")
    if _sha256_bytes(response.body) != SILERO_VAD_SHA256:
        raise RuntimeError("Downloaded Silero VAD model failed integrity verification.")
    return response.body


def _atomic_write_verified_model(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

        if not _vad_model_is_verified(temp_path):
            raise RuntimeError("Verified VAD model could not be written safely.")
        os.replace(temp_path, target)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def ensure_vad_model() -> Path:
    target = vad_model_path()
    if _vad_model_is_verified(target):
        return target

    print(f"Downloading and verifying Silero VAD model once to: {target}")
    data = _download_verified_vad_model()
    _atomic_write_verified_model(target, data)
    if not _vad_model_is_verified(target):
        raise RuntimeError("Silero VAD model integrity check failed after installation.")
    return target


def float_samples_to_wav(samples: np.ndarray, sample_rate: int) -> bytes:
    mono = np.asarray(samples, dtype=np.float32).reshape(-1)
    mono = np.clip(mono, -1.0, 1.0)
    pcm = (mono * 32767.0).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())
    return buffer.getvalue()


def _resolve_input_device(sd, requested: str | None):
    devices = sd.query_devices()
    if requested:
        if requested.isdigit():
            return int(requested)
        needle = requested.casefold()
        for index, device in enumerate(devices):
            if device.get("max_input_channels", 0) > 0 and needle in str(device.get("name", "")).casefold():
                return index
        raise RuntimeError(f"No input device matched: {requested}")

    default_input = sd.default.device[0]
    if isinstance(default_input, int) and default_input >= 0:
        return default_input

    preferred = ("microphone array", "microphone")
    for phrase in preferred:
        for index, device in enumerate(devices):
            if device.get("max_input_channels", 0) > 0 and phrase in str(device.get("name", "")).casefold():
                return index
    raise RuntimeError("No microphone input device found.")


def capture_one_utterance(*, device_hint: str | None, wait_seconds: float) -> np.ndarray:
    try:
        import sounddevice as sd
    except Exception as exc:
        raise RuntimeError("sounddevice is unavailable.") from exc

    ensure_vad_model()
    detector = create_voice_activity_detector()
    settings = vad_settings()
    device_index = _resolve_input_device(sd, device_hint)
    device = sd.query_devices(device_index)
    print(f"Microphone: {device['name']}")
    print("Listening — speak one command, then stop speaking...")

    deadline = time.monotonic() + wait_seconds
    buffer = np.empty(0, dtype=np.float32)

    try:
        with sd.InputStream(
            device=device_index,
            channels=1,
            dtype="float32",
            samplerate=settings.sample_rate,
            blocksize=settings.window_size,
        ) as stream:
            while time.monotonic() < deadline:
                samples, overflowed = stream.read(settings.window_size)
                if overflowed:
                    print("Warning: microphone input overflowed once; continuing.")
                buffer = np.concatenate((buffer, samples.reshape(-1)))
                while len(buffer) >= settings.window_size:
                    detector.accept_waveform(buffer[: settings.window_size])
                    buffer = buffer[settings.window_size :]
                if not detector.empty():
                    segment = np.asarray(detector.front.samples, dtype=np.float32).copy()
                    detector.pop()
                    return segment
    except Exception as exc:
        raise RuntimeError(f"Microphone/VAD capture failed: {exc}") from exc

    raise TimeoutError(f"No completed speech segment detected within {wait_seconds:.0f} seconds.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Bunnelby live VAD → local Whisper STT probe")
    parser.add_argument(
        "--device",
        default=os.getenv("BUNNELBY_MIC_DEVICE", ""),
        help="Optional microphone device index or case-insensitive name fragment.",
    )
    parser.add_argument("--language", choices=("auto", "en", "hi"), default="auto")
    parser.add_argument("--wait-seconds", type=float, default=20.0)
    args = parser.parse_args()

    started = time.perf_counter()
    try:
        samples = capture_one_utterance(
            device_hint=args.device.strip() or None,
            wait_seconds=max(5.0, min(args.wait_seconds, 60.0)),
        )
        capture_seconds = len(samples) / vad_settings().sample_rate
        print(f"Speech segment: {capture_seconds:.2f}s")

        wav_bytes = float_samples_to_wav(samples, vad_settings().sample_rate)
        stt_started = time.perf_counter()
        result = transcribe_audio(
            wav_bytes,
            content_type="audio/wav",
            language=args.language,
        )
        stt_seconds = time.perf_counter() - stt_started
        print(f"Transcript: {result.text}")
        print(
            "STT: "
            f"language={result.language} confidence={result.language_probability:.3f} "
            f"latency={stt_seconds:.2f}s total={time.perf_counter() - started:.2f}s"
        )
        return 0 if result.text else 2
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
