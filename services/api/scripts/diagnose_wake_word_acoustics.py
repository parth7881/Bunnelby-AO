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

from services.api.app.wake_word_service import validate_wake_word_model, wake_word_settings


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


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnostic only: decode microphone audio with the same GigaSpeech "
            "transducer used by Bunnelby's KWS model."
        )
    )
    parser.add_argument(
        "--device",
        default=os.getenv("BUNNELBY_MIC_DEVICE", ""),
        help="Optional microphone input index or unique case-insensitive name fragment.",
    )
    parser.add_argument("--seconds", type=float, default=10.0)
    args = parser.parse_args()

    duration = max(5.0, min(float(args.seconds), 30.0))

    try:
        import sounddevice as sd
        import sherpa_onnx

        paths = validate_wake_word_model()
        settings = wake_word_settings()
        recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(paths["tokens"]),
            encoder=str(paths["encoder"]),
            decoder=str(paths["decoder"]),
            joiner=str(paths["joiner"]),
            num_threads=1,
            sample_rate=settings.sample_rate,
            feature_dim=80,
            decoding_method="modified_beam_search",
            max_active_paths=8,
            provider="cpu",
        )

        device_index = _resolve_input_device(sd, args.device.strip() or None)
        device = sd.query_devices(device_index)
        print(f"Microphone: {device['name']}")
        print(
            'Acoustic diagnostic — say "Bunnelby" naturally 3 times, '
            "about 2 seconds apart."
        )
        print("This does NOT trigger Bunnelby or call /chat.")

        stream = recognizer.create_stream()
        sample_rate = settings.sample_rate
        samples_per_read = int(0.10 * sample_rate)
        deadline = time.monotonic() + duration
        last_result = ""

        with sd.InputStream(
            device=device_index,
            channels=1,
            dtype="float32",
            samplerate=sample_rate,
            blocksize=samples_per_read,
        ) as mic:
            while time.monotonic() < deadline:
                samples, overflowed = mic.read(samples_per_read)
                if overflowed:
                    print("Warning: microphone input overflowed once; continuing.")
                mono = np.asarray(samples, dtype=np.float32).reshape(-1)
                stream.accept_waveform(sample_rate, mono)
                while recognizer.is_ready(stream):
                    recognizer.decode_stream(stream)
                result = str(recognizer.get_result(stream) or "").strip()
                if result and result != last_result:
                    print(f"Partial: {result}")
                    last_result = result

        # Give the streaming transducer a small zero tail so final tokens can flush.
        tail = np.zeros(int(0.8 * sample_rate), dtype=np.float32)
        stream.accept_waveform(sample_rate, tail)
        stream.input_finished()
        while recognizer.is_ready(stream):
            recognizer.decode_stream(stream)
        final_result = str(recognizer.get_result(stream) or "").strip()

        print(f"Final acoustic decode: {final_result or '<EMPTY>'}")
        if not final_result:
            print(
                "DIAGNOSIS: This GigaSpeech model did not produce a usable textual "
                "hypothesis for the spoken wake word."
            )
            return 2

        print(
            "DIAGNOSIS: Use this decode to decide whether a phonetic/acoustic alias "
            "is viable for KWS."
        )
        return 0
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
