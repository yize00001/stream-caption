"""Segment quality, conservative overlap deduplication and bounded context."""

import math
import re
from collections import deque
from dataclasses import asdict, dataclass

from stream_caption.audio import SAMPLE_RATE


def sanitize_diagnostic(value):
    """Keep diagnostics valid JSON even when rejected model output has NaN scores."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: sanitize_diagnostic(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [sanitize_diagnostic(item) for item in value]
    return value


@dataclass(frozen=True)
class SpeechWord:
    word: str
    start: float
    end: float
    probability: float


@dataclass(frozen=True)
class SpeechSegment:
    text: str
    start: float
    end: float
    avg_logprob: float
    no_speech_prob: float
    compression_ratio: float
    words: tuple[SpeechWord, ...] = ()

    def rejection_reason(self, settings):
        values = (self.start, self.end, self.avg_logprob,
                  self.no_speech_prob, self.compression_ratio)
        if not all(math.isfinite(value) for value in values) or self.end <= self.start:
            return "invalid_segment"
        if not settings.quality_filter:
            return ""
        # Joint evidence, rather than a phrase blacklist or a confidence guarantee.
        low_probability = self.avg_logprob < settings.min_avg_logprob
        if low_probability and self.no_speech_prob > settings.max_no_speech_prob:
            return "low_probability_and_no_speech"
        if low_probability and self.compression_ratio > settings.max_compression_ratio:
            return "low_probability_and_repetition"
        return ""


@dataclass(frozen=True)
class Transcription:
    segments: tuple[SpeechSegment, ...]
    language: str
    language_probability: float
    speech_seconds: float

    def diagnostics(self):
        return sanitize_diagnostic(asdict(self))


class SegmentHistory:
    """Suppress identical text only when it covers the same overlapping audio."""

    def __init__(self):
        self._seen = deque()

    def clear(self):
        self._seen.clear()

    def select(self, segments, window_start_sample):
        window_start = window_start_sample / SAMPLE_RATE
        while self._seen and self._seen[0][2] < window_start - 1:
            self._seen.popleft()
        fresh = []
        for segment in segments:
            key = re.sub(r"\s+", " ", segment.text).strip().casefold().strip("。.!?！？")
            start, end = window_start + segment.start, window_start + segment.end
            if not key:
                continue
            duplicate = any(
                key == previous and min(end, old_end) - max(start, old_start)
                >= 0.5 * min(end - start, old_end - old_start)
                for previous, old_start, old_end in self._seen
            )
            if not duplicate:
                fresh.append(segment)
        return fresh

    def commit(self, segments, window_start_sample):
        offset = window_start_sample / SAMPLE_RATE
        for segment in segments:
            key = re.sub(r"\s+", " ", segment.text).strip().casefold().strip("。.!?！？")
            self._seen.append((key, offset + segment.start, offset + segment.end))


class TranslationContext:
    def __init__(self, settings):
        self._settings = settings
        self._items = deque(maxlen=settings.context_max_sentences)
        self._language = None
        self._last_time = None

    def clear(self):
        self._items.clear()
        self._language = None
        self._last_time = None

    def get(self, language, now):
        if (language != self._language or self._last_time is None
                or now - self._last_time > self._settings.context_max_age_seconds):
            self.clear()
            return "", ""
        while self._items and now - self._items[0][2] > self._settings.context_max_age_seconds:
            self._items.popleft()
        return tuple("\n".join(item[index] for item in self._items) for index in (0, 1))

    def add(self, source, target, language, now):
        self.get(language, now)
        limit = self._settings.context_max_characters
        # Keep complete pairs. A single oversized pair is not useful bounded context.
        if len(source) + len(target) > limit:
            self.clear()
            return
        self._items.append((source, target, now))
        while sum(len(src) + len(tgt) for src, tgt, _ in self._items) > limit:
            self._items.popleft()
        self._language, self._last_time = language, now
