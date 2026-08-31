from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services.api.app import wake_word_service


class WakeWordServiceTests(unittest.TestCase):
    def _write_model_fixture(self, root: Path) -> None:
        for name in (
            "tokens.txt",
            "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
            "decoder-epoch-12-avg-2-chunk-16-left-64.onnx",
            "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
        ):
            (root / name).write_bytes(b"fixture")
        (root / "bunnelby.keywords.txt").write_text("▁B UN N EL BY\n", encoding="utf-8")

    def test_default_settings_are_lightweight_and_cpu_only(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            for key in (
                "WAKE_WORD_THREADS",
                "WAKE_WORD_MAX_ACTIVE_PATHS",
                "WAKE_WORD_TRAILING_BLANKS",
                "WAKE_WORD_SCORE",
                "WAKE_WORD_THRESHOLD",
            ):
                os.environ.pop(key, None)
            settings = wake_word_service.wake_word_settings()
        self.assertEqual(settings.sample_rate, 16000)
        self.assertEqual(settings.num_threads, 1)
        self.assertEqual(settings.max_active_paths, 4)
        self.assertEqual(settings.provider, "cpu")
        self.assertAlmostEqual(settings.keywords_score, 1.5)
        self.assertAlmostEqual(settings.keywords_threshold, 0.25)

    def test_environment_values_are_clamped(self) -> None:
        with patch.dict(
            os.environ,
            {
                "WAKE_WORD_THREADS": "999",
                "WAKE_WORD_MAX_ACTIVE_PATHS": "0",
                "WAKE_WORD_TRAILING_BLANKS": "999",
                "WAKE_WORD_SCORE": "999",
                "WAKE_WORD_THRESHOLD": "0",
            },
        ):
            settings = wake_word_service.wake_word_settings()
        self.assertEqual(settings.num_threads, 4)
        self.assertEqual(settings.max_active_paths, 1)
        self.assertEqual(settings.num_trailing_blanks, 16)
        self.assertAlmostEqual(settings.keywords_score, 10.0)
        self.assertAlmostEqual(settings.keywords_threshold, 0.01)

    def test_missing_model_directory_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "missing"
            with self.assertRaises(wake_word_service.WakeWordUnavailableError):
                wake_word_service.validate_wake_word_model(missing)

    def test_empty_keyword_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self._write_model_fixture(root)
            (root / "bunnelby.keywords.txt").write_text("", encoding="utf-8")
            with self.assertRaises(wake_word_service.WakeWordUnavailableError):
                wake_word_service.validate_wake_word_model(root)

    def test_keyword_spotter_uses_expected_safe_configuration(self) -> None:
        calls: list[dict[str, object]] = []

        class FakeKeywordSpotter:
            def __init__(self, **kwargs) -> None:
                calls.append(kwargs)

        fake_module = SimpleNamespace(KeywordSpotter=FakeKeywordSpotter)

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self._write_model_fixture(root)
            with (
                patch.dict(os.environ, {"WAKE_WORD_MODEL_DIR": str(root)}),
                patch.dict("sys.modules", {"sherpa_onnx": fake_module}),
            ):
                result = wake_word_service.create_keyword_spotter()

        self.assertIsInstance(result, FakeKeywordSpotter)
        self.assertEqual(len(calls), 1)
        config = calls[0]
        self.assertEqual(config["provider"], "cpu")
        self.assertEqual(config["num_threads"], 1)
        self.assertEqual(config["max_active_paths"], 4)
        self.assertTrue(str(config["keywords_file"]).endswith("bunnelby.keywords.txt"))

    def test_detection_resets_stream_after_single_trigger(self) -> None:
        class FakeStream:
            def __init__(self) -> None:
                self.accepted: list[tuple[int, object]] = []

            def accept_waveform(self, sample_rate: int, samples: object) -> None:
                self.accepted.append((sample_rate, samples))

        class FakeSpotter:
            def __init__(self) -> None:
                self.ready = [True, True]
                self.results = ["BUNNELBY", "BUNNELBY"]
                self.decode_calls = 0
                self.reset_calls = 0

            def is_ready(self, _stream) -> bool:
                return self.ready.pop(0) if self.ready else False

            def decode_stream(self, _stream) -> None:
                self.decode_calls += 1

            def get_result(self, _stream) -> str:
                return self.results.pop(0)

            def reset_stream(self, _stream) -> None:
                self.reset_calls += 1

        stream = FakeStream()
        spotter = FakeSpotter()
        detected = wake_word_service.detect_keyword_from_samples(
            spotter,
            stream,
            [0.0, 0.1],
            sample_rate=16000,
        )
        self.assertEqual(detected, "BUNNELBY")
        self.assertEqual(spotter.decode_calls, 1)
        self.assertEqual(spotter.reset_calls, 1)
        self.assertEqual(stream.accepted[0][0], 16000)

    def test_non_16khz_audio_is_rejected(self) -> None:
        with self.assertRaises(wake_word_service.WakeWordError):
            wake_word_service.detect_keyword_from_samples(
                SimpleNamespace(),
                SimpleNamespace(),
                [0.0],
                sample_rate=44100,
            )


if __name__ == "__main__":
    unittest.main()
