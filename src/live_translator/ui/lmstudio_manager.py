"""LM Studio model manager: browse, download, load and unload from Settings.

Rows come from two places. Models already downloaded are reported by LM Studio's
native API, so their size, loaded state and VRAM estimate are real. The rest are
suggestions from the curated catalog, whose sizes are approximate until downloaded.
All network, CLI and subprocess work happens on a worker thread.
"""
import threading

from gi.repository import Gtk, GLib

from live_translator.ai.providers import create_adapter, ProviderError
from live_translator.ai.providers.lmstudio_catalog import (
    TRANSLATION_MODELS, RECOMMENDED_CONTEXT)


class ModelRow:
    """One model, whether downloaded or merely suggested."""

    def __init__(self, name, size_mb, downloaded, instances=0, note="", approximate=False):
        self.name = name
        self.size_mb = size_mb
        self.downloaded = downloaded
        self.instances = instances
        self.note = note
        self.approximate = approximate
        self.required_mb = size_mb

    @property
    def loaded(self):
        return self.instances > 0

    def verdict(self, budget_mb):
        """Whether this model fits the VRAM left for translation."""
        if not budget_mb or not self.required_mb:
            return "unknown", "budget unknown"
        if self.required_mb > budget_mb:
            return "too-large", f"needs ~{self.required_mb / 1024:.1f} GB, over budget"
        if self.required_mb > budget_mb * 0.85:
            return "tight", f"~{self.required_mb / 1024:.1f} GB, very little headroom"
        return "fits", f"~{self.required_mb / 1024:.1f} GB, fits"

    def summary(self, budget_mb):
        size = (f"~{self.size_mb / 1024:.1f} GB" if self.approximate
                else f"{self.size_mb / 1024:.1f} GB")
        state = ("loaded" if self.loaded else "downloaded") if self.downloaded else "not downloaded"
        icon = {"fits": "✓", "tight": "!", "too-large": "✗"}.get(self.verdict(budget_mb)[0], "?")
        return f"{icon}  {self.name}  —  {size} · {state} · {self.verdict(budget_mb)[1]}"


