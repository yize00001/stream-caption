import tempfile
import unittest
from pathlib import Path

from stream_caption.settings import Settings, SettingsError, load_settings


class SettingsTests(unittest.TestCase):
    def load_text(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.toml"
            path.write_text(text, encoding="utf-8")
            return load_settings(path)

    def test_missing_file_uses_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(load_settings(Path(directory) / "missing.toml"), Settings())

    def test_example_and_low_latency_settings(self):
        load_settings(Path(__file__).parents[1] / "settings.toml.example")
        settings = self.load_text('[audio]\nwindow_seconds = 2\nstep_seconds = 1\n')
        self.assertEqual((settings.audio.window_seconds, settings.audio.step_seconds), (2, 1))

    def test_invalid_settings_report_specific_key(self):
        cases = [
            ('[audio]\nstep_seconds = 0', 'audio.step_seconds'),
            ('[audio]\nwindow_seconds = -1', 'audio.window_seconds'),
            ('[audio]\nwindow_seconds = 1\nstep_seconds = 2', 'audio.window_seconds'),
            ('[audio]\nwindow_seconds = 5\nstep_seconds = 2', 'audio.window_seconds'),
            ('[audio]\nstep_seconds = 0.5', 'audio.step_seconds'),
            ('[audio]\nstep_seconds = true', 'audio.step_seconds'),
            ('[audio]\nmin_text_length = 0', 'audio.min_text_length'),
            ('[audio]\nsilence_threshold = nan', 'audio.silence_threshold'),
            ('[audio]\nsilence_threshold = 2', 'audio.silence_threshold'),
            ('[audio]\ndevice = 1', 'audio.device'),
            ('[overlay]\nopacity = inf', 'overlay.opacity'),
            ('[overlay]\nauto_hide_enabled = "false"', 'overlay.auto_hide_enabled'),
            ('[overlay]\nopacity = -0.1', 'overlay.opacity'),
            ('[overlay]\nwidth = 0', 'overlay.width'),
            ('[overlay]\nbg_color = "invalid"', 'overlay.bg_color'),
            ('[stt]\nbeam_size = "5"', 'stt.beam_size'),
            ('[stt]\nvocab = [1]', 'stt.vocab'),
            ('[stt]\nquality_filter = "true"', 'stt.quality_filter'),
            ('[stt]\nmin_avg_logprob = 1', 'stt.min_avg_logprob'),
            ('[stt]\nmax_no_speech_prob = 1.1', 'stt.max_no_speech_prob'),
            ('[stt]\nmax_compression_ratio = 0', 'stt.max_compression_ratio'),
            ('[stt]\nstabilize_captions = "true"', 'stt.stabilize_captions'),
            ('[stt]\ncaption_buffer_seconds = 0', 'stt.caption_buffer_seconds'),
            ('[stt]\ncaption_silence_seconds = 0', 'stt.caption_silence_seconds'),
            ('[stt]\ncaption_stability_passes = -1', 'stt.caption_stability_passes'),
            ('[translation]\ntarget_lang = ""', 'translation.target_lang'),
            ('[translation]\ncontext_max_sentences = 0', 'translation.context_max_sentences'),
            ('[translation]\ncontext_max_characters = -1', 'translation.context_max_characters'),
            ('[translation]\ncontext_max_age_seconds = 0', 'translation.context_max_age_seconds'),
            ('[translation]\nmodel_type = "invalid"', 'translation.model_type'),
            ('[log]\nenabled = "false"', 'log.enabled'),
            ('[log]\ndiagnostics_enabled = 1', 'log.diagnostics_enabled'),
            ('[hotkey]\ntoggle = ""', 'hotkey.toggle'),
            ('[audio]\nstep_second = 1', 'audio.step_second'),
            ('[audo]', 'audo'),
            ('audio = 1', 'audio'),
        ]
        for text, key in cases:
            with self.subTest(text=text), self.assertRaises(SettingsError) as error:
                self.load_text(text)
            self.assertIn(key, str(error.exception))

    def test_malformed_toml_is_configuration_error(self):
        with self.assertRaises(SettingsError):
            self.load_text('[audio')


if __name__ == "__main__":
    unittest.main()
