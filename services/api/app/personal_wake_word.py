from __future__ import annotations

import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np


class PersonalWakeWordError(RuntimeError):
    """Base error for Bunnelby's personalized local wake-word engine."""


class PersonalWakeWordUnavailableError(PersonalWakeWordError):
    """Raised when a valid enrolled wake-word profile is unavailable."""


SAMPLE_RATE = 16_000
FRAME_LENGTH = 400  # 25 ms
FRAME_STEP = 160  # 10 ms
NFFT = 512
N_MELS = 32
N_MFCC = 13
FEATURE_DIM = N_MFCC * 3
MIN_AUDIO_SECONDS = 0.25
MAX_AUDIO_SECONDS = 4.0
MIN_TEMPLATE_FRAMES = 4
MAX_TEMPLATE_FRAMES = 400
MIN_POSITIVE_TEMPLATES = 6
MIN_NEGATIVE_TEMPLATES = 8
MAX_TEMPLATES_PER_CLASS = 32
PROFILE_VERSION = 1
MAX_PROFILE_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class WakeWordProfile:
    positive_templates: tuple[np.ndarray, ...]
    negative_templates: tuple[np.ndarray, ...]
    positive_threshold: float
    separation_margin: float


@dataclass(frozen=True)
class WakeWordDecision:
    detected: bool
    positive_score: float
    negative_score: float
    threshold: float
    required_margin: float


def personal_wake_word_profile_path() -> Path:
    configured = os.getenv("PERSONAL_WAKE_WORD_PROFILE", "").strip()
    if configured:
        return Path(configured).expanduser()

    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if local_app_data:
        return (
            Path(local_app_data)
            / "Bunnelby"
            / "models"
            / "wakeword"
            / "personalized"
            / "profile.npz"
        )
    return (
        Path.home()
        / ".bunnelby"
        / "models"
        / "wakeword"
        / "personalized"
        / "profile.npz"
    )


def _hz_to_mel(value: float) -> float:
    return 2595.0 * math.log10(1.0 + value / 700.0)


def _mel_to_hz(value: float) -> float:
    return 700.0 * (10.0 ** (value / 2595.0) - 1.0)


