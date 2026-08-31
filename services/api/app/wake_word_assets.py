from __future__ import annotations

import hashlib
import io
import os
import tarfile
from pathlib import Path, PurePosixPath
from typing import Final

from services.api.app.secure_http import SecureHTTPError, request_https
from services.api.app.wake_word_service import wake_word_model_dir


class WakeWordAssetError(RuntimeError):
    """Raised when trusted wake-word assets cannot be installed safely."""


MODEL_ARCHIVE_NAME: Final[str] = (
    "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01.tar.bz2"
)
MODEL_URL: Final[str] = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/"
    + MODEL_ARCHIVE_NAME
)
CHECKSUM_URL: Final[str] = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/checksum.txt"
)
# SHA-256 exposed by GitHub for the official checksum.txt release asset.
CHECKSUM_MANIFEST_SHA256: Final[str] = (
    "284637b2b9fec1287aca10315dcc960710c6ec14224fb1dfa9fe427e77eb6c18"
)
ALLOWED_DOWNLOAD_HOSTS: Final[frozenset[str]] = frozenset(
    {"github.com", "release-assets.githubusercontent.com"}
)
MAX_CHECKSUM_BYTES: Final[int] = 16 * 1024
MAX_ARCHIVE_BYTES: Final[int] = 20 * 1024 * 1024
MAX_UNPACKED_BYTES: Final[int] = 64 * 1024 * 1024
MAX_TAR_MEMBERS: Final[int] = 512
WAKE_LABEL: Final[str] = "BUNNELBY"

