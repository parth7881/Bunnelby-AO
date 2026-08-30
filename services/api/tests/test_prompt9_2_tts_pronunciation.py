from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