class LMStudioManager(Gtk.Box):
    def __init__(self, get_budget_mb, get_connection=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.get_budget_mb = get_budget_mb
        # Read lazily: the URL and timeout can be edited after this widget is built.
        self.get_connection = get_connection or (lambda: {})
        self.on_model_chosen = lambda name: None
        self.rows = []
        self.busy = False
        self._cancel = False

        self.append(Gtk.Label(
            label="Models LM Studio has downloaded, plus suggestions you can download. "
                  "✓ fits the VRAM left after Whisper, ! is tight, ✗ is too large.",
            xalign=0, wrap=True))

        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list.connect("row-selected", lambda *_: self._update_buttons())
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(170)
        scroller.set_child(self.list)
        self.append(scroller)

        actions = Gtk.Box(spacing=6)
        self.buttons = {}
        for key, label in (("refresh", "Refresh"), ("download", "Download"),
                           ("load", "Load"), ("unload", "Unload"),
                           ("use", "Use for translation"), ("cancel", "Cancel")):
            button = Gtk.Button(label=label)
            button.connect("clicked", self._on_action, key)
            actions.append(button)
            self.buttons[key] = button
        self.append(actions)

        self.status = Gtk.Label(xalign=0, wrap=True)
        self.append(self.status)
        self.detail = Gtk.Label(xalign=0, wrap=True)
        self.detail.add_css_class("dim-label")
        self.append(self.detail)

        self._render()
        self._update_buttons()

    # ---- adapter access -------------------------------------------------
    def _adapter(self):
        return create_adapter("lmstudio", **(self.get_connection() or {}))

    # ---- rendering ------------------------------------------------------
    def _render(self):
        budget = self.get_budget_mb()
        while (child := self.list.get_first_child()) is not None:
            self.list.remove(child)
        if not self.rows:
            placeholder = Gtk.Label(label="Press Refresh to query LM Studio.", xalign=0)
            placeholder.set_margin_top(8)
            placeholder.set_margin_bottom(8)
            self.list.append(placeholder)
            return
        for row in self.rows:
            label = Gtk.Label(label=row.summary(budget), xalign=0, wrap=True)
            label.set_margin_top(4)
            label.set_margin_bottom(4)
            label.set_margin_start(6)
            self.list.append(label)

    def _selected(self):
        row = self.list.get_selected_row()
        if row is None:
            return None
        index = row.get_index()
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def _update_buttons(self):
        selection = self._selected()
        downloading = self.busy and not self._cancel
        self.buttons["refresh"].set_sensitive(not self.busy)
        self.buttons["download"].set_sensitive(
            bool(selection) and not selection.downloaded and not self.busy)
        self.buttons["load"].set_sensitive(
            bool(selection) and selection.downloaded and not selection.loaded and not self.busy)
        self.buttons["unload"].set_sensitive(
            bool(selection) and selection.loaded and not self.busy)
        self.buttons["use"].set_sensitive(bool(selection) and selection.downloaded)
        self.buttons["cancel"].set_sensitive(downloading)
        if selection:
            self.detail.set_text(selection.note)

    def autoload(self):
        """Populate the list without waiting for the user to press Refresh."""
        if not self.busy:
            self._on_action(None, "refresh")

    # ---- actions --------------------------------------------------------
    def _on_action(self, button, action):
        if action == "cancel":
            self._cancel = True
            self.status.set_text("Cancelling…")
            return
        selection = self._selected()
        if action == "use":
            if selection:
                self.on_model_chosen(selection.name)
                self.status.set_text(f"{selection.name} selected as the translation model.")
            return
        if action != "refresh" and not selection:
            return

        self.busy = True
        self._cancel = False
        self._update_buttons()
        name = selection.name if selection else None
        self.status.set_text("Querying LM Studio…" if action == "refresh" else
                             {"download": f"Starting download of {name}…",
                              "load": f"Loading {name}…",
                              "unload": f"Unloading {name}…"}[action])

        def report(text):
            GLib.idle_add(self.status.set_text, text)

        def worker():
            rows, message = None, ""
            try:
                adapter = self._adapter()
                if action == "refresh":
                    rows = self._collect(adapter)
                    message = f"{sum(r.downloaded for r in rows)} downloaded, {len(rows)} listed."
                elif action == "download":
                    adapter.download(name, on_progress=report, cancel=lambda: self._cancel)
                    rows = self._collect(adapter)
                    message = f"{name} downloaded."
                elif action == "load":
                    adapter.load(name)
                    rows = self._collect(adapter)
                    message = f"{name} loaded."
                else:
                    adapter.unload(name)
                    rows = self._collect(adapter)
                    message = f"{name} unloaded."
            except ProviderError as exc:
                message = str(exc)
            except Exception:
                message = "LM Studio operation failed. Check the server and connection settings."
            GLib.idle_add(finish, rows, message)

        def finish(rows, message):
            self.busy = False
            self._cancel = False
            if rows is not None:
                self.rows = rows
                self._render()
            self.status.set_text(message)
            self._update_buttons()
            return False

        threading.Thread(target=worker, daemon=True).start()

    def _collect(self, adapter):
        """Downloaded models first (real figures), then catalog suggestions."""
        rows = []
        downloaded_names = set()
        for entry in adapter.model_details():
            size = int((entry.get("size_bytes") or 0) / 1024 / 1024)
            row = ModelRow(entry["key"], size, True,
                           instances=len(entry.get("loaded_instances") or []),
                           note=_note(entry))
            estimate = adapter.estimate_load_mb(entry["key"], RECOMMENDED_CONTEXT)
            if estimate:
                row.required_mb = estimate
                row.note += (f"\nMeasured: needs {estimate / 1024:.1f} GB at "
                             f"{RECOMMENDED_CONTEXT} context (lms --estimate-only).")
            rows.append(row)
            downloaded_names.add(entry["key"].lower())

        for term, parameters, size_gb, note in TRANSLATION_MODELS:
            if any(term in name for name in downloaded_names):
                continue
            rows.append(ModelRow(term, int(size_gb * 1024), False, note=(
                f"{parameters}. {note}\nNot downloaded; size is approximate for a 4-bit "
                f"build. Download runs `lms get {term} -y`."), approximate=True))
        return rows


def _note(entry):
    from live_translator.ai.providers.lmstudio import describe_model
    return describe_model(entry)
