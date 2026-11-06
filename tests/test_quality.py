import json
import unittest

from stream_caption.audio import SAMPLE_RATE
from stream_caption.quality import SpeechSegment, Transcription, SegmentHistory, TranslationContext
from stream_caption.settings import STTSettings, TranslationSettings


def speech(text, start=0, end=1, logprob=-0.1, no_speech=0.01, compression=1.0):
    return SpeechSegment(text, start, end, logprob, no_speech, compression)


class QualityTests(unittest.TestCase):
    def test_joint_low_quality_evidence_rejected_without_banning_greetings(self):
        settings = STTSettings()
        self.assertEqual(speech('こんにちは').rejection_reason(settings), '')
        self.assertEqual(speech('こんばんは', logprob=-1.5, no_speech=0.8)
                         .rejection_reason(settings), 'low_probability_and_no_speech')
        self.assertEqual(speech('repeating', logprob=-1.5, compression=3)
                         .rejection_reason(settings), 'low_probability_and_repetition')
        self.assertEqual(speech('quiet speech', logprob=-1.1).rejection_reason(settings), '')

    def test_filter_can_be_disabled_but_invalid_timestamps_still_rejected(self):
        settings = STTSettings(quality_filter=False)
        self.assertEqual(speech('text', logprob=-2, no_speech=0.9).rejection_reason(settings), '')
        self.assertEqual(speech('text', end=0).rejection_reason(settings), 'invalid_segment')

    def test_nonfinite_metrics_are_rejected_and_diagnostics_are_valid_json(self):
        segment = speech('text', logprob=float('nan'))
        self.assertEqual(segment.rejection_reason(STTSettings()), 'invalid_segment')
        result = Transcription((segment,), 'ja', 0.9, 1)
        encoded = json.dumps(result.diagnostics(), allow_nan=False)
        self.assertIsNone(json.loads(encoded)['segments'][0]['avg_logprob'])

    def test_negation_and_number_corrections_survive_overlapping_audio(self):
        for previous, corrected in [
            ('今日は参加できます', '今日は参加できません'),
            ('I can attend the meeting.', 'I cannot attend the meeting.'),
            ('The price is 100 dollars.', 'The price is 900 dollars.'),
        ]:
            with self.subTest(corrected=corrected):
                history = SegmentHistory()
                history.commit([speech(previous, 1, 2)], 0)
                segments = [speech(corrected, 0, 1)]
                self.assertEqual(history.select(segments, SAMPLE_RATE), segments)

    def test_only_same_text_in_same_audio_is_suppressed(self):
        history = SegmentHistory()
        history.commit([speech('Hello!', 1, 2)], 0)
        self.assertEqual(history.select([speech('Hello!', 0, 1)], SAMPLE_RATE), [])
        repeated_later = [speech('Hello!', 1, 2)]
        self.assertEqual(history.select(repeated_later, SAMPLE_RATE), repeated_later)

    def test_new_segment_survives_partially_overlapping_window(self):
        history = SegmentHistory()
        history.commit([speech('old', 1, 2)], 0)
        fresh = speech('new', 1, 2)
        self.assertEqual(history.select([speech('old'), fresh], SAMPLE_RATE), [fresh])

    def test_context_keeps_recent_pairs_with_limits(self):
        context = TranslationContext(TranslationSettings(context_max_sentences=2))
        for index in range(3):
            context.add(f'source {index}', f'target {index}', 'en', index)
        self.assertEqual(context.get('en', 3), ('source 1\nsource 2', 'target 1\ntarget 2'))

    def test_context_expires_each_pair_and_resets_on_language_change(self):
        context = TranslationContext(TranslationSettings(context_max_age_seconds=15))
        context.add('old', 'old target', 'ja', 0)
        context.add('recent', 'recent target', 'ja', 10)
        self.assertEqual(context.get('ja', 20), ('recent', 'recent target'))
        self.assertEqual(context.get('en', 21), ('', ''))
        self.assertEqual(context.get('ja', 22), ('', ''))
        context.add('new', 'target', 'ja', 23)
        self.assertEqual(context.get('ja', 40), ('', ''))

    def test_context_character_limit_keeps_complete_pairs(self):
        context = TranslationContext(TranslationSettings(context_max_characters=10))
        context.add('one', 'ONE', 'en', 0)
        context.add('two', 'TWO', 'en', 1)
        self.assertEqual(context.get('en', 2), ('two', 'TWO'))
        context.add('oversized source', 'oversized target', 'en', 3)
        self.assertEqual(context.get('en', 4), ('', ''))


if __name__ == '__main__':
    unittest.main()
