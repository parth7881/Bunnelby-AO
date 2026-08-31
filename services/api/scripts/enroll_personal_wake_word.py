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
    calibrate_profile,
    extract_acoustic_features,
    save_profile,
)
from services.api.app.vad_service import create_voice_activity_detector, vad_settings


NEGATIVE_PROMPTS = (
    "What is on my calendar today?",
    "Open the browser.",
    "Check my latest email.",
    "What time is my next meeting?",
    "Play some music.",
    "Search my files.",
    "Tell me the weather.",
    "Open Visual Studio Code.",
    "What did I work on yesterday?",
    "Read my notifications.",
    "I am free this evening.",
    "Close this window.",
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


def _capture_segment(sd, stream, detector, settings, *, timeout_seconds: float) -> np.ndarray:
    deadline = time.monotonic() + timeout_seconds
    buffer = np.empty(0, dtype=np.float32)
    while time.monotonic() < deadline:
        samples, overflowed = stream.read(settings.window_size)
        if overflowed:
            print("Warning: microphone input overflowed once; continuing.")
        buffer = np.concatenate((buffer, np.asarray(samples, dtype=np.float32).reshape(-1)))
        while len(buffer) >= settings.window_size:
            detector.accept_waveform(buffer[: settings.window_size])
            buffer = buffer[settings.window_size :]
        if not detector.empty():
            segment = np.asarray(detector.front.samples, dtype=np.float32).copy()
            detector.pop()
            return segment
    raise TimeoutError("No completed speech segment detected before timeout.")


def _capture_feature(
    sd,
    stream,
    *,
    prompt: str,
    timeout_seconds: float,
) -> np.ndarray:
    print(prompt)
    print("  Speak after the prompt, then stop speaking.")
    detector = create_voice_activity_detector()
    settings = vad_settings()
    segment = _capture_segment(
        sd,
        stream,
        detector,
        settings,
        timeout_seconds=timeout_seconds,
    )
    duration = len(segment) / settings.sample_rate
    features = extract_acoustic_features(segment, sample_rate=settings.sample_rate)
    print(f"  Captured: {duration:.2f}s → {features.shape[0]} feature frames")
    # Raw audio is not written to disk and is released after feature extraction.
    del segment
    return features


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enroll a local personalized wake-word profile for Bunnelby."
    )
    parser.add_argument(
        "--device",
        default=os.getenv("BUNNELBY_MIC_DEVICE", ""),
        help="Optional microphone input index or unique case-insensitive name fragment.",
    )
    parser.add_argument("--positive-count", type=int, default=10)
    parser.add_argument("--negative-count", type=int, default=12)
    parser.add_argument("--timeout-seconds", type=float, default=12.0)
    args = parser.parse_args()

    positive_count = max(6, min(int(args.positive_count), 20))
    negative_count = max(8, min(int(args.negative_count), len(NEGATIVE_PROMPTS)))
    timeout_seconds = max(5.0, min(float(args.timeout_seconds), 30.0))

    try:
        import sounddevice as sd

        settings = vad_settings()
        device_index = _resolve_input_device(sd, args.device.strip() or None)
        device = sd.query_devices(device_index)
        print(f"Microphone: {device['name']}")
        print()
        print("BUNNELBY PERSONAL WAKE-WORD ENROLLMENT")
        print("Raw enrollment audio will NOT be saved to disk.")
        print(
            "Use your normal everyday voice and laptop distance. Vary speed and tone slightly "
            "between positive samples."
        )
        print()

        positives: list[np.ndarray] = []
        negatives: list[np.ndarray] = []
        with sd.InputStream(
            device=device_index,
            channels=1,
            dtype="float32",
            samplerate=settings.sample_rate,
            blocksize=settings.window_size,
        ) as mic:
            for index in range(positive_count):
                positives.append(
                    _capture_feature(
                        sd,
                        mic,
                        prompt=f"Positive {index + 1}/{positive_count}: say ONLY  Bunnelby",
                        timeout_seconds=timeout_seconds,
                    )
                )
                time.sleep(0.25)

            print()
            print("Now record normal NON-wake speech for false-positive calibration.")
            print()
            for index in range(negative_count):
                negatives.append(
                    _capture_feature(
                        sd,
                        mic,
                        prompt=(
                            f'Negative {index + 1}/{negative_count}: say  "{NEGATIVE_PROMPTS[index]}"'
                        ),
                        timeout_seconds=timeout_seconds,
                    )
                )
                time.sleep(0.25)

        profile = calibrate_profile(positives, negatives)
        target = save_profile(profile)
        print()
        print(f"Personal wake-word profile ready: {target}")
        print(f"Positive threshold: {profile.positive_threshold:.5f}")
        print(f"Separation margin: {profile.separation_margin:.5f}")
        print("Enrollment: PASS")
        return 0
    except KeyboardInterrupt:
        print("\nCancelled. No profile was saved.")
        return 130
    except (PersonalWakeWordError, TimeoutError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("Enrollment failed closed; no new profile is trusted.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
