import importlib
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

# Import the real module while preventing environment loading or usage API requests.
with patch.dict(os.environ, {'DEEPL_API_KEY': ''}), patch('dotenv.load_dotenv'):
    translator = importlib.import_module('stream_caption.translator')


def response(text, reason='stop'):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=text), finish_reason=reason)])


class TranslatorTests(unittest.TestCase):
    def setUp(self):
        self.deepl = Mock()
        self.sakura = Mock()
        self.deepl_patch = patch.object(translator, '_deepl_client', self.deepl)
        self.sakura_patch = patch.object(translator, '_sakura_client', self.sakura)
        self.deepl_patch.start()
        self.sakura_patch.start()
        self.addCleanup(self.deepl_patch.stop)
        self.addCleanup(self.sakura_patch.stop)

    def test_native_traditional_and_context_for_english(self):
        self.deepl.translate_text.return_value = '正確翻譯'
        result = translator.translate_detailed('new text', 'en', 'zh-TW',
                                               context_source='previous English sentence')
        self.assertEqual(result.backend, 'deepl')
        self.assertEqual(result.text, '正確翻譯')
        kwargs = self.deepl.translate_text.call_args.kwargs
        self.assertEqual(kwargs['target_lang'], 'ZH-HANT')
        self.assertEqual(kwargs['source_lang'], 'EN')
        self.assertEqual(kwargs['context'], 'previous English sentence')
        self.assertNotIn('model_type', kwargs)
        self.sakura.chat.completions.create.assert_not_called()

    def test_model_and_glossary_are_forwarded_when_configured(self):
        self.deepl.translate_text.return_value = 'translation'
        translator.translate_detailed('text', model_type='prefer_quality_optimized',
                                       glossary_id='glossary-id')
        kwargs = self.deepl.translate_text.call_args.kwargs
        self.assertEqual(kwargs['model_type'], 'prefer_quality_optimized')
        self.assertEqual(kwargs['glossary'], 'glossary-id')

    def test_simplified_target_mapping(self):
        self.deepl.translate_text.return_value = '简体'
        self.assertEqual(translator.translate('text', target_lang='zh-CN'), '简体')
        self.assertEqual(self.deepl.translate_text.call_args.kwargs['target_lang'], 'ZH-HANS')

    def test_deepl_failure_falls_back_and_keeps_multiline_translation(self):
        self.deepl.translate_text.side_effect = RuntimeError('unavailable')
        self.sakura.chat.completions.create.return_value = response('第一句。\n第二句。')
        result = translator.translate_detailed('日本語の文章')
        self.assertEqual(result.text, '第一句。\n第二句。')
        self.assertEqual(result.backend, 'sakura')
        self.assertEqual(result.status, 'ok')
        self.assertEqual(result.errors, ('deepl: RuntimeError',))

    def test_non_japanese_pair_does_not_attempt_sakura(self):
        self.deepl.translate_text.side_effect = RuntimeError('unavailable')
        result = translator.translate_detailed('English text', 'en', 'zh-TW')
        self.assertEqual(result.text, '')
        self.assertEqual(result.status, 'unavailable')
        self.sakura.chat.completions.create.assert_not_called()

    def test_empty_deepl_response_can_use_fallback(self):
        self.deepl.translate_text.return_value = ''
        self.sakura.chat.completions.create.return_value = response('譯文')
        result = translator.translate_detailed('日本語の文章')
        self.assertEqual(result.backend, 'sakura')
        self.assertEqual(result.errors, ('deepl: empty response',))

    def test_truncated_sakura_output_is_reported_not_presented_as_complete(self):
        self.deepl.translate_text.side_effect = RuntimeError('unavailable')
        self.sakura.chat.completions.create.return_value = response('未完', 'length')
        result = translator.translate_detailed('日本語の文章')
        self.assertEqual(result.text, '')
        self.assertEqual(result.status, 'truncated')

    def test_context_overflow_retries_without_context_and_retains_full_output(self):
        self.deepl.translate_text.side_effect = RuntimeError('unavailable')
        self.sakura.chat.completions.create.side_effect = [
            RuntimeError('context overflow'), response('第一句\n第二句')]
        result = translator.translate_detailed('new text', context_source='old source',
                                               context_target='old translation')
        self.assertEqual(result.text, '第一句\n第二句')
        last_prompt = self.sakura.chat.completions.create.call_args.kwargs['messages'][0]['content']
        self.assertNotIn('old source', last_prompt)

    def test_empty_input_and_same_language_avoid_api(self):
        self.assertEqual(translator.translate_detailed(' ').status, 'empty_input')
        result = translator.translate_detailed('hello', 'en', 'en')
        self.assertEqual(result.text, 'hello')
        self.assertEqual(result.backend, 'identity')
        self.deepl.translate_text.assert_not_called()
        self.sakura.chat.completions.create.assert_not_called()

    def test_provider_errors_do_not_echo_response_bodies(self):
        self.deepl.translate_text.side_effect = RuntimeError('sensitive-response-marker')
        self.sakura.chat.completions.create.side_effect = RuntimeError('sensitive-response-marker')
        with patch('builtins.print') as printed:
            result = translator.translate_detailed('日本語の文章')
        self.assertNotIn('sensitive-response-marker', str(printed.call_args_list))
        self.assertNotIn('sensitive-response-marker', str(result.errors))

    def test_context_retry_does_not_echo_sensitive_response(self):
        self.deepl.translate_text.side_effect = RuntimeError('unavailable')
        self.sakura.chat.completions.create.side_effect = [
            RuntimeError('context overflow sensitive-response-marker'), response('譯文')]
        with patch('builtins.print') as printed:
            result = translator.translate_detailed('new text', context_source='old text',
                                                   context_target='old translation')
        self.assertEqual(result.text, '譯文')
        self.assertNotIn('sensitive-response-marker', str(printed.call_args_list))

    def test_topic_context_is_forwarded_without_rewriting_source(self):
        self.deepl.translate_text.return_value = 'translation'
        translator.translate_detailed('original text', context_source='previous sentence',
                                       topic_context='日本語の飲み会の話題。')
        call = self.deepl.translate_text.call_args
        self.assertEqual(call.args, ('original text',))
        self.assertEqual(call.kwargs['context'], '日本語の飲み会の話題。\nprevious sentence')

    def test_sakura_retry_keeps_topic_and_drops_previous_sentence(self):
        self.deepl.translate_text.side_effect = RuntimeError('unavailable')
        self.sakura.chat.completions.create.side_effect = [
            RuntimeError('context overflow'), response('translation')]
        translator.translate_detailed('original text', context_source='previous sentence',
                                       context_target='previous translation', topic_context='飲み会の話題')
        prompt = self.sakura.chat.completions.create.call_args.kwargs['messages'][0]['content']
        self.assertIn('飲み会の話題', prompt)
        self.assertIn('original text', prompt)
        self.assertNotIn('previous sentence', prompt)


if __name__ == '__main__':
    unittest.main()
