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

from services.api.app.personal_wake_word import (
    PersonalWakeWordError,
    PersonalWakeWordUnavailableError,
    evaluate_features,
    extract_acoustic_features,
    load_profile,
)
from services.api.app.vad_service import create_voice_activity_detector, vad_settings


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
            raise RuntimeError("Microphone name fragment must match exactly one input device.")
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Live microphone probe for Bunnelby's personalized wake-word detector."
    )
    parser.add_argument(
        "--device",
        default=os.getenv("BUNNELBY_MIC_DEVICE", ""),
        help="Optional microphone input index or unique case-insensitive name fragment.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args()
    timeout_seconds = max(5.0, min(float(args.timeout_seconds), 60.0))

    try:
        import sounddevice as sd

        profile = load_profile()
        settings = vad_settings()
        detector = create_voice_activity_detector()
        device_index = _resolve_input_device(sd, args.device.strip() or None)
        device = sd.query_devices(device_index)

        print(f"Microphone: {device['name']}")
        print("Personalized wake profile: loaded")
        print('Listening — say "Bunnelby" naturally. Normal speech should be rejected.')

        deadline = time.monotonic() + timeout_seconds
        started = time.monotonic()
        buffer = np.empty(0, dtype=np.float32)
        segment_index = 0

        with sd.InputStream(
            device=device_index,
            channels=1,
            dtype="float32",
            samplerate=settings.sample_rate,
            blocksize=settings.window_size,
        ) as mic:
            while time.monotonic() < deadline:
                samples, overflowed = mic.read(settings.window_size)
                if overflowed:
                    print("Warning: microphone input overflowed once; continuing.")
                buffer = np.concatenate(
                    (buffer, np.asarray(samples, dtype=np.float32).reshape(-1))
                )
                while len(buffer) >= settings.window_size:
                    detector.accept_waveform(buffer[: settings.window_size])
                    buffer = buffer[settings.window_size :]

                while not detector.empty():
                    segment = np.asarray(detector.front.samples, dtype=np.float32).copy()
                    detector.pop()
                    segment_index += 1
                    duration = len(segment) / settings.sample_rate
                    try:
                        features = extract_acoustic_features(
                            segment, sample_rate=settings.sample_rate
                        )
                        decision = evaluate_features(features, profile)
                    except PersonalWakeWordError as exc:
                        print(
                            f"Segment {segment_index}: ignored ({duration:.2f}s) — {exc}"
                        )
                        continue
                    finally:
                        del segment

                    print(
                        f"Segment {segment_index}: {duration:.2f}s "
                        f"positive={decision.positive_score:.5f} "
                        f"negative={decision.negative_score:.5f} "
                        f"threshold={decision.threshold:.5f} "
                        f"margin={decision.required_margin:.5f} "
                        f"=> {'WAKE' if decision.detected else 'reject'}"
                    )
                    if decision.detected:
                        print("Wake detected: Bunnelby")
                        print(f"Detection latency: {time.monotonic() - started:.2f}s")
                        return 0

        print(
            f'ERROR: Personalized wake word "Bunnelby" was not detected within '
            f"{timeout_seconds:.0f} seconds.",
            file=sys.stderr,
        )
        return 2
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130
    except (PersonalWakeWordUnavailableError, PersonalWakeWordError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
