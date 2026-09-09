"""Transcription settings must apply without restarting the app."""
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import live_translator.app as app
from live_translator.processing.whisper_models import is_model_cached

TRANSCRIPTION = {"whisper_model": "small", "device": "cuda", "compute_type": "float16",
                 "enable_diarization": True, "num_speakers": None, "min_audio_length": 0.5,
                 "beam_size": 3, "min_silence_duration_ms": 300, "speech_pad_ms": 100,
                 "no_speech_threshold": 0.4, "source_language": "en"}


class ReloadTests(unittest.TestCase):
    def _app(self, values=None):
        values = {**TRANSCRIPTION, **(values or {})}
        instance = app.LiveTranslatorApp.__new__(app.LiveTranslatorApp)
        instance.args = types.SimpleNamespace(whisper_model=None, device=None,
                                              compute_type=None, source_language=None)
        instance.settings = MagicMock()
        instance.settings.get.side_effect = lambda c, k, d=None: values.get(k, d)
        instance.window = MagicMock()
        instance.transcriber = MagicMock(enable_diarization=True)
        instance._transcriber_config = {"model_size": "base", "device": "cpu"}
        instance._reloading = False
        return instance

    def _reload(self, instance, build):
        instance._build_transcriber = build
        done = threading.Event()

        def idle(fn, *args):
            fn(*args)
            done.set()
            return False

        with patch.object(app.GLib, 'idle_add', side_effect=idle):
            instance._reload_transcriber_if_needed()
            done.wait(5)

    def test_changed_settings_rebuild_the_transcriber(self):
        instance = self._app()
        built = []
        self._reload(instance, lambda config: built.append(config) or MagicMock(enable_diarization=True))
        self.assertEqual(built[0]["model_size"], "small")
        self.assertEqual(built[0]["compute_type"], "float16")
        self.assertEqual(instance._transcriber_config["model_size"], "small")
        self.assertFalse(instance._reloading)

    def test_unchanged_settings_do_not_rebuild(self):
        instance = self._app()
        instance._transcriber_config = instance._transcription_config()
        built = []
        instance._build_transcriber = lambda config: built.append(config)
        instance._reload_transcriber_if_needed()
        self.assertEqual(built, [])

    def test_a_failed_rebuild_keeps_the_working_transcriber(self):
        instance = self._app()
        original = instance.transcriber

        def explode(config):
            raise RuntimeError("CUDA out of memory")

        self._reload(instance, explode)
        self.assertIs(instance.transcriber, original)
        self.assertFalse(instance._reloading)
        message = " ".join(str(c) for c in instance.window.set_status.call_args_list)
        self.assertIn("CUDA out of memory", message)

    def test_a_reload_already_running_is_not_started_twice(self):
        instance = self._app()
        instance._reloading = True
        built = []
        instance._build_transcriber = lambda config: built.append(config)
        instance._reload_transcriber_if_needed()
        self.assertEqual(built, [])

    def test_diarization_follows_what_the_model_actually_supports(self):
        instance = self._app()
        self._reload(instance, lambda config: MagicMock(enable_diarization=False))
        self.assertFalse(instance.diarization_enabled)


class DownloadWarningTests(unittest.TestCase):
    def test_incomplete_download_is_not_treated_as_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            revision = (Path(directory) / "models--Systran--faster-whisper-small"
                        / "snapshots" / "abc")
            revision.mkdir(parents=True)
            (revision / "config.json").write_text("{}")
            with patch('huggingface_hub.constants.HF_HUB_CACHE', directory):
                self.assertFalse(is_model_cached("small"))
            (revision / "model.bin").write_bytes(b"weights")
            with patch('huggingface_hub.constants.HF_HUB_CACHE', directory):
                self.assertTrue(is_model_cached("small"))

    def test_missing_cache_and_custom_models(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('huggingface_hub.constants.HF_HUB_CACHE', directory):
                self.assertFalse(is_model_cached("medium"))
                # Nothing useful to say about a custom id, so do not warn.
                self.assertTrue(is_model_cached("my/finetune"))

    def test_uncached_model_warns_about_the_download(self):
        instance = app.LiveTranslatorApp.__new__(app.LiveTranslatorApp)
        instance.window = MagicMock()
        config = {"model_size": "medium", "device": "cuda"}
        with patch('live_translator.processing.whisper_models.is_model_cached', return_value=False), \
             patch.object(app, 'Transcriber', return_value=MagicMock()), \
             patch.object(app.GLib, 'idle_add', side_effect=lambda fn, *a: fn(*a)):
            instance._build_transcriber(config)
        message = " ".join(str(c) for c in instance.window.set_status.call_args_list)
        self.assertIn("Downloading", message)
        self.assertIn("several minutes", message)


if __name__ == '__main__':
    unittest.main()
