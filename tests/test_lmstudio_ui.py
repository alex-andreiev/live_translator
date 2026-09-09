"""Regression tests for LM Studio discovery, error reporting and the settings UI."""
import io
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError

from live_translator.ai.providers import create_adapter, ProviderError
from live_translator.ai.providers.lmstudio import describe_model

GEMMA = {
    "type": "llm", "key": "google/gemma-4-e4b", "display_name": "Gemma 4 E4B",
    "params_string": "7.5B", "size_bytes": 6326937801,
    "quantization": {"name": "Q4_K_M"}, "max_context_length": 131072,
    "loaded_instances": [], "capabilities": {"vision": True},
}


class DescribeModelTests(unittest.TestCase):
    def test_summary_includes_size_and_characteristics(self):
        summary = describe_model(GEMMA)
        for expected in ("Gemma 4 E4B", "7.5B params", "6.33 GB on disk",
                         "Q4_K_M", "131,072 token context", "vision"):
            self.assertIn(expected, summary)

    def test_loaded_state_is_reported(self):
        self.assertIn("not loaded", describe_model(GEMMA))
        self.assertIn("loaded (1 instance)",
                      describe_model({**GEMMA, "loaded_instances": [{"id": "i1"}]}))
        self.assertIn("loaded (2 instances)",
                      describe_model({**GEMMA, "loaded_instances": [{"id": "i1"}, {"id": "i2"}]}))

    def test_sparse_entry_does_not_raise(self):
        self.assertEqual(describe_model({"key": "bare"}), "not loaded — use Load model")


class ErrorDetailTests(unittest.TestCase):
    def _http_error(self, code, body):
        return HTTPError("http://localhost:1234/x", code, "reason", {},
                         io.BytesIO(body.encode()))

    def _raise(self, code, body):
        opener = MagicMock()
        opener.open.side_effect = self._http_error(code, body)
        with patch('live_translator.ai.providers.base.build_opener', return_value=opener):
            with self.assertRaises(ProviderError) as caught:
                create_adapter('lmstudio').list_models()
        return str(caught.exception)

    def test_provider_message_reaches_the_user(self):
        message = self._raise(404, '{"error":{"type":"model_not_found",'
                                   '"message":"Model does/not-exist not found in downloaded models"}}')
        self.assertIn("not found in downloaded models", message)

    def test_auth_failures_never_echo_the_body(self):
        for code in (401, 403):
            message = self._raise(code, '{"error":{"message":"token sk-secret-value rejected"}}')
            self.assertNotIn("sk-secret-value", message)

    def test_unparseable_or_empty_bodies_fall_back_to_the_hint(self):
        for body in ("not json", "{}", '{"error":{}}', '[]', '{"error":123}'):
            message = self._raise(404, body)
            self.assertIn("Check the endpoint", message)

    def test_detail_is_bounded_and_single_line(self):
        message = self._raise(500, '{"message":"' + ("word " * 200).strip() + '"}')
        self.assertNotIn("\n", message)
        self.assertLess(len(message), 300)