_REQUIRED_ARCHIVE_FILES: Final[dict[str, int]] = {
    "tokens.txt": 64 * 1024,
    "bpe.model": 1024 * 1024,
    "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx": 8 * 1024 * 1024,
    "decoder-epoch-12-avg-2-chunk-16-left-64.onnx": 2 * 1024 * 1024,
    "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx": 1024 * 1024,
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fetch_official_asset(url: str, *, max_bytes: int) -> bytes:
    try:
        response = request_https(
            url,
            allowed_hosts=ALLOWED_DOWNLOAD_HOSTS,
            method="GET",
            timeout_seconds=60.0,
            max_response_bytes=max_bytes,
            max_redirects=2,
        )
    except SecureHTTPError as exc:
        raise WakeWordAssetError("Secure wake-word asset download failed.") from exc

    if response.status < 200 or response.status >= 300:
        raise WakeWordAssetError(
            f"Wake-word asset server returned HTTP {response.status}."
        )
    return response.body


def _parse_archive_sha256(manifest: bytes) -> str:
    if _sha256(manifest) != CHECKSUM_MANIFEST_SHA256:
        raise WakeWordAssetError("Official wake-word checksum manifest failed integrity verification.")

    try:
        text = manifest.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WakeWordAssetError("Wake-word checksum manifest is not valid UTF-8.") from exc

    matches: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        digest = parts[0].casefold()
        filename = parts[-1].lstrip("*")
        if filename != MODEL_ARCHIVE_NAME:
            continue
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise WakeWordAssetError("Official wake-word archive checksum is malformed.")
        matches.append(digest)

    if len(matches) != 1:
        raise WakeWordAssetError("Official checksum manifest does not uniquely identify the wake-word model.")
    return matches[0]


def _validate_tar_member(member: tarfile.TarInfo) -> None:
    normalized_name = member.name.replace("\\", "/")
    path = PurePosixPath(normalized_name)
    if not normalized_name or path.is_absolute() or ".." in path.parts:
        raise WakeWordAssetError("Wake-word archive contains an unsafe path.")
    if member.issym() or member.islnk() or member.isdev() or member.isfifo():
        raise WakeWordAssetError("Wake-word archive contains a forbidden special file.")
    if not (member.isdir() or member.isreg()):
        raise WakeWordAssetError("Wake-word archive contains an unsupported member type.")
    if member.size < 0:
        raise WakeWordAssetError("Wake-word archive contains an invalid member size.")


def _extract_required_files(archive: bytes) -> dict[str, bytes]:
    try:
        tar = tarfile.open(fileobj=io.BytesIO(archive), mode="r:bz2")
    except (tarfile.TarError, OSError) as exc:
        raise WakeWordAssetError("Wake-word model archive is invalid.") from exc

    selected: dict[str, bytes] = {}
    total_unpacked = 0
    try:
        members = tar.getmembers()
        if len(members) > MAX_TAR_MEMBERS:
            raise WakeWordAssetError("Wake-word archive contains too many members.")

        for member in members:
            _validate_tar_member(member)
            if member.isreg():
                total_unpacked += member.size
                if total_unpacked > MAX_UNPACKED_BYTES:
                    raise WakeWordAssetError("Wake-word archive expands beyond the allowed size.")

                basename = PurePosixPath(member.name.replace("\\", "/")).name
                limit = _REQUIRED_ARCHIVE_FILES.get(basename)
                if limit is None:
                    continue
                if basename in selected:
                    raise WakeWordAssetError(
                        f"Wake-word archive contains duplicate required file: {basename}."
                    )
                if member.size <= 0 or member.size > limit:
                    raise WakeWordAssetError(
                        f"Wake-word model file has an invalid size: {basename}."
                    )
                source = tar.extractfile(member)
                if source is None:
                    raise WakeWordAssetError(
                        f"Wake-word model file could not be read: {basename}."
                    )
                payload = source.read(limit + 1)
                if len(payload) != member.size or len(payload) > limit:
                    raise WakeWordAssetError(
                        f"Wake-word model file failed bounded extraction: {basename}."
                    )
                selected[basename] = payload
    finally:
        tar.close()

    missing = sorted(set(_REQUIRED_ARCHIVE_FILES) - set(selected))
    if missing:
        raise WakeWordAssetError(
            "Wake-word archive is missing required model files: " + ", ".join(missing)
        )
    return selected


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        with temp.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _build_bunnelby_keyword(tokens_path: Path, bpe_path: Path) -> bytes:
    try:
        import sherpa_onnx
    except Exception as exc:
        raise WakeWordAssetError(
            "sherpa-onnx is unavailable; cannot generate Bunnelby keyword tokens."
        ) from exc

    try:
        encoded = sherpa_onnx.text2token(
            [WAKE_LABEL],
            tokens=str(tokens_path),
            tokens_type="bpe",
            bpe_model=str(bpe_path),
            lexicon="",
        )
    except Exception as exc:
        raise WakeWordAssetError("Bunnelby wake phrase could not be tokenized.") from exc

    if not isinstance(encoded, list) or len(encoded) != 1 or not encoded[0]:
        raise WakeWordAssetError("Bunnelby wake phrase produced no keyword tokens.")
    pieces = [str(piece).strip() for piece in encoded[0] if str(piece).strip()]
    if not pieces or len(pieces) > 32:
        raise WakeWordAssetError("Bunnelby wake phrase produced an invalid token sequence.")
    if any("\n" in piece or "\r" in piece or len(piece) > 64 for piece in pieces):
        raise WakeWordAssetError("Bunnelby wake phrase produced unsafe keyword tokens.")

    # For English BPE KWS, sherpa-onnx expects only the encoded token sequence.
    # Original-word metadata prefixed with '@' is required by phonetic/pinyin modes,
    # not by the BPE model used for Bunnelby.
    line = " ".join(pieces) + "\n"
    payload = line.encode("utf-8")
    if len(payload) > 4096:
        raise WakeWordAssetError("Bunnelby keyword definition is unexpectedly large.")
    return payload


def wake_word_assets_present(target: Path | None = None) -> bool:
    root = (target or wake_word_model_dir()).expanduser()
    required = set(_REQUIRED_ARCHIVE_FILES) | {"bunnelby.keywords.txt"}
    return root.is_dir() and all(
        (root / name).is_file() and (root / name).stat().st_size > 0 for name in required
    )


def install_wake_word_assets(*, target: Path | None = None, force: bool = False) -> Path:
    """Install the official KWS model and a locally generated Bunnelby keyword definition.

    Network access occurs only in this explicit setup function. The always-on wake runtime never
    downloads assets. The release checksum manifest is itself pinned by SHA-256, the model archive
    is verified against that manifest, and only a narrow allow-list of regular files is extracted.
    """
    root = (target or wake_word_model_dir()).expanduser().resolve(strict=False)
    if wake_word_assets_present(root) and not force:
        return root

    manifest = _fetch_official_asset(CHECKSUM_URL, max_bytes=MAX_CHECKSUM_BYTES)
    expected_archive_sha256 = _parse_archive_sha256(manifest)

    archive = _fetch_official_asset(MODEL_URL, max_bytes=MAX_ARCHIVE_BYTES)
    if _sha256(archive) != expected_archive_sha256:
        raise WakeWordAssetError("Wake-word model archive failed SHA-256 verification.")

    files = _extract_required_files(archive)
    root.mkdir(parents=True, exist_ok=True)
    for name, payload in files.items():
        _atomic_write(root / name, payload)

    keyword_payload = _build_bunnelby_keyword(root / "tokens.txt", root / "bpe.model")
    _atomic_write(root / "bunnelby.keywords.txt", keyword_payload)
    _atomic_write(root / "source.sha256", (expected_archive_sha256 + "\n").encode("ascii"))
    return root
