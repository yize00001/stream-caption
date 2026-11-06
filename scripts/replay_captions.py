"""Replay local diagnostics without recording, loading a model or calling translation APIs."""

import argparse
import json
from collections import Counter
from pathlib import Path

from stream_caption.captions import CaptionAssembler
from stream_caption.quality import SpeechSegment, SpeechWord
from stream_caption.settings import Settings


def replay(records):
    settings = Settings()
    assembler = CaptionAssembler(
        max_buffer_seconds=settings.stt.caption_buffer_seconds,
        silence_seconds=settings.stt.caption_silence_seconds,
        stability_passes=settings.stt.caption_stability_passes,
        min_text_length=settings.audio.min_text_length,
    )
    updates = []
    windows = word_windows = 0
    for record in records:
        if record.get('event') == 'audio_gap':
            assembler.clear()
        elif record.get('event') == 'audio_window':
            updates.extend(assembler.advance(record['window_end_sample'] / 16000))
        elif record.get('event') == 'stt':
            if record.get('status') in ('obsolete', 'slow_stt'):
                assembler.clear()
                continue
            windows += 1
            segments = []
            has_words = False
            for raw in record.get('segments', []):
                values = dict(raw)
                values['words'] = tuple(SpeechWord(**word) for word in (raw.get('words') or ()))
                has_words = has_words or bool(values['words'])
                segment = SpeechSegment(**values)
                if not segment.rejection_reason(settings.stt):
                    segments.append(segment)
            word_windows += int(has_words)
            updates.extend(assembler.observe(segments, record['window_start_sample'],
                                             record['window_end_sample'], record['language']))
    latest = {update.caption_id: update for update in updates}
    return {
        'input_stt_windows': windows,
        'windows_with_word_timestamps': word_windows,
        'segment_only_windows': windows - word_windows,
        'updates': len(updates),
        'unique_caption_ids': len(latest),
        'finalized_captions': sum(update.final for update in latest.values()),
        'revisions_to_existing_caption': len(updates) - len(latest),
        'update_reasons': dict(Counter(update.reason for update in updates)),
        'is_accuracy_evaluation': False,
        'notes': [
            'Old rolling windows do not contain the longer audio used by live stabilization.',
            'window_shift events seal text to avoid losing coverage during replay.',
            'CJK and segment-only inputs retain complete segments; timing drift may preserve overlaps.',
            'This validates state transitions, not recognition quality or API cost savings.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('diagnostics', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    with args.diagnostics.open(encoding='utf-8-sig') as file:
        summary = replay(json.loads(line) for line in file if line.strip())
    summary['input_file'] = str(args.diagnostics.resolve())
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + '\n', encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
