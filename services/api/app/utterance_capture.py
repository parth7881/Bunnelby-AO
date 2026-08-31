from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np


class UtteranceCaptureError(RuntimeError):
    """Raised when a bounded local microphone utterance cannot be captured safely."""


@dataclass
class VadUtteranceAggregator:
    """Aggregate one logical utterance across multiple completed VAD segments.

    sherpa-onnx emits a completed segment as soon as its configured minimum silence is
    observed. Human sentences can contain pauses longer than that, so returning the first
    segment truncates natural speech. This aggregator waits a short continuation window,
    while also consulting ``is_speech_detected()`` so newly-started speech keeps the same
    logical utterance alive.
    """

    sample_rate: int
    continuation_seconds: float = 0.50
    inter_segment_gap_seconds: float = 0.08
    max_output_seconds: float = 8.0
    _segments: list[np.ndarray] = field(default_factory=list, init=False)
    _last_completed_at: float | None = field(default=None, init=False)
    _speech_ever_seen: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.sample_rate != 16_000:
            raise UtteranceCaptureError("Utterance aggregation currently requires 16 kHz audio.")
        if not 0.10 <= float(self.continuation_seconds) <= 1.50:
            raise UtteranceCaptureError("Continuation window is outside safe bounds.")
        if not 0.0 <= float(self.inter_segment_gap_seconds) <= 0.25:
            raise UtteranceCaptureError("Inter-segment gap is outside safe bounds.")
        if not 1.0 <= float(self.max_output_seconds) <= 15.0:
            raise UtteranceCaptureError("Maximum utterance duration is outside safe bounds.")

    def _append_completed_segments(self, detector: Any, now: float) -> None:
        while not detector.empty():
            raw = np.asarray(detector.front.samples, dtype=np.float32).reshape(-1).copy()
            detector.pop()
            if raw.size == 0:
                continue
            if not np.all(np.isfinite(raw)):
                raise UtteranceCaptureError("VAD returned non-finite speech samples.")
            self._segments.append(np.clip(raw, -1.0, 1.0))
            self._last_completed_at = now
            self._speech_ever_seen = True
            if self._current_sample_count() > int(self.max_output_seconds * self.sample_rate):
                raise UtteranceCaptureError("Captured utterance exceeds the configured duration limit.")

    def _current_sample_count(self) -> int:
        if not self._segments:
            return 0
        gap_samples = int(round(self.inter_segment_gap_seconds * self.sample_rate))
        return sum(segment.size for segment in self._segments) + gap_samples * (len(self._segments) - 1)

    def observe(self, detector: Any, *, now: float) -> np.ndarray | None:
        """Drain completed segments and return audio once the logical turn has ended."""
        if not math.isfinite(now):
            raise UtteranceCaptureError("Monotonic timestamp is invalid.")

        self._append_completed_segments(detector, now)
        currently_speaking = bool(detector.is_speech_detected())
        if currently_speaking:
            self._speech_ever_seen = True
            return None

        if (
            self._segments
            and self._last_completed_at is not None
            and now - self._last_completed_at >= self.continuation_seconds
        ):
            return self.finalize()
        return None

    def finalize(self) -> np.ndarray:
        if not self._segments:
            raise UtteranceCaptureError("No completed speech was captured.")
        gap_samples = int(round(self.inter_segment_gap_seconds * self.sample_rate))
        if gap_samples <= 0 or len(self._segments) == 1:
            output = np.concatenate(self._segments).astype(np.float32, copy=False)
        else:
            gap = np.zeros(gap_samples, dtype=np.float32)
            pieces: list[np.ndarray] = []
            for index, segment in enumerate(self._segments):
                if index:
                    pieces.append(gap)
                pieces.append(segment)
            output = np.concatenate(pieces).astype(np.float32, copy=False)

        if output.size <= 0 or output.size > int(self.max_output_seconds * self.sample_rate):
            raise UtteranceCaptureError("Final utterance size is invalid.")
        if not np.all(np.isfinite(output)):
            raise UtteranceCaptureError("Final utterance contains non-finite samples.")
        return output


def capture_vad_utterance(
    stream: Any,
    detector: Any,
    *,
    sample_rate: int,
    window_size: int,
    timeout_seconds: float,
    continuation_seconds: float = 0.50,
    max_output_seconds: float = 8.0,
    now_fn: Callable[[], float] = time.monotonic,
) -> np.ndarray:
    """Capture one bounded logical utterance from an already-open microphone stream.

    No audio is persisted. The caller owns the microphone and detector lifecycle.
    """
    if sample_rate != 16_000:
        raise UtteranceCaptureError("Utterance capture requires 16 kHz audio.")
    if window_size < 80 or window_size > 4096:
        raise UtteranceCaptureError("VAD window size is outside safe bounds.")
    timeout = float(timeout_seconds)
    if not 2.0 <= timeout <= 30.0:
        raise UtteranceCaptureError("Utterance timeout is outside safe bounds.")

    aggregator = VadUtteranceAggregator(
        sample_rate=sample_rate,
        continuation_seconds=continuation_seconds,
        max_output_seconds=max_output_seconds,
    )
    started = now_fn()
    deadline = started + timeout

    while now_fn() < deadline:
        samples, _overflowed = stream.read(window_size)
        chunk = np.asarray(samples, dtype=np.float32).reshape(-1)
        if chunk.size != window_size:
            raise UtteranceCaptureError("Microphone returned an unexpected frame size.")
        if not np.all(np.isfinite(chunk)):
            raise UtteranceCaptureError("Microphone returned non-finite samples.")

        detector.accept_waveform(np.clip(chunk, -1.0, 1.0))
        completed = aggregator.observe(detector, now=now_fn())
        if completed is not None:
            return completed

    # Flush only at the hard timeout so an in-progress final segment is not silently lost.
    try:
        detector.flush()
    except Exception as exc:
        raise UtteranceCaptureError("VAD could not flush its final buffered segment.") from exc

    aggregator._append_completed_segments(detector, now_fn())
    if aggregator._segments:
        return aggregator.finalize()
    raise TimeoutError("No completed speech utterance detected before timeout.")
