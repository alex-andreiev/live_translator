"""Regression tests for CLI wiring, translator fallbacks and device enumeration."""
import json
import subprocess
import unittest
from unittest.mock import patch, MagicMock

from live_translator.audio.mic import MicCapture
from live_translator.processing.translator import Translator
from live_translator.processing.whisper_models import WHISPER_MODELS, model_description


class TranslatorTests(unittest.TestCase):
    def _translator(self):
        with patch('live_translator.processing.translator.APIClient') as client:
            translator = Translator()
        return translator, client.return_value

    def test_disabled_provider_skips_requests(self):
        translator, client = self._translator()
        translator.set_settings(provider='none')
        self.assertEqual(translator.provider, 'none')
        self.assertIsNone(translator.translate('hello'))
        client.generate.assert_not_called()

    def test_cleared_model_is_applied_and_unset_fields_kept(self):
        translator, client = self._translator()
        translator.set_settings(provider='deepseek', model='')
        self.assertEqual(translator.model, '')
        client.set_settings.assert_called_with(provider='deepseek', model='')
        translator.set_settings(target_language='German')
        self.assertEqual(translator.provider, 'deepseek')

    def test_last_error_is_exposed_from_client(self):
        translator, client = self._translator()
        client.last_error = 'Check the API key.'
        self.assertEqual(translator.last_error, 'Check the API key.')


class WhisperDetailTests(unittest.TestCase):
    def test_every_model_reports_size_and_recommendation(self):
        for name in WHISPER_MODELS:
            cpu = model_description(name, 'cpu')
            self.assertIn('parameters', cpu)
            self.assertIn('CPU recommendation', cpu)
            self.assertIn('GPU recommendation', model_description(name, 'cuda'))

    def test_weights_scale_with_parameters_and_custom_model_is_safe(self):
        self.assertIn('78 MB', model_description('tiny'))
        self.assertIn('3.10 GB', model_description('large-v3'))
        self.assertIn('Custom model', model_description('my-finetune'))


class MicrophoneListingTests(unittest.TestCase):
    def test_pipewire_sources_come_from_pw_dump_graph(self):
        dump = json.dumps([
            {'info': {'props': {'media.class': 'Audio/Source', 'node.name': 'alsa_input.mic',
                                'node.description': 'Built-in Microphone'}}},
            {'info': {'props': {'media.class': 'Audio/Sink', 'node.name': 'alsa_output.speaker'}}},
            {'info': {'props': {'media.class': 'Audio/Source'}}},  # no node.name
            'not-an-object',
        ])
        with patch('live_translator.audio.mic.shutil.which', return_value='/usr/bin/pw-dump'), \
             patch('live_translator.audio.mic.subprocess.run') as run:
            run.return_value.stdout = dump
            self.assertEqual(MicCapture()._list_pipewire_sources(),
                             [{'id': 'alsa_input.mic', 'name': 'Built-in Microphone',
                               'full': 'alsa_input.mic'}])

    def test_pipewire_failures_fall_back_without_raising(self):
        with patch('live_translator.audio.mic.shutil.which', return_value='/usr/bin/pw-dump'), \
             patch('live_translator.audio.mic.subprocess.run',
                   side_effect=subprocess.TimeoutExpired('pw-dump', 10)):
            self.assertEqual(MicCapture()._list_pipewire_sources(), [])
        with patch('live_translator.audio.mic.shutil.which', return_value=None):
            self.assertEqual(MicCapture()._list_pipewire_sources(), [])
            self.assertEqual(MicCapture()._list_pulseaudio_sources(), [])

    def test_pulseaudio_listing_skips_sink_monitors(self):
        with patch('live_translator.audio.mic.shutil.which', return_value='/usr/bin/pactl'), \
             patch('live_translator.audio.mic.subprocess.run') as run:
            run.return_value.stdout = ("0\talsa_output.speaker.monitor\tmodule\ts16le\n"
                                       "1\talsa_input.mic\tmodule\ts16le\n")
            self.assertEqual([m['id'] for m in MicCapture()._list_pulseaudio_sources()],
                             ['alsa_input.mic'])


class CommandLineTests(unittest.TestCase):
    def _parse(self, argv):
        from live_translator.app import main
        with patch('live_translator.app.LiveTranslatorApp') as app, patch('sys.argv', ['live-translator', *argv]):
            main()
        return app.call_args.args[0]

    def test_unset_options_default_to_none_so_settings_win(self):
        args = self._parse([])
        for field in ('whisper_model', 'provider', 'model', 'source_language',
                      'target_language', 'device', 'compute_type'):
            self.assertIsNone(getattr(args, field), field)

    def test_provider_and_model_flags(self):
        args = self._parse(['--provider', 'deepseek', '--model', 'deepseek-v4-flash'])
        self.assertEqual((args.provider, args.model), ('deepseek', 'deepseek-v4-flash'))
        self.assertEqual(self._parse(['-p', 'none']).provider, 'none')

    def test_legacy_ollama_model_flag_still_maps_to_model(self):
        self.assertEqual(self._parse(['--ollama-model', 'mistral:7b']).model, 'mistral:7b')

    def test_unknown_provider_is_rejected(self):
        with self.assertRaises(SystemExit):
            self._parse(['--provider', 'not-a-provider'])


if __name__ == '__main__':
    unittest.main()
