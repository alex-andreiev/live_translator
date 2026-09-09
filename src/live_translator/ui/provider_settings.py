"""Reusable provider/model selector; network and process work stays off GTK."""
import threading
from gi.repository import Gtk, GLib
from live_translator.ai.providers import PROVIDERS, create_adapter


class ProviderSettings(Gtk.Box):
    def __init__(self, settings, category, profiles, connections=True, auto_discover=True):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.profiles = profiles
        self.connections = connections
        self.auto_discover = auto_discover
        self.before_request = lambda: None
        self.current = None
        self.models = {}
        self.generation = 0
        self.busy = False
        self.provider = Gtk.ComboBoxText()
        for key, (label, _, _) in PROVIDERS.items():
            self.provider.append(key, label)
        self.append(self.provider)
        self.model = Gtk.ComboBoxText.new_with_entry()
        self.model.get_child().set_placeholder_text("Select or enter model ID")
        self.append(self.model)
        self.model_info = Gtk.Label(xalign=0, wrap=True)
        self.append(self.model_info)
        self.model_details = {}
        self.model.get_child().connect("changed", self._update_model_info)
        self.url = Gtk.Entry(placeholder_text="Server URL")
        self.key = Gtk.Entry(placeholder_text="API key (or use environment variable)")
        self.key.set_visibility(False)
        self.timeout = Gtk.SpinButton.new_with_range(1, 600, 1)
        # Re-discover shortly after the user stops editing the server or key.
        for entry in (self.url, self.key):
            entry.connect("activate", lambda *_: self.connection_changed())
            entry.connect("changed", self._schedule_rediscovery)
        self.connection_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for label, widget in (("Server URL", self.url), ("API key", self.key), ("Request timeout (seconds)", self.timeout)):
            self.connection_box.append(Gtk.Label(label=label, xalign=0))
            self.connection_box.append(widget)
        if connections:
            self.append(self.connection_box)
        else:
            self.append(Gtk.Label(label="Uses connection settings from the Translation tab.", xalign=0))
        self.actions = Gtk.Box(spacing=6)
        self.buttons = []
        for title, action in (("Refresh / test", "refresh"), ("Start server", "start"),
                              ("Stop server", "stop"), ("Server status", "status"),
                              ("Load model", "load"), ("Unload model", "unload")):
            button = Gtk.Button(label=title)
            button.connect("clicked", self._run, action)
            self.actions.append(button)
            self.buttons.append(button)
        # Wrap controls on two lines to fit the settings window.
        self.append(self.actions)
        lifecycle = Gtk.Box(spacing=6)
        for button in self.buttons[3:]:
            self.actions.remove(button)
            lifecycle.append(button)
        self.append(lifecycle)
        self.status = Gtk.Label(xalign=0, wrap=True)
        self.append(self.status)
        self.hint = Gtk.Label(xalign=0, wrap=True)
        self.append(self.hint)
        self.models[settings.get(category, "provider", "ollama")] = settings.get(category, "model", "")
        self.provider.connect("changed", self._changed)
        self.provider.set_active_id(settings.get(category, "provider", "ollama"))
        if self.provider.get_active_id() is None:
            self.provider.set_active_id("none")

    def snapshot(self):
        if self.current is None:
            return
        self.models[self.current] = self.model.get_child().get_text().strip()
        if self.connections:
            self.profiles[self.current] = {"base_url": self.url.get_text().strip(),
                                           "api_key": self.key.get_text().strip(),
                                           "timeout": self.timeout.get_value_as_int()}

    def _changed(self, combo):
        self.snapshot()
        self.generation += 1
        self.current = combo.get_active_id()
        _, default_url, default_model = PROVIDERS[self.current]
        profile = self.profiles.get(self.current, {})
        self.url.set_text(profile.get("base_url", default_url))
        self.key.set_text(profile.get("api_key", ""))
        self.timeout.set_value(profile.get("timeout", 30))
        self.model.remove_all()
        self.model_details = {}
        self.model.get_child().set_text(self.models.get(self.current, default_model))
        self._update_model_info()
        self.connection_box.set_visible(self.current != "none")
        self.model.set_sensitive(self.current != "none")
        for index, button in enumerate(self.buttons):
            button.set_visible(index == 0 or self.current == "lmstudio")
            button.set_sensitive(self.current != "none" and not self.busy)
        self.status.set_text("")
        self.hint.set_text({
            "none": "Speech recognition continues without an LLM or translation service.",
            "ollama": "Optional local service. Install Ollama and download a model before using it.",
            "lmstudio": "Download models in LM Studio first. Start requires LM Studio/llmster and the lms CLI. Model controls require the native v1 API. Stop affects other clients too.",
            "deepseek": "Sends text to DeepSeek using your API account. Refresh lists current models. Flash is the initial low-latency choice. Key fallback: DEEPSEEK_API_KEY.",
        }.get(self.current, "External API: text is sent to this provider using your account."))
        self._autodiscover()

    def _autodiscover(self):
        """Populate the model list without the user pressing Refresh.

        Skipped when there is nothing to ask, or when the provider needs a key we do
        not have -- querying then would only produce an error the user did not invite.
        """
        # Deliberately not gated on self.busy: switching provider bumps `generation`,
        # which discards the in-flight reply, and the new provider must still load.
        if not self.auto_discover or self.current in (None, "none"):
            return
        if self._needs_missing_key():
            self.status.set_text("Enter an API key, then models are listed automatically.")
            return
        self._run(None, "refresh", auto=True)

    def _needs_missing_key(self):
        from live_translator.ai.providers import ADAPTERS
        adapter = ADAPTERS.get(self.current)
        if adapter is None or not getattr(adapter, "requires_key", False):
            return False
        import os
        return not (self.key.get_text().strip() or os.environ.get(getattr(adapter, "key_env", ""), ""))

    def _run(self, button, action, auto=False):
        self.before_request()
        self.snapshot()
        provider = self.current
        model = self.model.get_child().get_text().strip()
        options = self.profiles.get(provider, {}).copy()
        generation = self.generation
        self.busy = True
        for item in self.buttons:
            item.set_sensitive(False)
        self.status.set_text("Loading available models…" if auto else "Working…")

        def worker():
            described = {}
            try:
                adapter = create_adapter(provider, **options)
                models = None
                if action == "refresh":
                    if provider == "lmstudio":
                        from live_translator.ai.providers.lmstudio import describe_model
                        entries = adapter.model_details()
                        models = [m["key"] for m in entries]
                        described = {m["key"]: describe_model(m) for m in entries}
                        loaded = sum(bool(m.get("loaded_instances")) for m in entries)
                        message = f"Connected. {len(models)} models available, {loaded} loaded."
                    else:
                        models = adapter.list_models()
                        message = f"Connected. {len(models)} models available."
                elif action in ("start", "stop", "status"):
                    message = adapter.server(action)
                else:
                    if not model:
                        raise ValueError("Select a model first.")
                    getattr(adapter, action)(model)
                    message = f"Model {action} completed. Refresh to check loaded status."
            except Exception as exc:
                from live_translator.ai.providers import ProviderError
                message = str(exc) if isinstance(exc, (ProviderError, ValueError)) else "Provider operation failed. Check connection settings."
                if auto:
                    message = f"{message} Press Refresh / test to retry."
                models = None
            GLib.idle_add(finish, models, message, described)

        def finish(models, message, described):
            self.busy = False
            for item in self.buttons:
                item.set_sensitive(self.current != "none")
            if generation != self.generation:
                return False
            self.status.set_text(message)
            if models is not None:
                # Preserve edits made while discovery was running, including custom IDs.
                selected = self.model.get_child().get_text().strip()
                self.model_details = described
                self.model.remove_all()
                for name in models:
                    self.model.append_text(name)
                # Without this the field stays blank for providers that have no
                # default model, so a successful refresh still looks like "no models".
                if not selected and models:
                    selected = models[0]
                self.model.get_child().set_text(selected)
                self._update_model_info()
                # A model the server does not have fails only at translation time,
                # so say so here. It is not overwritten: it may be a valid custom id.
                if selected and models and selected not in models:
                    self.status.set_text(
                        f"{message} Warning: '{selected}' is not on this server. "
                        f"Available: {', '.join(models[:5])}"
                        + ("…" if len(models) > 5 else "")
                        + ". Pick one from the list unless this id is served another way.")
            return False

        threading.Thread(target=worker, daemon=True).start()

    def _schedule_rediscovery(self, *_):
        if not self.auto_discover or self.current in (None, "none"):
            return
        if getattr(self, "_rediscover_source", None):
            GLib.source_remove(self._rediscover_source)

        def fire():
            self._rediscover_source = None
            self.connection_changed()
            return False

        self._rediscover_source = GLib.timeout_add(1200, fire)

    def connection_changed(self):
        """Called when the URL or key was edited: try discovery again."""
        self.snapshot()
        self._autodiscover()

    def apply_choice(self, provider, model):
        """Select a provider/model programmatically, as a recommendation would."""
        self.models[provider] = model
        if self.provider.get_active_id() == provider:
            self.model.get_child().set_text(model)
            self._update_model_info()
        else:
            self.provider.set_active_id(provider)

    def _update_model_info(self, *_):
        self.model_info.set_text(
            self.model_details.get(self.model.get_child().get_text().strip(), ""))

    def collect(self, settings, category):
        self.snapshot()
        settings.set(category, "provider", self.current)
        settings.set(category, "model", self.model.get_child().get_text().strip())

    def validate(self):
        if self.current != "none" and not self.model.get_child().get_text().strip():
            return ["Select or enter a model for the selected provider."]
        if self.connections and self.current != "none":
            try:
                create_adapter(self.current, base_url=self.url.get_text().strip(),
                               api_key=self.key.get_text().strip(), timeout=self.timeout.get_value_as_int())
            except Exception as exc:
                return [str(exc)]
        return []
