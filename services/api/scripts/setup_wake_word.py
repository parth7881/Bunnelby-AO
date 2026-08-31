from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.api.app.wake_word_assets import WakeWordAssetError, install_wake_word_assets
from services.api.app.wake_word_service import create_keyword_spotter, validate_wake_word_model


def _require_sentencepiece() -> None:
    try:
        import sentencepiece  # noqa: F401
    except Exception as exc:
        raise RuntimeError(
            "SentencePiece is required for one-time BPE wake-word setup. "
            "Install the pinned backend requirements and rerun setup."
        ) from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install and verify Bunnelby's local sherpa-onnx wake-word model."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download and replace the verified model assets.",
    )
    args = parser.parse_args()

    try:
        _require_sentencepiece()
        root = install_wake_word_assets(force=args.force)
        paths = validate_wake_word_model(root)
        # Initialization is part of setup validation; setup is not successful unless the
        # installed ONNX model can actually be opened by the current sherpa-onnx runtime.
        create_keyword_spotter()
        keyword = paths["keywords"].read_text(encoding="utf-8").strip()
        print(f"Wake-word model ready: {root}")
        print(f"Keyword definition: {keyword}")
        print("Wake-word engine initialization: PASS")
        return 0
    except (WakeWordAssetError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
