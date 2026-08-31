from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services.api.app import vad_service


class VADServiceTests(unittest.TestCase):
    def test_defaults_lock_16khz_silero_runtime(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            for key in (
                "VAD_THRESHOLD",
                "VAD_MIN_SILENCE_SECONDS",
                "VAD_MIN_SPEECH_SECONDS",
                "VAD_MAX_SPEECH_SECONDS",
            ):
                os.environ.pop(key, None)
            settings = vad_service.vad_settings()
        self.assertEqual(settings.sample_rate, 16000)
        self.assertEqual(settings.window_size, 512)
        self.assertAlmostEqual(settings.threshold, 0.35)
        self.assertAlmostEqual(settings.min_silence_duration, 0.45)
        self.assertAlmostEqual(settings.min_speech_duration, 0.15)
        self.assertAlmostEqual(settings.max_speech_duration, 12.0)

    def test_environment_values_are_clamped(self) -> None:
        with patch.dict(
            os.environ,
            {
                "VAD_THRESHOLD": "3",
                "VAD_MIN_SILENCE_SECONDS": "0",
                "VAD_MIN_SPEECH_SECONDS": "8",
                "VAD_MAX_SPEECH_SECONDS": "100",
            },
        ):
            settings = vad_service.vad_settings()
        self.assertAlmostEqual(settings.threshold, 0.95)
        self.assertAlmostEqual(settings.min_silence_duration, 0.10)
        self.assertAlmostEqual(settings.min_speech_duration, 2.0)
        self.assertAlmostEqual(settings.max_speech_duration, 30.0)

    def test_missing_model_fails_before_importing_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "silero_vad.onnx"
            with patch.dict(os.environ, {"VAD_MODEL_PATH": str(missing)}):
                with self.assertRaises(vad_service.VADUnavailableError):
                    vad_service.create_voice_activity_detector()

    def test_detector_uses_expected_silero_configuration(self) -> None:
        class FakeSilero:
            def __init__(self) -> None:
                self.model = ""
                self.threshold = 0.0
                self.min_silence_duration = 0.0
                self.min_speech_duration = 0.0
                self.max_speech_duration = 0.0
                self.window_size = 512

        class FakeConfig:
            def __init__(self) -> None:
                self.silero_vad = FakeSilero()
                self.sample_rate = 0

        detector_calls: list[tuple[object, float]] = []

        def fake_detector(config, buffer_size_in_seconds):
            detector_calls.append((config, buffer_size_in_seconds))
            return SimpleNamespace(config=config)

        fake_module = SimpleNamespace(
            VadModelConfig=FakeConfig,
            VoiceActivityDetector=fake_detector,
        )

        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / "silero_vad.onnx"
            model.write_bytes(b"fake")
            with (
                patch.dict(os.environ, {"VAD_MODEL_PATH": str(model)}),
                patch.dict("sys.modules", {"sherpa_onnx": fake_module}),
            ):
                detector = vad_service.create_voice_activity_detector()

        self.assertIsNotNone(detector)
        self.assertEqual(len(detector_calls), 1)
        config, buffer_size = detector_calls[0]
        self.assertEqual(config.sample_rate, 16000)
        self.assertEqual(config.silero_vad.model, str(model))
        self.assertAlmostEqual(config.silero_vad.threshold, 0.35)
        self.assertAlmostEqual(config.silero_vad.min_silence_duration, 0.45)
        self.assertAlmostEqual(config.silero_vad.min_speech_duration, 0.15)
        self.assertAlmostEqual(config.silero_vad.max_speech_duration, 12.0)
        self.assertEqual(buffer_size, 30.0)


if __name__ == "__main__":
    unittest.main()
