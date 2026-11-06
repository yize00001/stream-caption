"""Revise a bounded utterance hypothesis, then seal it on silence or a buffer limit."""

import math
import re
import uuid
from collections import deque
from dataclasses import dataclass

from stream_caption.audio import SAMPLE_RATE


@dataclass(frozen=True)
class CaptionUpdate:
    caption_id: str | None
    text: str
    language: str
    final: bool
    revision: int
    reason: str


@dataclass(frozen=True)
class _Piece:
    text: str
    start: float
    end: float


class CaptionAssembler:
    """Each observation must include the whole unsealed utterance's audio.

    Japanese/Chinese/Korean alignment entries may be subword pieces. Keep complete
    segments for these languages instead of deleting syllables by estimated time.
    """

    def __init__(self, *, max_buffer_seconds=8, silence_seconds=0.8,
                 stability_passes=2, min_text_length=4):
        self.max_buffer_seconds = max_buffer_seconds
        self.silence_seconds = silence_seconds
        self.stability_passes = stability_passes
        self.min_text_length = min_text_length
        self._prefix = uuid.uuid4().hex
        self._counter = 0
        self._sealed_until = 0.0
        self._pending = None
        self._sealed_pieces = deque(maxlen=32)

    @property
    def pending(self):
        return self._pending is not None

    def clear(self):
        # Preserve the ID counter so a pause cannot overwrite an older caption.
        self._pending = None
        self._sealed_until = 0.0
        self._sealed_pieces.clear()

    def retain_from_sample(self, overlap_seconds):
        return max(0, int((self._sealed_until - overlap_seconds) * SAMPLE_RATE))

    def _was_sealed(self, piece):
        key = re.sub(r'\s+', '', piece.text).strip('。.!?！？').casefold()
        return any(
            key == re.sub(r'\s+', '', old.text).strip('。.!?！？').casefold()
            and min(piece.end, old.end) - max(piece.start, old.start)
            >= 0.5 * min(piece.end - piece.start, old.end - old.start)
            for old in self._sealed_pieces
        )

    def _pieces(self, segments, offset, language):
        pieces = []
        for segment in segments:
            if segment.words and language not in ('ja', 'zh', 'ko'):
                for word in segment.words:
                    start, end = offset + word.start, offset + word.end
                    if (not math.isfinite(start) or not math.isfinite(end)
                            or end < start or end <= self._sealed_until + 0.02):
                        continue
                    # Keep complete words, including words that straddle the seal.
                    pieces.append(_Piece(word.word, start, end))
            else:
                # Timing drift can place the first kana of a corrected word before
                # the previous seal. Suppress only identical, overlapping segments.
                piece = _Piece(segment.text, offset + segment.start, offset + segment.end)
                if segment.text.strip() and not self._was_sealed(piece):
                    pieces.append(piece)
        return pieces

    def _emit(self, final, reason):
        pending = self._pending
        text = ''.join(piece.text for piece in pending['pieces']).strip()
        length = len(text)
        if not text:
            return []
        if not final and (pending['passes'] < self.stability_passes
                          or length < self.min_text_length):
            return []
        if final and length < 2 and pending['passes'] < self.stability_passes:
            return []
        if text == pending['published_text'] and not final:
            return []
        pending['revision'] += 1
        pending['published_text'] = text
        return [CaptionUpdate(pending['id'], text, pending['language'], final,
                              pending['revision'], reason)]

    def _seal(self, reason):
        if not self.pending:
            return []
        updates = self._emit(True, reason)
        self._sealed_until = max(self._sealed_until, self._pending['pieces'][-1].end)
        if updates:
            self._sealed_pieces.extend(self._pending['pieces'])
        self._pending = None
        return updates

    def advance(self, audio_end_seconds):
        """A silent input window can seal a pending caption without another API call."""
        if self.pending and audio_end_seconds - self._pending['pieces'][-1].end >= self.silence_seconds:
            return self._seal('silence')
        return []

    def observe(self, segments, window_start_sample, window_end_sample, language):
        start, end = window_start_sample / SAMPLE_RATE, window_end_sample / SAMPLE_RATE
        updates = []
        if self.pending and language != self._pending['language']:
            updates.extend(self._seal('language_change'))
        # Do not silently erase old text when replaying a shifted/shorter window.
        if self.pending and start > self._pending['pieces'][0].start + 0.05:
            updates.extend(self._seal('window_shift'))
        pieces = self._pieces(segments, start, language)
        if not pieces:
            return updates + self.advance(end)

        groups = []
        for piece in pieces:
            if (not groups or (self.stability_passes == 1
                               and piece.start - groups[-1][-1].end >= self.silence_seconds)):
                groups.append([])
            groups[-1].append(piece)

        for index, group in enumerate(groups):
            if self.pending and group[0].start - self._pending['pieces'][-1].end >= self.silence_seconds:
                updates.extend(self._seal('speech_gap'))
            if not self.pending:
                self._counter += 1
                self._pending = {'id': f'{self._prefix}:{self._counter}', 'pieces': group,
                                 'language': language, 'passes': 1, 'observed_end': end,
                                 'published_text': None, 'revision': 0}
            else:
                if end > self._pending['observed_end']:
                    self._pending['passes'] += 1
                # Re-recognition includes the full pending audio, so corrections replace
                # the whole hypothesis; no fuzzy text deletion or phrase substitution.
                self._pending['pieces'] = group
                self._pending['observed_end'] = end

            if index < len(groups) - 1:
                updates.extend(self._seal('speech_gap'))
            elif (end - group[-1].end >= self.silence_seconds
                  and self._pending['passes'] >= self.stability_passes):
                updates.extend(self._seal('silence'))
            elif end - start >= self.max_buffer_seconds:
                updates.extend(self._seal('buffer_limit'))
            else:
                updates.extend(self._emit(False, 'revision'))
        return updates
