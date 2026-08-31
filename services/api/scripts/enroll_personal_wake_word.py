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
from services.api.app.utterance_capture import UtteranceCaptureError, capture_vad_utterance
from services.api.app.vad_service import create_voice_activity_detector, vad_settings


# Short, confusable phrases are intentional. A production wake detector must reject
# acoustically similar non-wake speech, not only long unrelated commands.
NEGATIVE_PROMPTS = (
    "Bunny",
    "Bundle",
    "Bumblebee",
    "Finally",
    "Probably",
    "Calendar",
    "Browser",
    "Music",
    "Email",
    "Meeting",
    "Open it",
    "Close it",
)

MIN_SHORT_PHRASE_SECONDS = 0.30
MAX_SHORT_PHRASE_SECONDS = 1.80
MAX_ATTEMPTS_PER_SAMPLE = 5


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


def _short_phrase_duration_is_suspicious(duration_seconds: float) -> bool:
    return not MIN_SHORT_PHRASE_SECONDS <= duration_seconds <= MAX_SHORT_PHRASE_SECONDS


def _capture_feature(
    stream,
    *,
    prompt: str,
    timeout_seconds: float,
) -> tuple[np.ndarray, float]:
    print(prompt)
    print("  Speak after the prompt, then stop speaking.")
    detector = create_voice_activity_detector()
    settings = vad_settings()
    segment = capture_vad_utterance(
        stream,
        detector,
        sample_rate=settings.sample_rate,
        window_size=settings.window_size,
        timeout_seconds=timeout_seconds,
        continuation_seconds=0.55,
        max_output_seconds=4.0,
    )
    duration = len(segment) / settings.sample_rate
    features = extract_acoustic_features(segment, sample_rate=settings.sample_rate)
    print(f"  Captured: {duration:.2f}s → {features.shape[0]} feature frames")
    del segment
    return features, duration


def _capture_confirmed_feature(
    sd,
    *,
    device_index: int,
    prompt: str,
    expected_text: str,
    timeout_seconds: float,
) -> np.ndarray:
    """Capture one short phrase with quality gating and explicit human confirmation.

    Each attempt owns a fresh microphone stream. This prevents audio spoken while the user
    is deciding whether to accept/re-record a sample from being queued into the next sample.
    Raw PCM never leaves memory and is discarded after feature extraction.
    """
    settings = vad_settings()
    for attempt in range(1, MAX_ATTEMPTS_PER_SAMPLE + 1):
        if attempt > 1:
            print(f"  Re-record attempt {attempt}/{MAX_ATTEMPTS_PER_SAMPLE}")

        with sd.InputStream(
            device=device_index,
            channels=1,
            dtype="float32",
            samplerate=settings.sample_rate,
            blocksize=settings.window_size,
        ) as mic:
            features, duration = _capture_feature(
                mic,
                prompt=prompt,
                timeout_seconds=timeout_seconds,
            )

        if _short_phrase_duration_is_suspicious(duration):
            print(
                f"  AUTO-REJECT: {duration:.2f}s is unusual for this short phrase. "
                "Wait for the prompt, say only the requested words once, then stop."
            )
            time.sleep(0.35)
            continue

        print(f'  Expected phrase: "{expected_text}"')
        while True:
            choice = input(
                "  Press ENTER if you said it correctly, R to re-record, or Q to cancel: "
            ).strip().casefold()
            if choice in ("", "a", "accept"):
                print("  Accepted.\n")
                return features
            if choice in ("r", "redo", "retry"):
                print("  Discarded — recording again.\n")
                break
            if choice in ("q", "quit", "cancel"):
                raise KeyboardInterrupt
            print("  Invalid choice. Use ENTER, R, or Q.")

        time.sleep(0.35)

    raise RuntimeError(
        "Too many failed/rejected recordings for one enrollment sample. "
        "Check microphone conditions and retry enrollment later."
    )


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
        print(
            "After every recording, confirm it. If you said the wrong word, press R and only "
            "that sample will be recorded again."
        )
        print()

        positives: list[np.ndarray] = []
        negatives: list[np.ndarray] = []

        for index in range(positive_count):
            positives.append(
                _capture_confirmed_feature(
                    sd,
                    device_index=device_index,
                    prompt=f"Positive {index + 1}/{positive_count}: say ONLY  Bunnelby",
                    expected_text="Bunnelby",
                    timeout_seconds=timeout_seconds,
                )
            )

        print()
        print("Now record SHORT NON-wake phrases for false-positive calibration.")
        print("These include intentionally similar words such as Bunny/Bundle/Bumblebee.")
        print()
        for index in range(negative_count):
            expected = NEGATIVE_PROMPTS[index]
            negatives.append(
                _capture_confirmed_feature(
                    sd,
                    device_index=device_index,
                    prompt=f'Negative {index + 1}/{negative_count}: say ONLY  "{expected}"',
                    expected_text=expected,
                    timeout_seconds=timeout_seconds,
                )
            )

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
    except (PersonalWakeWordError, UtteranceCaptureError, TimeoutError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("Enrollment failed closed; no new profile is trusted.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
