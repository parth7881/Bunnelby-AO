from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np

from services.api.app.wake_word_service import (
    WakeWordError,
    WakeWordUnavailableError,
    calibrated_wake_word_settings,
    create_keyword_spotter,
    detect_keyword_from_samples,
    wake_word_settings,
)


def _resolve_input_device(sd, requested: str | None):
    devices = sd.query_devices()
    if requested:
        if requested.isdigit():
            index = int(requested)
            if index < 0 or index >= len(devices):
                raise RuntimeError("Requested microphone device index is out of range.")
            if devices[index].get("max_input_channels", 0) <= 0:
                raise RuntimeError("Requested device is not a microphone input.")
            return index

        needle = requested.casefold()
        matches = [
            index
            for index, device in enumerate(devices)
            if device.get("max_input_channels", 0) > 0
            and needle in str(device.get("name", "")).casefold()
        ]
        if len(matches) != 1:
            raise RuntimeError(
                "Microphone name fragment must match exactly one input device."
            )
        return matches[0]

    default_input = sd.default.device[0]
    if isinstance(default_input, int) and default_input >= 0:
        return default_input

    for phrase in ("microphone array", "microphone"):
        for index, device in enumerate(devices):
            if device.get("max_input_channels", 0) > 0 and phrase in str(
                device.get("name", "")
            ).casefold():
                return index
    raise RuntimeError("No microphone input device found.")


def listen_for_wake_word(
    *,
    device_hint: str | None,
    timeout_seconds: float,
    score: float | None,
    threshold: float | None,
) -> tuple[str, float]:
    try:
        import sounddevice as sd
    except Exception as exc:
        raise RuntimeError("sounddevice is unavailable.") from exc

    base_settings = wake_word_settings()
    if (score is None) != (threshold is None):
        raise WakeWordError("Calibration requires both --score and --threshold together.")
    settings = (
        calibrated_wake_word_settings(score=score, threshold=threshold)
        if score is not None and threshold is not None
        else base_settings
    )
    spotter = create_keyword_spotter(settings=settings)
    stream = spotter.create_stream()
    device_index = _resolve_input_device(sd, device_hint)
    device = sd.query_devices(device_index)
    print(f"Microphone: {device['name']}")
    print(
        "Wake profile: "
        f"score={settings.keywords_score:.2f} "
        f"threshold={settings.keywords_threshold:.2f}"
    )
    print('Listening for wake word — say "Bunnelby"...')

    started = time.monotonic()
    deadline = started + timeout_seconds
    samples_per_read = int(0.10 * settings.sample_rate)

    try:
        with sd.InputStream(
            device=device_index,
            channels=1,
            dtype="float32",
            samplerate=settings.sample_rate,
            blocksize=samples_per_read,
        ) as mic:
            while time.monotonic() < deadline:
                samples, overflowed = mic.read(samples_per_read)
                if overflowed:
                    print("Warning: microphone input overflowed once; continuing.")
                mono = np.asarray(samples, dtype=np.float32).reshape(-1)
                detected = detect_keyword_from_samples(
                    spotter,
                    stream,
                    mono,
                    sample_rate=settings.sample_rate,
                )
                if detected:
                    return detected, time.monotonic() - started
    except Exception as exc:
        raise RuntimeError(f"Microphone/wake-word capture failed: {exc}") from exc

    raise TimeoutError(
        f'Wake word "Bunnelby" was not detected within {timeout_seconds:.0f} seconds.'
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Bunnelby live local wake-word probe")
    parser.add_argument(
        "--device",
        default=os.getenv("BUNNELBY_MIC_DEVICE", ""),
        help="Optional microphone input index or unique case-insensitive name fragment.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument(
        "--score",
        type=float,
        default=None,
        help="Optional bounded KWS calibration score; use with --threshold.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Optional bounded KWS calibration threshold; use with --score.",
    )
    args = parser.parse_args()

    timeout = max(5.0, min(float(args.timeout_seconds), 60.0))
    try:
        detected, latency = listen_for_wake_word(
            device_hint=args.device.strip() or None,
            timeout_seconds=timeout,
            score=args.score,
            threshold=args.threshold,
        )
        print(f"Wake detected: {detected}")
        print(f"Detection latency: {latency:.2f}s")
        return 0
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130
    except (WakeWordUnavailableError, WakeWordError, TimeoutError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