def _mel_filterbank() -> np.ndarray:
    low_mel = _hz_to_mel(40.0)
    high_mel = _hz_to_mel(SAMPLE_RATE / 2.0 - 100.0)
    mel_points = np.linspace(low_mel, high_mel, N_MELS + 2)
    hz_points = np.array([_mel_to_hz(v) for v in mel_points], dtype=np.float64)
    bins = np.floor((NFFT + 1) * hz_points / SAMPLE_RATE).astype(int)
    bins = np.clip(bins, 0, NFFT // 2)

    filters = np.zeros((N_MELS, NFFT // 2 + 1), dtype=np.float32)
    for index in range(1, N_MELS + 1):
        left, center, right = bins[index - 1], bins[index], bins[index + 1]
        if center <= left:
            center = min(left + 1, NFFT // 2)
        if right <= center:
            right = min(center + 1, NFFT // 2)
        for k in range(left, center):
            filters[index - 1, k] = (k - left) / max(1, center - left)
        for k in range(center, right):
            filters[index - 1, k] = (right - k) / max(1, right - center)
    return filters


_MEL_FILTERBANK = _mel_filterbank()
_DCT = np.empty((N_MFCC, N_MELS), dtype=np.float32)
for _k in range(N_MFCC):
    scale = math.sqrt(1.0 / N_MELS) if _k == 0 else math.sqrt(2.0 / N_MELS)
    for _n in range(N_MELS):
        _DCT[_k, _n] = scale * math.cos(math.pi * (_n + 0.5) * _k / N_MELS)


def _delta(features: np.ndarray, width: int = 2) -> np.ndarray:
    padded = np.pad(features, ((width, width), (0, 0)), mode="edge")
    denominator = 2.0 * sum(i * i for i in range(1, width + 1))
    result = np.zeros_like(features, dtype=np.float32)
    for offset in range(1, width + 1):
        result += offset * (
            padded[width + offset : width + offset + len(features)]
            - padded[width - offset : width - offset + len(features)]
        )
    return result / denominator


def extract_acoustic_features(samples: np.ndarray, *, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Extract normalized MFCC + delta + delta-delta features from one utterance.

    This intentionally uses only NumPy so the always-local wake-word path has no model,
    cloud, PyTorch, pickle, or arbitrary-code dependency. Input audio is never persisted here.
    """
    if sample_rate != SAMPLE_RATE:
        raise PersonalWakeWordError("Personal wake-word audio must be 16 kHz mono PCM.")

    mono = np.asarray(samples, dtype=np.float32).reshape(-1)
    if not np.all(np.isfinite(mono)):
        raise PersonalWakeWordError("Personal wake-word audio contains non-finite samples.")
    min_samples = int(MIN_AUDIO_SECONDS * SAMPLE_RATE)
    max_samples = int(MAX_AUDIO_SECONDS * SAMPLE_RATE)
    if mono.size < min_samples:
        raise PersonalWakeWordError("Wake-word utterance is too short for reliable matching.")
    if mono.size > max_samples:
        raise PersonalWakeWordError("Wake-word utterance is too long for reliable matching.")

    mono = np.clip(mono, -1.0, 1.0)
    peak = float(np.max(np.abs(mono)))
    if peak < 1e-4:
        raise PersonalWakeWordError("Wake-word utterance is effectively silent.")
    mono = mono / max(peak, 1e-6)

    emphasized = np.empty_like(mono)
    emphasized[0] = mono[0]
    emphasized[1:] = mono[1:] - 0.97 * mono[:-1]

    if emphasized.size <= FRAME_LENGTH:
        frame_count = 1
    else:
        frame_count = 1 + int(math.ceil((emphasized.size - FRAME_LENGTH) / FRAME_STEP))
    padded_length = (frame_count - 1) * FRAME_STEP + FRAME_LENGTH
    padded = np.pad(emphasized, (0, max(0, padded_length - emphasized.size)))

    indices = (
        np.arange(FRAME_LENGTH, dtype=np.int64)[None, :]
        + np.arange(frame_count, dtype=np.int64)[:, None] * FRAME_STEP
    )
    frames = padded[indices] * np.hamming(FRAME_LENGTH).astype(np.float32)
    spectrum = np.fft.rfft(frames, n=NFFT)
    power = (np.abs(spectrum) ** 2 / NFFT).astype(np.float32)
    mel_energy = np.maximum(power @ _MEL_FILTERBANK.T, 1e-10)
    log_mel = np.log(mel_energy)
    mfcc = (log_mel @ _DCT.T).astype(np.float32)

    mean = np.mean(mfcc, axis=0, keepdims=True)
    std = np.std(mfcc, axis=0, keepdims=True)
    mfcc = (mfcc - mean) / np.maximum(std, 1e-5)
    delta = _delta(mfcc)
    delta_delta = _delta(delta)
    features = np.concatenate((mfcc, delta, delta_delta), axis=1).astype(np.float32)

    if features.shape[1] != FEATURE_DIM:
        raise PersonalWakeWordError("Unexpected personal wake-word feature dimension.")
    if not MIN_TEMPLATE_FRAMES <= features.shape[0] <= MAX_TEMPLATE_FRAMES:
        raise PersonalWakeWordError("Wake-word feature sequence length is outside safe bounds.")
    if not np.all(np.isfinite(features)):
        raise PersonalWakeWordError("Wake-word features contain non-finite values.")
    return features


def _normalized_frames(features: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(features, axis=1, keepdims=True)
    return features / np.maximum(norms, 1e-6)


def dtw_distance(first: np.ndarray, second: np.ndarray) -> float:
    """Return a bounded, length-normalized DTW cosine distance between two templates."""
    a = _validate_template(first)
    b = _validate_template(second)
    a = _normalized_frames(a)
    b = _normalized_frames(b)
    n, m = a.shape[0], b.shape[0]
    band = max(abs(n - m) + 6, int(max(n, m) * 0.30))

    previous = np.full(m + 1, np.inf, dtype=np.float64)
    previous[0] = 0.0
    for i in range(1, n + 1):
        current = np.full(m + 1, np.inf, dtype=np.float64)
        start = max(1, i - band)
        stop = min(m, i + band)
        for j in range(start, stop + 1):
            local = 1.0 - float(np.clip(np.dot(a[i - 1], b[j - 1]), -1.0, 1.0))
            current[j] = local + min(previous[j], current[j - 1], previous[j - 1])
        previous = current

    raw = float(previous[m])
    if not math.isfinite(raw):
        return float("inf")
    normalized = raw / max(1, n + m)
    duration_penalty = 0.12 * abs(math.log(max(n, 1) / max(m, 1)))
    return normalized + duration_penalty


def _validate_template(value: np.ndarray) -> np.ndarray:
    array = np.asarray(value, dtype=np.float32)
    if array.ndim != 2 or array.shape[1] != FEATURE_DIM:
        raise PersonalWakeWordError("Invalid wake-word template shape.")
    if not MIN_TEMPLATE_FRAMES <= array.shape[0] <= MAX_TEMPLATE_FRAMES:
        raise PersonalWakeWordError("Invalid wake-word template length.")
    if not np.all(np.isfinite(array)):
        raise PersonalWakeWordError("Wake-word template contains non-finite values.")
    return array


def _template_score(features: np.ndarray, templates: Sequence[np.ndarray], *, k: int = 3) -> float:
    if not templates:
        return float("inf")
    distances = sorted(dtw_distance(features, template) for template in templates)
    count = min(max(1, k), len(distances))
    return float(np.median(np.asarray(distances[:count], dtype=np.float64)))


def calibrate_profile(
    positive_templates: Sequence[np.ndarray],
    negative_templates: Sequence[np.ndarray],
) -> WakeWordProfile:
    positives = tuple(_validate_template(item).copy() for item in positive_templates)
    negatives = tuple(_validate_template(item).copy() for item in negative_templates)
    if not MIN_POSITIVE_TEMPLATES <= len(positives) <= MAX_TEMPLATES_PER_CLASS:
        raise PersonalWakeWordError(
            f"Enrollment requires {MIN_POSITIVE_TEMPLATES}-{MAX_TEMPLATES_PER_CLASS} positive samples."
        )
    if not MIN_NEGATIVE_TEMPLATES <= len(negatives) <= MAX_TEMPLATES_PER_CLASS:
        raise PersonalWakeWordError(
            f"Enrollment requires {MIN_NEGATIVE_TEMPLATES}-{MAX_TEMPLATES_PER_CLASS} negative samples."
        )

    positive_scores: list[float] = []
    positive_to_negative: list[float] = []
    for index, template in enumerate(positives):
        peers = positives[:index] + positives[index + 1 :]
        positive_scores.append(_template_score(template, peers))
        positive_to_negative.append(_template_score(template, negatives))

    negative_to_positive = [_template_score(template, positives) for template in negatives]
    negative_self_scores: list[float] = []
    for index, template in enumerate(negatives):
        peers = negatives[:index] + negatives[index + 1 :]
        negative_self_scores.append(_template_score(template, peers))

    worst_positive = max(positive_scores)
    closest_negative = min(negative_to_positive)
    if not math.isfinite(worst_positive) or not math.isfinite(closest_negative):
        raise PersonalWakeWordError("Wake-word enrollment calibration produced invalid scores.")
    if worst_positive >= closest_negative:
        raise PersonalWakeWordError(
            "Enrollment samples are not acoustically separable enough. Re-enroll with clearer "
            "Bunnelby samples and more varied negative phrases."
        )

    threshold = worst_positive + 0.40 * (closest_negative - worst_positive)

    positive_margins = [
        neg_score - pos_score
        for pos_score, neg_score in zip(positive_scores, positive_to_negative)
    ]
    negative_margins = [
        pos_score - neg_score
        for pos_score, neg_score in zip(negative_to_positive, negative_self_scores)
    ]
    available_margin = min(positive_margins + negative_margins)
    if available_margin <= 0:
        raise PersonalWakeWordError(
            "Enrollment classes overlap acoustically. Re-enrollment is required."
        )
    required_margin = max(0.002, min(0.08, available_margin * 0.20))

    return WakeWordProfile(
        positive_templates=positives,
        negative_templates=negatives,
        positive_threshold=float(threshold),
        separation_margin=float(required_margin),
    )


def evaluate_features(features: np.ndarray, profile: WakeWordProfile) -> WakeWordDecision:
    candidate = _validate_template(features)
    positive_score = _template_score(candidate, profile.positive_templates)
    negative_score = _template_score(candidate, profile.negative_templates)
    detected = (
        positive_score <= profile.positive_threshold
        and positive_score + profile.separation_margin < negative_score
    )
    return WakeWordDecision(
        detected=bool(detected),
        positive_score=float(positive_score),
        negative_score=float(negative_score),
        threshold=float(profile.positive_threshold),
        required_margin=float(profile.separation_margin),
    )


def save_profile(profile: WakeWordProfile, path: Path | None = None) -> Path:
    target = (path or personal_wake_word_profile_path()).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    if len(profile.positive_templates) > MAX_TEMPLATES_PER_CLASS or len(profile.negative_templates) > MAX_TEMPLATES_PER_CLASS:
        raise PersonalWakeWordError("Wake-word profile contains too many templates.")

    payload: dict[str, np.ndarray] = {
        "version": np.asarray([PROFILE_VERSION], dtype=np.int32),
        "sample_rate": np.asarray([SAMPLE_RATE], dtype=np.int32),
        "positive_count": np.asarray([len(profile.positive_templates)], dtype=np.int32),
        "negative_count": np.asarray([len(profile.negative_templates)], dtype=np.int32),
        "positive_threshold": np.asarray([profile.positive_threshold], dtype=np.float32),
        "separation_margin": np.asarray([profile.separation_margin], dtype=np.float32),
    }
    for index, template in enumerate(profile.positive_templates):
        payload[f"positive_{index:02d}"] = _validate_template(template)
    for index, template in enumerate(profile.negative_templates):
        payload[f"negative_{index:02d}"] = _validate_template(template)

    handle = tempfile.NamedTemporaryFile(
        mode="w+b", suffix=".npz", prefix="profile-", dir=target.parent, delete=False
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            np.savez_compressed(handle, **payload)
            handle.flush()
            os.fsync(handle.fileno())
        if temp_path.stat().st_size <= 0 or temp_path.stat().st_size > MAX_PROFILE_BYTES:
            raise PersonalWakeWordError("Serialized wake-word profile size is invalid.")
        os.replace(temp_path, target)
    finally:
        temp_path.unlink(missing_ok=True)
    return target


def load_profile(path: Path | None = None) -> WakeWordProfile:
    target = (path or personal_wake_word_profile_path()).expanduser()
    if not target.is_file():
        raise PersonalWakeWordUnavailableError(
            f"Personalized Bunnelby wake-word profile is missing at {target}."
        )
    size = target.stat().st_size
    if size <= 0 or size > MAX_PROFILE_BYTES:
        raise PersonalWakeWordUnavailableError("Personalized wake-word profile size is invalid.")

    try:
        with np.load(target, allow_pickle=False) as data:
            version = int(data["version"][0])
            sample_rate = int(data["sample_rate"][0])
            positive_count = int(data["positive_count"][0])
            negative_count = int(data["negative_count"][0])
            threshold = float(data["positive_threshold"][0])
            margin = float(data["separation_margin"][0])
            if version != PROFILE_VERSION or sample_rate != SAMPLE_RATE:
                raise PersonalWakeWordUnavailableError("Personalized wake-word profile version is unsupported.")
            if not MIN_POSITIVE_TEMPLATES <= positive_count <= MAX_TEMPLATES_PER_CLASS:
                raise PersonalWakeWordUnavailableError("Personalized wake-word positive count is invalid.")
            if not MIN_NEGATIVE_TEMPLATES <= negative_count <= MAX_TEMPLATES_PER_CLASS:
                raise PersonalWakeWordUnavailableError("Personalized wake-word negative count is invalid.")
            if not math.isfinite(threshold) or threshold <= 0:
                raise PersonalWakeWordUnavailableError("Personalized wake-word threshold is invalid.")
            if not math.isfinite(margin) or margin <= 0:
                raise PersonalWakeWordUnavailableError("Personalized wake-word margin is invalid.")

            positives = tuple(
                _validate_template(data[f"positive_{index:02d}"]).copy()
                for index in range(positive_count)
            )
            negatives = tuple(
                _validate_template(data[f"negative_{index:02d}"]).copy()
                for index in range(negative_count)
            )
    except PersonalWakeWordUnavailableError:
        raise
    except Exception as exc:
        raise PersonalWakeWordUnavailableError("Personalized wake-word profile is corrupt or invalid.") from exc

    return WakeWordProfile(
        positive_templates=positives,
        negative_templates=negatives,
        positive_threshold=threshold,
        separation_margin=margin,
    )