class _IsolatedSettings:
    """Tests must never read or write the developer's real settings file."""

    def __enter__(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        self._dir = tempfile.TemporaryDirectory()
        self._patch = patch.object(Path, 'home', return_value=Path(self._dir.name))
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()
        self._dir.cleanup()
        return False


def _gtk():
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import Gtk
    if not Gtk.init_check():
        raise unittest.SkipTest("no display")
    return Gtk


class SettingsWidgetTests(unittest.TestCase):
    def setUp(self):
        self.Gtk = _gtk()
        self._settings = _IsolatedSettings().__enter__()
        self.addCleanup(self._settings.__exit__, None, None, None)

    def _widget(self, auto_discover=False):
        from live_translator.ui.provider_settings import ProviderSettings
        from live_translator.utils.settings import Settings
        widget = ProviderSettings(Settings(), 'translation', {}, auto_discover=auto_discover)
        widget.provider.set_active_id('lmstudio')
        return widget

    def _refresh(self, widget, entries):
        """Drive _run's worker/finish synchronously."""
        adapter = MagicMock()
        adapter.model_details.return_value = entries
        with patch('live_translator.ui.provider_settings.create_adapter', return_value=adapter), \
             patch('live_translator.ui.provider_settings.threading.Thread') as thread, \
             patch('live_translator.ui.provider_settings.GLib.idle_add',
                   side_effect=lambda fn, *a: fn(*a)):
            thread.side_effect = lambda target, daemon: MagicMock(start=target)
            widget.buttons[0].emit('clicked')

    def test_refresh_fills_an_empty_model_field(self):
        widget = self._widget()
        self.assertEqual(widget.model.get_child().get_text(), '')
        self._refresh(widget, [GEMMA])
        self.assertEqual(widget.model.get_child().get_text(), 'google/gemma-4-e4b')
        self.assertIn('6.33 GB on disk', widget.model_info.get_text())
        self.assertEqual(widget.validate(), [])

    def test_refresh_keeps_a_model_the_user_typed(self):
        widget = self._widget()
        widget.model.get_child().set_text('my/custom-model')
        self._refresh(widget, [GEMMA])
        self.assertEqual(widget.model.get_child().get_text(), 'my/custom-model')

    def test_details_do_not_leak_across_providers(self):
        widget = self._widget()
        self._refresh(widget, [GEMMA])
        widget.provider.set_active_id('deepseek')
        self.assertEqual(widget.model_info.get_text(), '')
        self.assertEqual(widget.model_details, {})

    def test_selecting_a_provider_discovers_models_without_a_button_press(self):
        calls = []
        from live_translator.ui.provider_settings import ProviderSettings
        with patch.object(ProviderSettings, '_run',
                          side_effect=lambda b, a, auto=False: calls.append((a, auto))):
            self._widget(auto_discover=True)
        self.assertIn(("refresh", True), calls)

    def test_no_discovery_for_disabled_or_keyless_providers(self):
        from live_translator.ui.provider_settings import ProviderSettings
        import os
        for provider in ("none", "deepseek"):
            calls = []
            widget = self._widget()
            widget.auto_discover = True
            with patch.object(ProviderSettings, '_run',
                              side_effect=lambda b, a, auto=False: calls.append(a)), \
                 patch.dict(os.environ, {}, clear=True):
                widget.provider.set_active_id(provider)
            self.assertEqual(calls, [], provider)

    def test_a_key_bearing_provider_is_discovered(self):
        from live_translator.ui.provider_settings import ProviderSettings
        import os
        calls = []
        widget = self._widget()
        widget.auto_discover = True
        with patch.object(ProviderSettings, '_run',
                          side_effect=lambda b, a, auto=False: calls.append(a)), \
             patch.dict(os.environ, {"DEEPSEEK_API_KEY": "k"}):
            widget.provider.set_active_id('deepseek')
        self.assertEqual(calls, ["refresh"])

    def test_a_model_missing_from_the_server_is_flagged_not_overwritten(self):
        widget = self._widget()
        widget.model.get_child().set_text('google/gemma-4-e2b')
        self._refresh(widget, [GEMMA])
        # Preserved: it may be a valid custom id served another way.
        self.assertEqual(widget.model.get_child().get_text(), 'google/gemma-4-e2b')
        self.assertIn("is not on this server", widget.status.get_text())
        self.assertIn("google/gemma-4-e4b", widget.status.get_text())

    def test_no_warning_when_the_model_is_available(self):
        widget = self._widget()
        widget.model.get_child().set_text('google/gemma-4-e4b')
        self._refresh(widget, [GEMMA])
        self.assertNotIn("not on this server", widget.status.get_text())

    def test_validation_dialog_renders_on_gtk4(self):
        from live_translator.ui.settings_dialog import SettingsDialog
        dialog = SettingsDialog(self.Gtk.Window())
        # Regression: format_secondary_text is GTK3-only and raised AttributeError here.
        dialog._show_validation_errors(['Select or enter a model for the selected provider.'])


if __name__ == '__main__':
    unittest.main()
