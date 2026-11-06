"""Exercise pipeline boundaries without opening devices, loading models or calling APIs."""

import sys
import json
import tempfile
import threading
import types
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from stream_caption import __main__ as app
from stream_caption.audio import AudioChunk, PauseState, SAMPLE_RATE
from stream_caption.settings import Settings, SettingsError
from stream_caption.quality import SpeechSegment, SpeechWord, Transcription


class FakeMic:
    def __init__(self):
        self.closed = False
        self.active = False
        self.closed_while_active = False
        self.tick = threading.Event()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed_while_active = self.active
        self.closed = True

    def record(self, numframes):
        if self.closed:
            raise AssertionError('read after recorder closed')
        self.active = True
        try:
            self.tick.wait(0.005)
            return np.ones((numframes, 2), dtype=np.float32)
        finally:
            self.active = False


class PipelineTests(unittest.TestCase):
    def run_pipeline(self, transcribe, translate, overlay=None, pause=None, stop_after=1,
                     configure=None, recording_factory=None):
        settings = Settings()
        settings.audio.window_seconds = 2
        settings.audio.step_seconds = 1
        settings.stt.model = 'small'
        settings.stt.stabilize_captions = False  # Existing lifecycle tests exercise legacy mode.
        if configure:
            configure(settings)
        stop = threading.Event()
        pause = pause or PauseState()
        mic = FakeMic()
        overlay = overlay or Mock()
        def on_push(*args):
            if overlay.push.call_count >= stop_after:
                stop.set()

        overlay.push.side_effect = on_push
        def on_upsert(*args, **kwargs):
            if overlay.upsert.call_count >= stop_after:
                stop.set()

        overlay.upsert.side_effect = on_upsert
        translator = types.ModuleType('stream_caption.translator')
        def detailed(*args, **kwargs):
            text = translate(*args, **kwargs)
            return types.SimpleNamespace(text=text, backend='fake',
                                         status='ok' if text else 'unavailable', errors=())

        def recognize(model, audio, **kwargs):
            result = transcribe(model, audio, **kwargs)
            if isinstance(result, Transcription):
                return result
            text, language = result
            return Transcription((SpeechSegment(text, 0, len(audio) / SAMPLE_RATE,
                                                 -0.1, 0.01, 1.0),), language, 0.99, 2.0)

        translator.translate_detailed = detailed
        timer = threading.Timer(3, stop.set)
        with ExitStack() as stack:
            stack.enter_context(patch.dict(sys.modules, {'stream_caption.translator': translator}))
            stack.enter_context(patch.object(app.sc, 'default_speaker', return_value=types.SimpleNamespace(id='fake', name='fake')))
            stack.enter_context(patch.object(app.sc, 'get_microphone', return_value=types.SimpleNamespace(recorder=lambda **kwargs: mic)))
            stack.enter_context(patch.object(app, '_load_model', return_value=object()))
            stack.enter_context(patch.object(app, '_transcribe', side_effect=recognize))
            if recording_factory:
                stack.enter_context(patch.object(app, 'recording', recording_factory))
            timer.start()
            try:
                app._pipeline(settings, overlay, stop, pause)
            finally:
                stop.set()
                timer.cancel()
                timer.join()
                self.assertTrue(mic.closed)
                self.assertFalse(mic.closed_while_active)
                self.assertFalse(any(t.name == 'audio-record' and t.is_alive() for t in threading.enumerate()))
        return overlay

    def test_two_second_window_reaches_stt(self):
        def transcribe(model, audio, **kwargs):
            self.assertEqual(len(audio), SAMPLE_RATE * 2)
            return 'fresh sentence', 'en'

        overlay = self.run_pipeline(transcribe, lambda *args, **kwargs: 'translation')
        overlay.push.assert_called_once_with('fresh sentence', 'translation')

    def test_pause_resume_during_stt_discards_result(self):
        pause = PauseState()
        calls = []
        translate = Mock(return_value='translation')

        def transcribe(model, audio, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                pause.set()
                pause.clear()
                return 'obsolete sentence', 'en'
            self.assertEqual(kwargs['prev_text'], '')
            return 'fresh sentence', 'en'

        overlay = self.run_pipeline(transcribe, translate, pause=pause)
        self.assertEqual(len(calls), 2)
        translate.assert_called_once()
        overlay.push.assert_called_once_with('fresh sentence', 'translation')

    def test_pause_resume_during_translation_discards_result(self):
        pause = PauseState()
        calls = []

        def translate(text, **kwargs):
            calls.append(text)
            if len(calls) == 2:
                self.assertEqual(kwargs['context_source'], 'previous sentence')
                self.assertEqual(kwargs['context_target'], 'fresh translation')
                pause.set()
                pause.clear()
                return 'obsolete translation'
            self.assertEqual(kwargs['context_source'], '')
            self.assertEqual(kwargs['context_target'], '')
            return 'fresh translation'

        # The repeated first sentence after resume must not be treated as duplicate.
        transcribe = Mock(side_effect=[('previous sentence', 'ja'),
                                       ('obsolete sentence', 'ja'),
                                       ('previous sentence', 'ja')])
        overlay = self.run_pipeline(transcribe, translate, pause=pause, stop_after=2)
        self.assertEqual(len(calls), 3)
        self.assertEqual(transcribe.call_args.kwargs['prev_text'], '')
        self.assertEqual(overlay.push.call_count, 2)
        for call in overlay.push.call_args_list:
            self.assertEqual(call.args, ('previous sentence', 'fresh translation'))

    def test_pipeline_exception_cleans_reader_before_next_run(self):
        with self.assertRaisesRegex(RuntimeError, 'STT failed'):
            self.run_pipeline(Mock(side_effect=RuntimeError('STT failed')), Mock())
        overlay = self.run_pipeline(lambda *args, **kwargs: ('fresh sentence', 'en'),
                                    lambda *args, **kwargs: 'translation')
        overlay.push.assert_called_once()

    def test_invalid_config_stops_before_ui_or_pipeline(self):
        with patch.object(app, 'load_settings', side_effect=SettingsError('audio.step_seconds: invalid')), \
                patch.object(app, 'SubtitleOverlay') as overlay:
            with self.assertRaisesRegex(SystemExit, 'audio.step_seconds'):
                app.main()
            overlay.assert_not_called()

    def test_tray_failure_stops_hotkey_and_waits_for_pipeline_cleanup(self):
        with patch.object(app, 'load_settings', return_value=Settings()), \
                patch.object(app, 'SubtitleOverlay'), \
                patch.object(app.threading, 'Thread') as worker, \
                patch.object(app._kb, 'Listener') as listener, \
                patch.object(app.pystray, 'Icon') as tray:
            tray.return_value.run.side_effect = RuntimeError('tray failed')
            with self.assertRaisesRegex(RuntimeError, 'tray failed'):
                app.main()
            worker.return_value.start.assert_called_once()
            worker.return_value.join.assert_called_once()
            self.assertTrue(worker.call_args.kwargs['args'][2].is_set())
            listener.return_value.stop.assert_called_once()

    def test_failed_translation_preserves_source_and_does_not_pollute_context(self):
        transcribe = Mock(side_effect=[('failed source', 'en'), ('fresh source', 'en')])
        calls = []

        def translate(text, **kwargs):
            calls.append(text)
            self.assertEqual(kwargs['context_source'], '')
            return '' if len(calls) == 1 else 'fresh translation'

        overlay = self.run_pipeline(transcribe, translate, stop_after=2)
        self.assertEqual(overlay.push.call_args_list[0].args,
                         ('failed source', '[翻譯暫時不可用]'))
        self.assertEqual(overlay.push.call_args_list[1].args,
                         ('fresh source', 'fresh translation'))

    def test_rejected_low_quality_speech_never_reaches_translation(self):
        transcribe = Mock(side_effect=[
            Transcription((SpeechSegment('invented greeting', 0, 1, -2, 0.9, 1),),
                          'ja', 0.9, 1),
            ('real sentence', 'ja')])
        translate = Mock(return_value='translation')
        overlay = self.run_pipeline(transcribe, translate)
        translate.assert_called_once()
        overlay.push.assert_called_once_with('real sentence', 'translation')

    def test_gap_requires_fresh_full_window_and_clears_context(self):
        @contextmanager
        def scripted_recording(mic, audio_q, pause, step):
            for index in (0, 1, 4, 5):
                audio_q.put_nowait(AudioChunk(0, index * SAMPLE_RATE,
                                              np.full(SAMPLE_RATE, index + 1, dtype=np.float32),
                                              float(index)))
            yield types.SimpleNamespace(is_alive=lambda: True)

        windows = []

        def transcribe(model, audio, **kwargs):
            windows.append(audio.copy())
            return f'sentence {len(windows)}', 'en'

        def translate(text, **kwargs):
            self.assertEqual(kwargs['context_source'], '')
            return 'translation'

        self.run_pipeline(transcribe, translate, stop_after=2,
                          recording_factory=scripted_recording)
        self.assertEqual(len(windows), 2)
        np.testing.assert_array_equal(windows[0], np.repeat([1, 2], SAMPLE_RATE))
        np.testing.assert_array_equal(windows[1], np.repeat([5, 6], SAMPLE_RATE))

    def test_opt_in_diagnostics_include_segments_backend_and_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            module_path = str(Path(directory) / 'src' / 'stream_caption' / '__main__.py')
            with patch.object(app, '__file__', module_path):
                self.run_pipeline(lambda *args, **kwargs: ('source text', 'en'),
                                  lambda *args, **kwargs: 'translation',
                                  configure=lambda s: setattr(s.log, 'diagnostics_enabled', True))
            paths = list((Path(directory) / 'logs').glob('*.diagnostics.jsonl'))
            self.assertEqual(len(paths), 1)
            records = [json.loads(line) for line in paths[0].read_text(encoding='utf-8').splitlines()]
            self.assertEqual(records[0]['status'], 'accepted')
            self.assertEqual(records[0]['segments'][0]['avg_logprob'], -0.1)
            self.assertEqual(records[1]['backend'], 'fake')
            self.assertEqual(records[1]['translated_text'], 'translation')

    def test_diagnostics_disabled_does_not_create_log(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(app, '__file__', str(Path(directory) / 'src' / 'pkg' / '__main__.py')):
                self.run_pipeline(lambda *args, **kwargs: ('source text', 'en'),
                                  lambda *args, **kwargs: 'translation')
            self.assertFalse((Path(directory) / 'logs').exists())

    def test_transcribe_keeps_scores_and_defaults_to_no_previous_text_prompt(self):
        model = Mock()
        model.transcribe.return_value = (
            iter([SpeechSegment('こんにちは', 0, 1, -0.2, 0.1, 1.2)]),
            types.SimpleNamespace(language='ja', language_probability=0.98, duration_after_vad=1))
        result = app._transcribe(model, np.ones(SAMPLE_RATE), prev_text='previous sentence')
        self.assertEqual(result.segments[0].avg_logprob, -0.2)
        self.assertEqual(result.language_probability, 0.98)
        self.assertIsNone(model.transcribe.call_args.kwargs['initial_prompt'])
        self.assertFalse(model.transcribe.call_args.kwargs['condition_on_previous_text'])

    def test_stabilized_caption_grows_buffer_and_revises_same_overlay_entry(self):
        lengths = []
        sentences = iter(['I can attend', 'I cannot attend', 'I cannot attend tomorrow'])

        def transcribe(model, audio, **kwargs):
            lengths.append(len(audio) / SAMPLE_RATE)
            self.assertTrue(kwargs['word_timestamps'])
            return next(sentences), 'en'

        def translate(text, **kwargs):
            self.assertEqual(kwargs['context_source'], '')
            return 'translated ' + text

        overlay = self.run_pipeline(transcribe, translate, stop_after=2,
                                    configure=lambda s: setattr(s.stt, 'stabilize_captions', True))
        self.assertEqual(lengths, [2, 3, 4])
        first, second = overlay.upsert.call_args_list
        self.assertEqual(first.args[0], second.args[0])
        self.assertEqual(first.args[1], 'I cannot attend')
        self.assertEqual(second.args[1], 'I cannot attend tomorrow')
        overlay.push.assert_not_called()

    def test_identical_final_caption_reuses_translation(self):
        def configure(settings):
            settings.stt.stabilize_captions = True
            settings.stt.caption_buffer_seconds = 3
            settings.stt.caption_stability_passes = 1

        translate = Mock(return_value='translation')
        overlay = self.run_pipeline(lambda *args, **kwargs: ('unchanged sentence', 'en'),
                                    translate, stop_after=2, configure=configure)
        translate.assert_called_once()
        self.assertEqual(overlay.upsert.call_args_list[0].args,
                         overlay.upsert.call_args_list[1].args)

    def test_only_final_caption_becomes_context_for_next_utterance(self):
        def configure(settings):
            settings.stt.stabilize_captions = True
            settings.stt.caption_buffer_seconds = 3
            settings.stt.caption_stability_passes = 1

        responses = iter([
            ('draft sentence', 'en'),
            ('completed sentence', 'en'),
            Transcription((SpeechSegment('old new sentence', 0, 2, -0.1, 0.01, 1.0,
                           (SpeechWord('old', 0, 1, 0.9),
                            SpeechWord(' new sentence', 1, 2, 0.9))),), 'en', 0.99, 2),
        ])
        calls = []

        def translate(text, **kwargs):
            calls.append(kwargs['context_source'])
            return 'translation of ' + text

        overlay = self.run_pipeline(lambda *args, **kwargs: next(responses), translate,
                                    stop_after=3, configure=configure)
        self.assertEqual(calls, ['', '', 'completed sentence'])
        self.assertEqual(overlay.upsert.call_args_list[-1].args[1], 'new sentence')

    def test_pause_discards_unpublished_stabilization_buffer(self):
        pause = PauseState()
        count = 0

        def transcribe(model, audio, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                pause.set()
                pause.clear()
            return ('old speech' if count <= 2 else 'new speech'), 'en'

        overlay = self.run_pipeline(transcribe, lambda *args, **kwargs: 'translation',
                                    pause=pause,
                                    configure=lambda s: setattr(s.stt, 'stabilize_captions', True))
        self.assertEqual(count, 4)
        overlay.upsert.assert_called_once()
        self.assertEqual(overlay.upsert.call_args.args[1], 'new speech')

    def test_no_speech_window_finalizes_pending_caption(self):
        responses = iter([('complete sentence', 'en'), Transcription((), 'en', 0.99, 0)])
        translate = Mock(return_value='translation')
        overlay = self.run_pipeline(lambda *args, **kwargs: next(responses), translate,
                                    configure=lambda s: setattr(s.stt, 'stabilize_captions', True))
        overlay.upsert.assert_called_once()
        self.assertEqual(overlay.upsert.call_args.args[1], 'complete sentence')
        translate.assert_called_once()

    def test_live_word_alignment_is_preserved_from_whisper(self):
        model = Mock()
        model.transcribe.return_value = (
            iter([types.SimpleNamespace(text=' speech', start=0.2, end=1.3,
                  avg_logprob=-0.2, no_speech_prob=0.1, compression_ratio=1.1,
                  words=[types.SimpleNamespace(word=' speech', start=0.2, end=1.3, probability=0.95)])]),
            types.SimpleNamespace(language='en', language_probability=0.99, duration_after_vad=1.3))
        result = app._transcribe(model, np.ones(SAMPLE_RATE * 2), word_timestamps=True)
        self.assertTrue(model.transcribe.call_args.kwargs['word_timestamps'])
        self.assertEqual(result.segments[0].words, (SpeechWord(' speech', 0.2, 1.3, 0.95),))


if __name__ == '__main__':
    unittest.main()
