import unittest

from stream_caption.audio import SAMPLE_RATE
from stream_caption.captions import CaptionAssembler
from stream_caption.quality import SpeechSegment, SpeechWord


def segment(text, start, end, words=()):
    return SpeechSegment(text, start, end, -0.1, 0.05, 1.0, words)


class CaptionAssemblerTests(unittest.TestCase):
    def observe(self, assembler, text, end, *, language='ja', speech_end=None):
        return assembler.observe([segment(text, 0, end if speech_end is None else speech_end)],
                                 0, int(end * SAMPLE_RATE), language)

    def test_waits_then_keeps_negation_correction(self):
        assembler = CaptionAssembler()
        self.assertEqual(self.observe(assembler, '明日は参加できます', 2), [])
        updates = self.observe(assembler, '明日は参加できません', 4)
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].text, '明日は参加できません')
        self.assertFalse(updates[0].final)

    def test_published_number_correction_revises_same_caption(self):
        assembler = CaptionAssembler(stability_passes=1)
        first = self.observe(assembler, 'The price is 100 dollars.', 2)[0]
        second = self.observe(assembler, 'The price is 900 dollars.', 4)[0]
        self.assertEqual(first.caption_id, second.caption_id)
        self.assertGreater(second.revision, first.revision)
        self.assertEqual(second.text, 'The price is 900 dollars.')

    def test_silence_finalizes_once_and_short_question_survives(self):
        assembler = CaptionAssembler()
        self.assertEqual(self.observe(assembler, '誰から', 2), [])
        updates = assembler.advance(4)
        self.assertEqual(updates[0].text, '誰から')
        self.assertTrue(updates[0].final)
        self.assertEqual(assembler.advance(6), [])

    def test_silence_inside_observation_finishes_complete_caption(self):
        assembler = CaptionAssembler()
        self.assertEqual(self.observe(assembler, 'こんにちは', 4, speech_end=2), [])
        updates = self.observe(assembler, 'こんにちは', 6, speech_end=2)
        self.assertEqual(len(updates), 1)
        self.assertTrue(updates[0].final)
        self.assertEqual(updates[0].reason, 'silence')

    def test_unconfirmed_single_character_is_not_published(self):
        assembler = CaptionAssembler()
        self.assertEqual(self.observe(assembler, 'あ', 4, speech_end=1), [])

    def test_repeated_identical_speech_at_different_times_is_preserved(self):
        assembler = CaptionAssembler(stability_passes=1)
        first = assembler.observe([segment('はいはい', 0, 1)], 0, 4 * SAMPLE_RATE, 'ja')[0]
        second = assembler.observe([segment('はいはい', 0, 1)], 5 * SAMPLE_RATE,
                                   9 * SAMPLE_RATE, 'ja')[0]
        self.assertEqual(first.text, second.text)
        self.assertNotEqual(first.caption_id, second.caption_id)

    def test_word_times_remove_sealed_context_and_keep_complete_new_word(self):
        assembler = CaptionAssembler(stability_passes=1)
        first = assembler.observe([segment('old sentence', 0, 2)], 0,
                                  4 * SAMPLE_RATE, 'en')[0]
        words = (SpeechWord('old sentence', 0, 2, 0.9),
                 SpeechWord(' new word', 2, 3, 0.9))
        updates = assembler.observe([segment('old sentence new word', 0, 3, words)],
                                   0, 4 * SAMPLE_RATE, 'en')
        self.assertEqual(updates[0].text, 'new word')
        self.assertNotEqual(first.caption_id, updates[0].caption_id)

    def test_multiple_utterances_in_one_window_keep_separate_ids(self):
        assembler = CaptionAssembler(stability_passes=1)
        updates = assembler.observe([segment('first sentence', 0, 1),
                                     segment('second sentence', 2, 3)],
                                    0, 4 * SAMPLE_RATE, 'en')
        self.assertEqual([u.text for u in updates], ['first sentence', 'second sentence'])
        self.assertNotEqual(updates[0].caption_id, updates[1].caption_id)

    def test_buffer_limit_is_bounded_even_without_silence(self):
        updates = self.observe(CaptionAssembler(), 'continuous speech', 8)
        self.assertTrue(updates[0].final)
        self.assertEqual(updates[0].reason, 'buffer_limit')

    def test_same_observation_does_not_count_as_two_passes(self):
        assembler = CaptionAssembler()
        self.assertEqual(self.observe(assembler, 'pending speech', 2), [])
        self.assertEqual(self.observe(assembler, 'pending speech', 2), [])

    def test_clear_uses_new_id_and_discards_unfinished_text(self):
        assembler = CaptionAssembler(stability_passes=1)
        first = self.observe(assembler, 'old speech', 2)[0]
        assembler.clear()
        second = self.observe(assembler, 'new speech', 2)[0]
        self.assertNotEqual(first.caption_id, second.caption_id)
        self.assertEqual(second.text, 'new speech')

    def test_language_change_seals_previous_language(self):
        assembler = CaptionAssembler(stability_passes=1)
        self.observe(assembler, 'previous language', 2, language='en')
        updates = assembler.observe([segment('別の言語です', 0, 1)],
                                    2 * SAMPLE_RATE, 6 * SAMPLE_RATE, 'ja')
        self.assertEqual([u.language for u in updates], ['en', 'ja'])

    def test_japanese_subword_before_seal_is_not_deleted_by_time(self):
        # Real test failure: a prior hypothesis placed different speech at 1.73–2.31.
        # The corrected first kana later ended at 2.29 and was incorrectly deleted.
        assembler = CaptionAssembler(stability_passes=1)
        assembler.observe([segment('ちょっとあの', 1.73, 2.31)], 0, 4 * SAMPLE_RATE, 'ja')
        words = (SpeechWord('め', 1.73, 2.29, 0.22),
                 SpeechWord('っちゃ', 2.68, 4.48, 0.98),
                 SpeechWord('話すかも', 4.48, 5.18, 0.99))
        updates = assembler.observe([segment('めっちゃ話すかも', 1.73, 5.18, words)],
                                     0, 6 * SAMPLE_RATE, 'ja')
        self.assertEqual(updates[0].text, 'めっちゃ話すかも')

    def test_japanese_segment_crossing_seal_stays_whole(self):
        assembler = CaptionAssembler(stability_passes=1)
        assembler.observe([segment('飲んだ挙句', 0, 2)], 0, 4 * SAMPLE_RATE, 'ja')
        words = (SpeechWord('挙', 1.8, 1.99, 0.95), SpeechWord('句', 2.01, 2.2, 0.99),
                 SpeechWord('どうなった', 2.2, 3.2, 0.9))
        updates = assembler.observe([segment('挙句どうなった', 1.8, 3.2, words)],
                                     0, 5 * SAMPLE_RATE, 'ja')
        self.assertEqual(updates[0].text, '挙句どうなった')

    def test_confirmed_identical_japanese_segment_is_suppressed(self):
        assembler = CaptionAssembler(stability_passes=1)
        assembler.observe([segment('同じ発言', 0, 2)], 0, 4 * SAMPLE_RATE, 'ja')
        self.assertEqual(assembler.observe([segment('同じ発言', 0.02, 2.03)],
                                          0, 5 * SAMPLE_RATE, 'ja'), [])

    def test_default_does_not_split_first_hypothesis_on_internal_timing_gap(self):
        assembler = CaptionAssembler()
        segments = [segment('前半の話', 0, 1), segment('まだ続く話', 2, 3.9)]
        self.assertEqual(assembler.observe(segments, 0, 4 * SAMPLE_RATE, 'ja'), [])
        updates = assembler.observe([segment('前半の話まだ続く話です', 0, 5.9)],
                                     0, 6 * SAMPLE_RATE, 'ja')
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].text, '前半の話まだ続く話です')


if __name__ == '__main__':
    unittest.main()
