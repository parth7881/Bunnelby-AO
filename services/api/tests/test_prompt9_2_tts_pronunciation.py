from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from services.api.app import tts_service
from services.api.app.tts_pronunciation import normalize_tts_text


class TTSPronunciationTests(unittest.TestCase):
    def test_hindi_normalizes_common_technical_terms(self) -> None:
        text = normalize_tts_text("Bunnelby ने GPU और API check कर लिया है।", "hi")
        self.assertIn("बनलबी", text)
        self.assertIn("जी पी यू", text)
        self.assertIn("ए पी आई", text)

    def test_hindi_normalizes_clock_markers(self) -> None:
        text = normalize_tts_text("Meeting 10 AM पर है और review 8 PM पर है।", "hi")
        self.assertIn("सुबह 10 बजे", text)
        self.assertIn("शाम 8 बजे", text)
        self.assertNotIn(" AM", text)
        self.assertNotIn(" PM", text)

    def test_display_markdown_is_removed(self) -> None:
        text = normalize_tts_text("**System ready** — awaiting command.", "en")
        self.assertNotIn("**", text)
        self.assertIn("System ready", text)

    def test_english_acronyms_are_spelled(self) -> None:
        text = normalize_tts_text("GPU and API status ready", "en")
        self.assertIn("G P U", text)
        self.assertIn("A P I", text)


class TTSProviderRoutingTests(unittest.TestCase):
    def test_prompt9_2_edge_defaults_are_language_specific(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            for name in (
                "EDGE_TTS_ENGLISH_VOICE",
                "EDGE_TTS_HINDI_VOICE",
                "EDGE_TTS_EN_RATE",
                "EDGE_TTS_HI_RATE",
                "EDGE_TTS_EN_PITCH",
                "EDGE_TTS_HI_PITCH",
            ):
                os.environ.pop(name, None)

            self.assertEqual(tts_service.edge_voice_name("en"), "en-GB-RyanNeural")
            self.assertEqual(tts_service.edge_voice_name("hi"), "hi-IN-MadhurNeural")
            self.assertEqual(tts_service.edge_rate("en"), "+4%")
            self.assertEqual(tts_service.edge_rate("hi"), "+8%")
            self.assertEqual(tts_service.edge_pitch("en"), "-12Hz")
            self.assertEqual(tts_service.edge_pitch("hi"), "-12Hz")

    def test_edge_is_primary_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TTS_PROVIDER", None)
            self.assertEqual(tts_service.preferred_provider(), "edge")

    def test_edge_failure_falls_back_to_piper(self) -> None:
        with (
            patch.dict(os.environ, {"TTS_PROVIDER": "edge", "TTS_ENABLED": "true"}),
            patch.object(
                tts_service,
                "_synthesize_edge",
                side_effect=tts_service._EdgeTTSUnavailableError("offline"),
            ) as edge,
            patch.object(tts_service, "_synthesize_piper", return_value=b"RIFF-piper") as piper,
        ):
            audio = tts_service.synthesize_speech("Bunnelby online", "en")

        self.assertEqual(audio, b"RIFF-piper")
        self.assertEqual(edge.call_count, 1)
        self.assertEqual(piper.call_count, 1)
        self.assertIn("Bunnelby", piper.call_args.args[0])

    def test_piper_can_be_forced_for_offline_mode(self) -> None:
        with (
            patch.dict(os.environ, {"TTS_PROVIDER": "piper", "TTS_ENABLED": "true"}),
            patch.object(tts_service, "_synthesize_edge") as edge,
            patch.object(tts_service, "_synthesize_piper", return_value=b"RIFF-offline") as piper,
        ):
            audio = tts_service.synthesize_speech("System ready", "en")

        self.assertEqual(audio, b"RIFF-offline")
        self.assertEqual(edge.call_count, 0)
        self.assertEqual(piper.call_count, 1)

    def test_hindi_edge_uses_balanced_pause_filter(self) -> None:
        self.assertIn("stop_duration=0.28", tts_service.EDGE_HINDI_AUDIO_FILTER)
        self.assertIn("stop_silence=0.14", tts_service.EDGE_HINDI_AUDIO_FILTER)


if __name__ == "__main__":
    unittest.main()
