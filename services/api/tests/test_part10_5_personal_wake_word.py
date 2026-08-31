from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from services.api.app import personal_wake_word as pww


class PersonalWakeWordTests(unittest.TestCase):
    def _tone(self, frequency: float, seconds: float = 0.9) -> np.ndarray:
        t = np.arange(int(seconds * pww.SAMPLE_RATE), dtype=np.float32) / pww.SAMPLE_RATE
        signal = (
            0.45 * np.sin(2 * np.pi * frequency * t)
            + 0.25 * np.sin(2 * np.pi * (frequency * 1.7) * t)
            + 0.10 * np.sin(2 * np.pi * (frequency * 2.3) * t)
        )
        envelope = np.minimum(1.0, np.arange(signal.size) / 500.0)
        envelope *= np.minimum(1.0, np.arange(signal.size)[::-1] / 500.0)
        return (signal * envelope).astype(np.float32)

    def test_feature_extraction_shape_is_bounded(self) -> None:
        features = pww.extract_acoustic_features(self._tone(230.0))
        self.assertEqual(features.ndim, 2)
        self.assertEqual(features.shape[1], pww.FEATURE_DIM)
        self.assertGreaterEqual(features.shape[0], pww.MIN_TEMPLATE_FRAMES)
        self.assertTrue(np.all(np.isfinite(features)))

    def test_silence_is_rejected(self) -> None:
        samples = np.zeros(pww.SAMPLE_RATE, dtype=np.float32)
        with self.assertRaises(pww.PersonalWakeWordError):
            pww.extract_acoustic_features(samples)

    def test_wrong_sample_rate_is_rejected(self) -> None:
        with self.assertRaises(pww.PersonalWakeWordError):
            pww.extract_acoustic_features(self._tone(230.0), sample_rate=44100)

    def test_dtw_same_template_is_close(self) -> None:
        features = pww.extract_acoustic_features(self._tone(230.0))
        self.assertLess(pww.dtw_distance(features, features), 1e-5)

    def test_profile_round_trip_uses_no_pickle(self) -> None:
        positives = [pww.extract_acoustic_features(self._tone(220 + i * 2)) for i in range(6)]
        negatives = [pww.extract_acoustic_features(self._tone(500 + i * 30)) for i in range(8)]
        profile = pww.calibrate_profile(positives, negatives)

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.npz"
            pww.save_profile(profile, path)
            loaded = pww.load_profile(path)

        self.assertEqual(len(loaded.positive_templates), 6)
        self.assertEqual(len(loaded.negative_templates), 8)
        self.assertGreater(loaded.positive_threshold, 0)
        self.assertGreater(loaded.separation_margin, 0)

    def test_corrupt_profile_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.npz"
            path.write_bytes(b"not-an-npz")
            with self.assertRaises(pww.PersonalWakeWordUnavailableError):
                pww.load_profile(path)

    def test_positive_like_candidate_is_detected(self) -> None:
        positives = [pww.extract_acoustic_features(self._tone(220 + i * 2)) for i in range(6)]
        negatives = [pww.extract_acoustic_features(self._tone(500 + i * 25)) for i in range(8)]
        profile = pww.calibrate_profile(positives, negatives)
        candidate = pww.extract_acoustic_features(self._tone(225.0))
        decision = pww.evaluate_features(candidate, profile)
        self.assertTrue(decision.detected)

    def test_negative_like_candidate_is_rejected(self) -> None:
        positives = [pww.extract_acoustic_features(self._tone(220 + i * 2)) for i in range(6)]
        negatives = [pww.extract_acoustic_features(self._tone(500 + i * 25)) for i in range(8)]
        profile = pww.calibrate_profile(positives, negatives)
        candidate = pww.extract_acoustic_features(self._tone(640.0))
        decision = pww.evaluate_features(candidate, profile)
        self.assertFalse(decision.detected)

    def test_overlapping_enrollment_fails_closed(self) -> None:
        same = [pww.extract_acoustic_features(self._tone(300.0)) for _ in range(8)]
        with self.assertRaises(pww.PersonalWakeWordError):
            pww.calibrate_profile(same[:6], same)


if __name__ == "__main__":
    unittest.main()
