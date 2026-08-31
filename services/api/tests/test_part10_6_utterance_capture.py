from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np

from services.api.app.utterance_capture import (
    UtteranceCaptureError,
    VadUtteranceAggregator,
    capture_vad_utterance,
)


class _FakeDetector:
    def __init__(self) -> None:
        self.queue: list[np.ndarray] = []
        self.speaking = False
        self.flush_calls = 0

    def empty(self) -> bool:
        return not self.queue

    @property
    def front(self):
        if not self.queue:
            raise RuntimeError("empty")
        return SimpleNamespace(samples=self.queue[0])

    def pop(self) -> None:
        self.queue.pop(0)

    def is_speech_detected(self) -> bool:
        return self.speaking

    def accept_waveform(self, _samples) -> None:
        return None

    def flush(self) -> None:
        self.flush_calls += 1


class _FakeStream:
    def __init__(self, frames: list[np.ndarray]) -> None:
        self.frames = list(frames)

    def read(self, _size: int):
        if not self.frames:
            return np.zeros((512, 1), dtype=np.float32), False
        return self.frames.pop(0).reshape(-1, 1), False


class UtteranceAggregatorTests(unittest.TestCase):
    def test_waits_for_continuation_then_finalizes(self) -> None:
        detector = _FakeDetector()
        aggregator = VadUtteranceAggregator(
            sample_rate=16000,
            continuation_seconds=0.5,
            inter_segment_gap_seconds=0.0,
            max_output_seconds=4.0,
        )
        detector.queue.append(np.ones(1600, dtype=np.float32) * 0.1)
        self.assertIsNone(aggregator.observe(detector, now=1.0))
        self.assertIsNone(aggregator.observe(detector, now=1.49))
        result = aggregator.observe(detector, now=1.51)
        self.assertIsNotNone(result)
        self.assertEqual(result.size, 1600)

    def test_multiple_segments_join_into_one_logical_utterance(self) -> None:
        detector = _FakeDetector()
        aggregator = VadUtteranceAggregator(
            sample_rate=16000,
            continuation_seconds=0.5,
            inter_segment_gap_seconds=0.05,
            max_output_seconds=4.0,
        )
        detector.queue.append(np.ones(800, dtype=np.float32) * 0.1)
        self.assertIsNone(aggregator.observe(detector, now=1.0))

        detector.speaking = True
        self.assertIsNone(aggregator.observe(detector, now=1.3))
        detector.speaking = False
        detector.queue.append(np.ones(1200, dtype=np.float32) * 0.2)
        self.assertIsNone(aggregator.observe(detector, now=1.4))

        result = aggregator.observe(detector, now=1.91)
        self.assertIsNotNone(result)
        expected_gap = int(round(0.05 * 16000))
        self.assertEqual(result.size, 800 + expected_gap + 1200)

    def test_nonfinite_segment_fails_closed(self) -> None:
        detector = _FakeDetector()
        detector.queue.append(np.asarray([0.1, np.nan], dtype=np.float32))
        aggregator = VadUtteranceAggregator(sample_rate=16000)
        with self.assertRaises(UtteranceCaptureError):
            aggregator.observe(detector, now=1.0)

    def test_unexpected_microphone_frame_size_fails_closed(self) -> None:
        detector = _FakeDetector()
        stream = _FakeStream([np.zeros(256, dtype=np.float32)])
        with self.assertRaises(UtteranceCaptureError):
            capture_vad_utterance(
                stream,
                detector,
                sample_rate=16000,
                window_size=512,
                timeout_seconds=2.0,
                now_fn=lambda: 0.0,
            )

    def test_invalid_sample_rate_is_rejected(self) -> None:
        with self.assertRaises(UtteranceCaptureError):
            VadUtteranceAggregator(sample_rate=44100)


if __name__ == "__main__":
    unittest.main()
