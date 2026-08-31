from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException

from services.api.app import main, stt_service


class STTServiceTests(unittest.TestCase):
    def tearDown(self) -> None:
        stt_service._reset_model_cache_for_tests()

    def test_defaults_lock_cpu_int8_small_model_and_beam5(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("STT_MODEL", None)
            os.environ.pop("STT_DEVICE", None)
            os.environ.pop("STT_COMPUTE_TYPE", None)
            os.environ.pop("STT_BEAM_SIZE", None)
            self.assertEqual(stt_service.stt_model_name(), "small")
            self.assertEqual(stt_service.stt_device(), "cpu")
            self.assertEqual(stt_service.stt_compute_type(), "int8")
            self.assertEqual(stt_service.stt_beam_size(), 5)

    def test_empty_audio_fails_before_model_load(self) -> None:
        with patch.object(stt_service, "_load_model") as load_model:
            with self.assertRaises(stt_service.STTAudioError):
                stt_service.transcribe_audio(b"")
        load_model.assert_not_called()

    def test_invalid_language_fails_closed(self) -> None:
        with patch.object(stt_service, "_load_model") as load_model:
            with self.assertRaises(stt_service.STTAudioError):
                stt_service.transcribe_audio(b"audio", language="fr")
        load_model.assert_not_called()

    def test_disabled_stt_fails_before_model_load(self) -> None:
        with (
            patch.dict(os.environ, {"STT_ENABLED": "false"}),
            patch.object(stt_service, "_load_model") as load_model,
        ):
            with self.assertRaises(stt_service.STTDisabledError):
                stt_service.transcribe_audio(b"audio")
        load_model.assert_not_called()

    def test_transcription_collects_segments_and_metadata(self) -> None:
        model = Mock()
        model.transcribe.return_value = (
            iter([SimpleNamespace(text=" Hello "), SimpleNamespace(text="Bunnelby")]),
            SimpleNamespace(language="en", language_probability=0.98, duration=1.7),
        )
        with (
            patch.object(stt_service, "_load_model", return_value=model),
            patch("services.api.app.stt_service.tempfile.NamedTemporaryFile") as named_temp,
            patch("services.api.app.stt_service.Path.unlink"),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("STT_BEAM_SIZE", None)
            handle = Mock()
            handle.name = "C:/Temp/bunnelby-test.webm"
            named_temp.return_value.__enter__.return_value = handle
            result = stt_service.transcribe_audio(
                b"fake-audio",
                content_type="audio/webm;codecs=opus",
                language="auto",
            )

        self.assertEqual(result.text, "Hello Bunnelby")
        self.assertEqual(result.language, "en")
        self.assertAlmostEqual(result.language_probability, 0.98)
        self.assertAlmostEqual(result.duration_seconds, 1.7)
        handle.write.assert_called_once_with(b"fake-audio")
        kwargs = model.transcribe.call_args.kwargs
        self.assertIsNone(kwargs["language"])
        self.assertEqual(kwargs["beam_size"], 5)
        self.assertTrue(kwargs["vad_filter"])
        self.assertFalse(kwargs["condition_on_previous_text"])

    def test_explicit_hindi_language_hint_is_forwarded(self) -> None:
        model = Mock()
        model.transcribe.return_value = (
            iter([SimpleNamespace(text=" नमस्ते ")]),
            SimpleNamespace(language="hi", language_probability=1.0, duration=0.8),
        )
        with (
            patch.object(stt_service, "_load_model", return_value=model),
            patch("services.api.app.stt_service.tempfile.NamedTemporaryFile") as named_temp,
            patch("services.api.app.stt_service.Path.unlink"),
        ):
            handle = Mock()
            handle.name = "C:/Temp/bunnelby-test.wav"
            named_temp.return_value.__enter__.return_value = handle
            result = stt_service.transcribe_audio(b"audio", content_type="audio/wav", language="hi")

        self.assertEqual(result.text, "नमस्ते")
        self.assertEqual(model.transcribe.call_args.kwargs["language"], "hi")

    def test_api_maps_bad_audio_to_400(self) -> None:
        with patch.object(main, "transcribe_audio", side_effect=stt_service.STTAudioError("bad audio")):
            with self.assertRaises(HTTPException) as context:
                main.speech_to_text(b"audio", "auto", "audio/webm")
        self.assertEqual(context.exception.status_code, 400)

    def test_api_maps_unavailable_model_to_503(self) -> None:
        with patch.object(main, "transcribe_audio", side_effect=stt_service.STTUnavailableError("missing")):
            with self.assertRaises(HTTPException) as context:
                main.speech_to_text(b"audio", "auto", "audio/webm")
        self.assertEqual(context.exception.status_code, 503)

    def test_api_returns_transcription_metadata(self) -> None:
        fake = stt_service.TranscriptionResult(
            text="check my calendar",
            language="en",
            language_probability=0.96,
            duration_seconds=1.4,
        )
        with patch.object(main, "transcribe_audio", return_value=fake):
            response = main.speech_to_text(b"audio", "auto", "audio/webm")
        self.assertEqual(response.text, "check my calendar")
        self.assertEqual(response.language, "en")
        self.assertAlmostEqual(response.language_probability, 0.96)


if __name__ == "__main__":
    unittest.main()
