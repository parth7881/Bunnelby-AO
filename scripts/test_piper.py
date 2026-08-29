from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.api.app.tts_service import (  # noqa: E402
    resolve_voice_directory,
    synthesize_acknowledgment,
    synthesize_speech,
)
from services.api.app.acknowledgments import normalize_spoken_text  # noqa: E402

SMOKE_PHRASES = {
    "en": "AO voice systems online.",
    "hi": "ए ओ वॉइस सिस्टम तैयार है।",
}

AB_LENGTH_SCALES = {
    "en": (1.08, 1.11, 1.14),
    "hi": (1.09, 1.12, 1.15),
}

AB_PHRASES = {
    "en": (
        ("greeting", "Good evening, sir. Everything is running normally."),
        ("inbox", "I've checked your inbox. Two messages need your attention."),
        ("warning", "The connection failed, but your local services are still running."),
        ("technical", "RAG retrieves relevant information before generating an answer."),
    ),
    "hi": (
        ("greeting", "शुभ संध्या, सर। सभी सिस्टम सामान्य रूप से चल रहे हैं।"),
        ("inbox", "मैंने आपका इनबॉक्स देख लिया है। दो संदेश महत्वपूर्ण हैं।"),
        ("warning", "कनेक्शन में समस्या है, लेकिन आपके लोकल सिस्टम सामान्य हैं।"),
        ("technical", "RAG में एआई पहले संबंधित जानकारी ढूँढता है, फिर जवाब देता है।"),
    ),
}


def generate_ab_samples(output_dir: Path, languages: tuple[str, ...]) -> None:
    for language in languages:
        for phrase_index, (label, phrase) in enumerate(AB_PHRASES[language], start=1):
            for scale in AB_LENGTH_SCALES[language]:
                wav_bytes = synthesize_speech(
                    normalize_spoken_text(phrase, language),  # type: ignore[arg-type]
                    language,  # type: ignore[arg-type]
                    length_scale_override=scale,
                )
                output_path = output_dir / (
                    f"{language}_{phrase_index:02d}_{label}_scale-{scale:.2f}.wav"
                )
                output_path.write_bytes(wav_bytes)
                print(f"{language} {scale:.2f}: {output_path} ({len(wav_bytes)} bytes)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate AO Piper smoke or Phase 6.1 A/B WAV files.")
    parser.add_argument("--mode", choices=("smoke", "ab"), default="smoke")
    parser.add_argument("--language", choices=("en", "hi", "all"), default="all")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
    )
    args = parser.parse_args()

    languages = ("en", "hi") if args.language == "all" else (args.language,)
    output_dir = args.output_dir or Path(tempfile.gettempdir()) / (
        "AO-piper-phase6-1-ab" if args.mode == "ab" else "AO-piper-smoke"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Voice directory: {resolve_voice_directory()}")

    if args.mode == "ab":
        generate_ab_samples(output_dir, languages)
        return 0

    for language in languages:
        wav_bytes = synthesize_acknowledgment(SMOKE_PHRASES[language], language)
        output_path = output_dir / f"ao-piper-{language}.wav"
        output_path.write_bytes(wav_bytes)
        print(f"{language}: {output_path} ({len(wav_bytes)} bytes)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
