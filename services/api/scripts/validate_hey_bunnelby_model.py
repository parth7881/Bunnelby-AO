from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MODEL_NAME = "hey_bunnelby.onnx"
MAX_MODEL_BYTES = 8 * 1024 * 1024
MIN_MODEL_BYTES = 16 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_target() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if local_app_data:
        return (
            Path(local_app_data)
            / "Bunnelby"
            / "models"
            / "wakeword"
            / "neural"
            / MODEL_NAME
        )
    return (
        Path.home()
        / ".bunnelby"
        / "models"
        / "wakeword"
        / "neural"
        / MODEL_NAME
    )


def _validate_onnx(path: Path) -> tuple[str, tuple[int | str | None, ...], tuple[int | str | None, ...]]:
    if not path.is_file():
        raise RuntimeError(f"Model file does not exist: {path}")
    size = path.stat().st_size
    if not MIN_MODEL_BYTES <= size <= MAX_MODEL_BYTES:
        raise RuntimeError(
            f"Model size {size} bytes is outside the accepted range "
            f"({MIN_MODEL_BYTES}-{MAX_MODEL_BYTES})."
        )

    try:
        import onnxruntime as ort
    except Exception as exc:
        raise RuntimeError("onnxruntime is unavailable in the backend environment.") from exc

    options = ort.SessionOptions()
    options.inter_op_num_threads = 1
    options.intra_op_num_threads = 1
    options.enable_mem_pattern = True

    try:
        session = ort.InferenceSession(
            str(path),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
    except Exception as exc:
        raise RuntimeError("ONNX Runtime could not load the wake-word model.") from exc

    providers = session.get_providers()
    if providers != ["CPUExecutionProvider"]:
        raise RuntimeError(
            "Wake-word model validator requires CPUExecutionProvider only; "
            f"got {providers}."
        )

    inputs = session.get_inputs()
    outputs = session.get_outputs()
    if len(inputs) != 1 or len(outputs) != 1:
        raise RuntimeError(
            "Wake-word classifier must expose exactly one input and one output tensor."
        )

    input_meta = inputs[0]
    output_meta = outputs[0]
    if input_meta.type != "tensor(float)":
        raise RuntimeError(
            f"Wake-word classifier input must be tensor(float), got {input_meta.type}."
        )
    if output_meta.type != "tensor(float)":
        raise RuntimeError(
            f"Wake-word classifier output must be tensor(float), got {output_meta.type}."
        )

    input_shape = tuple(input_meta.shape)
    output_shape = tuple(output_meta.shape)
    if len(input_shape) != 3:
        raise RuntimeError(
            f"Expected a 3-D openWakeWord embedding input, got shape {input_shape}."
        )
    if input_shape[-1] not in (96, "96"):
        raise RuntimeError(
            f"Expected openWakeWord embedding dimension 96, got shape {input_shape}."
        )
    if len(output_shape) not in (1, 2):
        raise RuntimeError(
            f"Unexpected wake-word classifier output shape: {output_shape}."
        )
    last_output = output_shape[-1] if output_shape else None
    if last_output not in (1, "1"):
        raise RuntimeError(
            f"Wake-word classifier must emit one probability, got shape {output_shape}."
        )

    return _sha256(path), input_shape, output_shape


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and optionally install a trained Hey Bunnelby ONNX model."
    )
    parser.add_argument("model", type=Path, help="Path to trained hey_bunnelby.onnx")
    parser.add_argument(
        "--install",
        action="store_true",
        help="Copy the validated model into Bunnelby's local neural wake-word directory.",
    )
    args = parser.parse_args()

    source = args.model.expanduser().resolve(strict=False)
    try:
        digest, input_shape, output_shape = _validate_onnx(source)
        print("Hey Bunnelby model validation: PASS")
        print(f"SHA-256: {digest}")
        print(f"Input shape: {input_shape}")
        print(f"Output shape: {output_shape}")
        print("Provider: CPUExecutionProvider")

        if args.install:
            target = _default_target()
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + f".{os.getpid()}.tmp")
            try:
                shutil.copyfile(source, temp)
                if _sha256(temp) != digest:
                    raise RuntimeError("Copied wake-word model failed post-copy integrity check.")
                os.replace(temp, target)
            finally:
                temp.unlink(missing_ok=True)
            digest_path = target.with_suffix(target.suffix + ".sha256")
            digest_path.write_text(digest + "\n", encoding="ascii")
            print(f"Installed: {target}")
            print(f"Integrity metadata: {digest_path}")

        return 0
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("Model rejected; nothing was trusted.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
