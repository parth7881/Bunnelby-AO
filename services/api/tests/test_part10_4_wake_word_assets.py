from __future__ import annotations

import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services.api.app import wake_word_assets


class WakeWordAssetTests(unittest.TestCase):
    def _tar_bytes(self, files: dict[str, bytes]) -> bytes:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:bz2") as tar:
            for name, payload in files.items():
                info = tarfile.TarInfo(name=name)
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
        return buffer.getvalue()

    def _parse_verified_manifest(self, text: str) -> str:
        with patch.object(
            wake_word_assets,
            "_sha256",
            return_value=wake_word_assets.CHECKSUM_MANIFEST_SHA256,
        ):
            return wake_word_assets._parse_archive_sha256(text.encode("utf-8"))

    def test_unverified_checksum_manifest_fails_closed(self) -> None:
        with self.assertRaises(wake_word_assets.WakeWordAssetError):
            wake_word_assets._parse_archive_sha256(
                b"0" * 64 + b"  " + wake_word_assets.MODEL_ARCHIVE_NAME.encode() + b"\n"
            )

    def test_verified_sha256sum_manifest_variant_is_accepted(self) -> None:
        digest = "a" * 64
        result = self._parse_verified_manifest(
            f"{digest}  {wake_word_assets.MODEL_ARCHIVE_NAME}\n"
        )
        self.assertEqual(result, digest)

    def test_verified_path_prefixed_manifest_variant_is_accepted(self) -> None:
        digest = "b" * 64
        result = self._parse_verified_manifest(
            f"{digest}  ./release/{wake_word_assets.MODEL_ARCHIVE_NAME}\n"
        )
        self.assertEqual(result, digest)

    def test_verified_sha256_label_manifest_variant_is_accepted(self) -> None:
        digest = "c" * 64
        result = self._parse_verified_manifest(
            f"{wake_word_assets.MODEL_ARCHIVE_NAME}: sha256:{digest}\n"
        )
        self.assertEqual(result, digest)

    def test_duplicate_target_checksum_entries_are_rejected(self) -> None:
        digest = "d" * 64
        manifest = (
            f"{digest}  {wake_word_assets.MODEL_ARCHIVE_NAME}\n"
            f"{digest}  ./release/{wake_word_assets.MODEL_ARCHIVE_NAME}\n"
        )
        with (
            patch.object(
                wake_word_assets,
                "_sha256",
                return_value=wake_word_assets.CHECKSUM_MANIFEST_SHA256,
            ),
            self.assertRaises(wake_word_assets.WakeWordAssetError),
        ):
            wake_word_assets._parse_archive_sha256(manifest.encode("utf-8"))

    def test_ambiguous_digest_line_is_rejected(self) -> None:
        manifest = (
            f"{'e' * 64} {'f' * 64} {wake_word_assets.MODEL_ARCHIVE_NAME}\n"
        )
        with (
            patch.object(
                wake_word_assets,
                "_sha256",
                return_value=wake_word_assets.CHECKSUM_MANIFEST_SHA256,
            ),
            self.assertRaises(wake_word_assets.WakeWordAssetError),
        ):
            wake_word_assets._parse_archive_sha256(manifest.encode("utf-8"))

    def test_archive_path_traversal_is_rejected(self) -> None:
        archive = self._tar_bytes({"../tokens.txt": b"fixture"})
        with self.assertRaises(wake_word_assets.WakeWordAssetError):
            wake_word_assets._extract_required_files(archive)

    def test_archive_symlink_is_rejected(self) -> None:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:bz2") as tar:
            info = tarfile.TarInfo(name="model/tokens.txt")
            info.type = tarfile.SYMTYPE
            info.linkname = "../../outside"
            tar.addfile(info)
        with self.assertRaises(wake_word_assets.WakeWordAssetError):
            wake_word_assets._extract_required_files(buffer.getvalue())

    def test_bunnelby_keyword_generation_uses_documented_bpe_format(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_text2token(texts, **kwargs):
            calls.append({"texts": texts, **kwargs})
            return [["▁BUN", "NEL", "BY"]]

        fake_module = SimpleNamespace(text2token=fake_text2token)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tokens = root / "tokens.txt"
            bpe = root / "bpe.model"
            tokens.write_text("fixture", encoding="utf-8")
            bpe.write_bytes(b"fixture")
            with patch.dict("sys.modules", {"sherpa_onnx": fake_module}):
                payload = wake_word_assets._build_bunnelby_keyword(tokens, bpe)

        self.assertEqual(payload.decode("utf-8"), "▁BUN NEL BY\n")
        self.assertEqual(calls[0]["texts"], ["BUNNELBY"])
        self.assertEqual(calls[0]["tokens_type"], "bpe")
        self.assertEqual(calls[0]["lexicon"], "")

    def test_empty_keyword_tokenization_fails_closed(self) -> None:
        fake_module = SimpleNamespace(text2token=lambda *_args, **_kwargs: [[]])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tokens = root / "tokens.txt"
            bpe = root / "bpe.model"
            tokens.write_text("fixture", encoding="utf-8")
            bpe.write_bytes(b"fixture")
            with (
                patch.dict("sys.modules", {"sherpa_onnx": fake_module}),
                self.assertRaises(wake_word_assets.WakeWordAssetError),
            ):
                wake_word_assets._build_bunnelby_keyword(tokens, bpe)

    def test_runtime_assets_check_requires_all_files(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in wake_word_assets._REQUIRED_ARCHIVE_FILES:
                (root / name).write_bytes(b"x")
            self.assertFalse(wake_word_assets.wake_word_assets_present(root))
            (root / "bunnelby.keywords.txt").write_text(
                "▁BUN NEL BY\n", encoding="utf-8"
            )
            self.assertTrue(wake_word_assets.wake_word_assets_present(root))


if __name__ == "__main__":
    unittest.main()
