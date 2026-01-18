"""
GTK overlay window for displaying captions with scrolling
"""
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gtk, Gdk, GLib, Pango
import threading

from settings import get_settings

class CaptionOverlay(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Live Translator")
        self.app = app
        self.settings = get_settings()

        # Window settings
        self.set_default_size(800, 300)
        self.set_decorated(True)
        self.set_resizable(True)

        # Create main box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(main_box)

        # Header bar with settings button
        header = Gtk.HeaderBar()
        header.set_show_title_buttons(True)
        self.set_titlebar(header)

        settings_btn = Gtk.Button()
        settings_btn.set_icon_name("emblem-system-symbolic")
        settings_btn.set_tooltip_text("Settings")
        settings_btn.connect("clicked", self._on_settings_clicked)
        header.pack_end(settings_btn)

        clear_btn = Gtk.Button()
        clear_btn.set_icon_name("edit-clear-all-symbolic")
        clear_btn.set_tooltip_text("Clear History")
        clear_btn.connect("clicked", lambda b: self.clear_history())
        header.pack_end(clear_btn)

        # AI Assistant toggle button
        self.ai_btn = Gtk.ToggleButton()
        self.ai_btn.set_icon_name("dialog-question-symbolic")
        self.ai_btn.set_tooltip_text("Toggle AI Assistant")
        self.ai_btn.connect("toggled", self._on_ai_toggled)
        header.pack_start(self.ai_btn)

        # Content box
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.box.set_margin_top(10)
        self.box.set_margin_bottom(10)
        self.box.set_margin_start(15)
        self.box.set_margin_end(15)
        self.box.set_vexpand(True)
        main_box.append(self.box)

        # Original text section
        original_frame = Gtk.Frame(label="Original")
        original_frame.set_vexpand(True)
        self.box.append(original_frame)

        original_scroll = Gtk.ScrolledWindow()
        original_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        original_scroll.set_vexpand(True)
        original_frame.set_child(original_scroll)

        self.original_text = Gtk.TextView()
        self.original_text.set_editable(False)
        self.original_text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.original_text.set_cursor_visible(False)
        self.original_text.add_css_class("original-text")
        self.original_buffer = self.original_text.get_buffer()
        original_scroll.set_child(self.original_text)
        self.original_scroll = original_scroll

        # Translated text section
        translated_frame = Gtk.Frame(label="Translation")
        translated_frame.set_vexpand(True)
        self.box.append(translated_frame)

        translated_scroll = Gtk.ScrolledWindow()
        translated_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        translated_scroll.set_vexpand(True)
        translated_frame.set_child(translated_scroll)

        self.translated_text = Gtk.TextView()
        self.translated_text.set_editable(False)
        self.translated_text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.translated_text.set_cursor_visible(False)
        self.translated_text.add_css_class("translated-text")
        self.translated_buffer = self.translated_text.get_buffer()
        translated_scroll.set_child(self.translated_text)
        self.translated_scroll = translated_scroll

        # History storage
        self.original_history = []
        self.translated_history = []

        # AI Assistant panel (initially hidden)
        self._create_ai_panel()

        # Apply initial CSS
        self.apply_appearance_settings()

    def _create_ai_panel(self):
        """Create the AI Assistant panel."""
        self.ai_frame = Gtk.Frame(label="AI Assistant")
        self.ai_frame.set_vexpand(True)
        self.ai_frame.set_visible(False)
        self.box.append(self.ai_frame)

        ai_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        ai_box.set_margin_top(5)
        ai_box.set_margin_bottom(5)
        ai_box.set_margin_start(5)
        ai_box.set_margin_end(5)
        self.ai_frame.set_child(ai_box)

        # Top row: Mode selector and Submit button
        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        ai_box.append(top_row)

        # Mode selector dropdown
        self.ai_mode_dropdown = Gtk.DropDown.new_from_strings([
            "Ask Question",
            "Summarize",
            "Learning Help"
        ])
        self.ai_mode_dropdown.set_selected(0)
        top_row.append(self.ai_mode_dropdown)

        # Question entry
        self.ai_entry = Gtk.Entry()
        self.ai_entry.set_placeholder_text("Enter your question...")
        self.ai_entry.set_hexpand(True)
        self.ai_entry.connect("activate", self._on_ai_submit)
        top_row.append(self.ai_entry)

        # Submit button
        submit_btn = Gtk.Button(label="Ask")
        submit_btn.add_css_class("suggested-action")
        submit_btn.connect("clicked", self._on_ai_submit)
        top_row.append(submit_btn)

        # Loading spinner
        self.ai_spinner = Gtk.Spinner()
        self.ai_spinner.set_visible(False)
        top_row.append(self.ai_spinner)

        # Response panels (side by side)
        response_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        response_box.set_vexpand(True)
        ai_box.append(response_box)

        # Original response panel
        orig_response_frame = Gtk.Frame(label="Response (Original)")
        orig_response_frame.set_hexpand(True)
        response_box.append(orig_response_frame)

        orig_response_scroll = Gtk.ScrolledWindow()
        orig_response_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        orig_response_scroll.set_vexpand(True)
        orig_response_scroll.set_min_content_height(100)
        orig_response_frame.set_child(orig_response_scroll)

        self.ai_original_text = Gtk.TextView()
        self.ai_original_text.set_editable(False)
        self.ai_original_text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.ai_original_text.set_cursor_visible(False)
        self.ai_original_text.add_css_class("ai-response-text")
        self.ai_original_buffer = self.ai_original_text.get_buffer()
        orig_response_scroll.set_child(self.ai_original_text)
        self.ai_original_scroll = orig_response_scroll

        # Translated response panel
        trans_response_frame = Gtk.Frame(label="Response (Translated)")
        trans_response_frame.set_hexpand(True)
        response_box.append(trans_response_frame)

        trans_response_scroll = Gtk.ScrolledWindow()
        trans_response_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        trans_response_scroll.set_vexpand(True)
        trans_response_scroll.set_min_content_height(100)
        trans_response_frame.set_child(trans_response_scroll)

        self.ai_translated_text = Gtk.TextView()
        self.ai_translated_text.set_editable(False)
        self.ai_translated_text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.ai_translated_text.set_cursor_visible(False)
        self.ai_translated_text.add_css_class("ai-response-translated")
        self.ai_translated_buffer = self.ai_translated_text.get_buffer()
        trans_response_scroll.set_child(self.ai_translated_text)
        self.ai_translated_scroll = trans_response_scroll

    def _on_ai_toggled(self, button):
        """Toggle AI Assistant panel visibility."""
        visible = button.get_active()
        self.ai_frame.set_visible(visible)
        if visible:
            self.ai_entry.grab_focus()

    def _on_ai_submit(self, widget):
        """Handle AI Assistant submission."""
        question = self.ai_entry.get_text().strip()
        mode_idx = self.ai_mode_dropdown.get_selected()
        modes = ["qa", "summary", "learning"]
        mode = modes[mode_idx]

        # For summary mode, question is optional
        if mode != "summary" and not question:
            self.ai_original_buffer.set_text("Please enter a question.")
            return

        # Get context from history
        context = self._get_context_for_ai()

        if not context:
            self.ai_original_buffer.set_text("No context available. Wait for some transcription.")
            return

        # Show spinner
        self.ai_spinner.set_visible(True)
        self.ai_spinner.start()
        self.ai_original_buffer.set_text("Processing...")
        self.ai_translated_buffer.set_text("")

        # Process in background
        if hasattr(self.app, 'on_ai_request'):
            threading.Thread(
                target=self._process_ai_request,
                args=(context, question, mode),
                daemon=True
            ).start()
        else:
            GLib.idle_add(self._ai_done, {
                "success": False,
                "original_response": "AI Assistant not available.",
                "translated_response": "",
                "is_tips": False
            })

    def _process_ai_request(self, context, question, mode):
        """Process AI request in background thread."""
        try:
            result = self.app.on_ai_request(context, question, mode)
            GLib.idle_add(self._ai_done, result)
        except Exception as e:
            GLib.idle_add(self._ai_done, {
                "success": False,
                "original_response": f"Error: {e}",
                "translated_response": "",
                "is_tips": False
            })

    def _ai_done(self, result):
        """Update UI with AI result."""
        self.ai_spinner.stop()
        self.ai_spinner.set_visible(False)

        prefix = "[Tips & Suggestions]\n\n" if result.get("is_tips") else ""
        self.ai_original_buffer.set_text(prefix + result.get("original_response", ""))
        self.ai_translated_buffer.set_text(prefix + result.get("translated_response", ""))

    def show_detected_qa(self, question, original_response, translated_response):
        """Show auto-detected question and answer in AI panel."""
        # Make AI panel visible if not already
        if not self.ai_frame.get_visible():
            self.ai_btn.set_active(True)
            self.ai_frame.set_visible(True)

        # Format the response with the detected question
        formatted_original = f"[Detected Question]\n{question}\n\n[Answer]\n{original_response}"
        formatted_translated = f"[Detected Question]\n{question}\n\n[Answer]\n{translated_response}"

        self.ai_original_buffer.set_text(formatted_original)
        self.ai_translated_buffer.set_text(formatted_translated)

        # Also update the entry field with the detected question
        self.ai_entry.set_text(question)

        # Scroll to show the response
        self._scroll_to_end(self.ai_original_scroll, self.ai_original_buffer)
        self._scroll_to_end(self.ai_translated_scroll, self.ai_translated_buffer)

    def _get_context_for_ai(self):
        """Get recent context for AI assistant."""
        num_entries = self.settings.get("ai_assistant", "context_entries", 10)

        original = self.original_history[-num_entries:] if self.original_history else []
        translated = self.translated_history[-num_entries:] if self.translated_history else []

        if not original and not translated:
            return ""

        context_parts = []
        if original:
            context_parts.append("Original:\n" + "\n".join(original))
        if translated:
            context_parts.append("Translation:\n" + "\n".join(translated))

        return "\n\n".join(context_parts)

    def apply_appearance_settings(self):
        """Apply appearance settings from config."""
        settings = self.settings
        bg_color = settings.get("appearance", "background_color", "rgba(30, 30, 30, 0.95)")
        orig_color = settings.get("appearance", "original_text_color", "#ffffff")
        trans_color = settings.get("appearance", "translated_text_color", "#4fc3f7")
        ai_color = settings.get("appearance", "ai_response_color", "#a5d6a7")
        orig_size = settings.get("appearance", "original_font_size", 14)
        trans_size = settings.get("appearance", "translated_font_size", 16)
        ai_size = settings.get("appearance", "ai_font_size", 14)
        opacity = settings.get("appearance", "opacity", 0.95)

        self.set_opacity(opacity)

        css = f"""
        window {{
            background-color: {bg_color};
        }}
        frame {{
            background-color: rgba(40, 40, 40, 0.9);
            border-radius: 5px;
        }}
        frame > label {{
            color: #888888;
            font-size: 12px;
        }}
        textview {{
            background-color: transparent;
            padding: 8px;
        }}
        textview text {{
            background-color: transparent;
        }}
        .original-text {{
            color: {orig_color};
            font-size: {orig_size}px;
        }}
        .translated-text {{
            color: {trans_color};
            font-size: {trans_size}px;
            font-weight: bold;
        }}
        .ai-response-text {{
            color: {ai_color};
            font-size: {ai_size}px;
        }}
        .ai-response-translated {{
            color: {trans_color};
            font-size: {ai_size}px;
        }}
        """.encode()

        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _on_settings_clicked(self, button):
        """Open settings dialog."""
        from settings_dialog import SettingsDialog
        dialog = SettingsDialog(self, on_apply_callback=self._on_settings_applied)
        dialog.present()

    def _on_settings_applied(self, settings):
        """Called when settings are applied."""
        self.apply_appearance_settings()
        # Notify app about translation settings change
        if hasattr(self.app, 'on_settings_changed'):
            self.app.on_settings_changed(settings)

    def _scroll_to_end(self, scrolled_window, text_buffer):
        """Scroll to the end of the text."""
        def do_scroll():
            adj = scrolled_window.get_vadjustment()
            adj.set_value(adj.get_upper() - adj.get_page_size())
        GLib.idle_add(do_scroll)

    def set_original_text(self, text):
        """Add original text to history and display."""
        GLib.idle_add(self._add_original, text)

    def set_original_text_with_speakers(self, segments):
        """
        Add speaker-segmented text to history and display with colors.

        Args:
            segments: list of dicts with 'speaker' and 'text' keys
        """
        GLib.idle_add(self._add_original_with_speakers, segments)

    def _add_original_with_speakers(self, segments):
        """Add speaker-colored text to original panel."""
        # Format text with speaker labels
        formatted_parts = []
        for seg in segments:
            speaker = seg.get("speaker", "Unknown")
            text = seg.get("text", "")
            formatted_parts.append(f"[{speaker}]: {text}")

        formatted_text = "\n".join(formatted_parts)
        self.original_history.append(formatted_text)

        # Keep last 50 entries
        if len(self.original_history) > 50:
            self.original_history.pop(0)

        # Apply colored text using tags
        self._apply_speaker_colors(self.original_buffer, self.original_history, segments)
        self._scroll_to_end(self.original_scroll, self.original_buffer)

    def _get_speaker_color(self, speaker_label):
        """Get color for a speaker."""
        # Extract speaker number from label like "Speaker 1"
        try:
            if "Unknown" in speaker_label:
                return self.settings.get("speakers", "unknown_speaker_color", "#b2bec3")

            parts = speaker_label.split()
            if len(parts) >= 2:
                num = int(parts[1])
                color_key = f"speaker_{num}_color"
                # Cycle through colors if speaker number > 6
                if num > 6:
                    num = ((num - 1) % 6) + 1
                    color_key = f"speaker_{num}_color"
                return self.settings.get("speakers", color_key, "#ffffff")
        except (ValueError, IndexError):
            pass
        return self.settings.get("speakers", "unknown_speaker_color", "#b2bec3")

    def _apply_speaker_colors(self, buffer, history, current_segments):
        """Apply speaker colors to text buffer."""
        # Get tag table
        tag_table = buffer.get_tag_table()

        # Create or get tags for each speaker color
        speaker_colors = {}
        for i in range(1, 7):
            color = self.settings.get("speakers", f"speaker_{i}_color", "#ffffff")
            tag_name = f"speaker_{i}"
            tag = tag_table.lookup(tag_name)
            if not tag:
                tag = buffer.create_tag(tag_name, foreground=color)
            else:
                tag.set_property("foreground", color)
            speaker_colors[f"Speaker {i}"] = tag

        # Unknown speaker tag
        unknown_color = self.settings.get("speakers", "unknown_speaker_color", "#b2bec3")
        unknown_tag = tag_table.lookup("speaker_unknown")
        if not unknown_tag:
            unknown_tag = buffer.create_tag("speaker_unknown", foreground=unknown_color)
        else:
            unknown_tag.set_property("foreground", unknown_color)
        speaker_colors["Unknown"] = unknown_tag

        # Build full text
        full_text = "\n\n".join(history)
        buffer.set_text(full_text)

        # Apply colors to current segments (last entry)
        if current_segments and history:
            # Find the start of the last entry
            last_entry = history[-1]
            start_pos = len(full_text) - len(last_entry)

            current_pos = start_pos
            for seg in current_segments:
                speaker = seg.get("speaker", "Unknown")
                text = seg.get("text", "")
                line = f"[{speaker}]: {text}"

                # Get the tag for this speaker
                tag = speaker_colors.get(speaker)
                if not tag:
                    # Map to numbered speaker
                    for key in speaker_colors:
                        if key in speaker:
                            tag = speaker_colors[key]
                            break
                    if not tag:
                        tag = unknown_tag

                # Apply tag to this line
                start_iter = buffer.get_iter_at_offset(current_pos)
                end_iter = buffer.get_iter_at_offset(current_pos + len(line))
                buffer.apply_tag(tag, start_iter, end_iter)

                current_pos += len(line) + 1  # +1 for newline

    def _add_original(self, text):
        self.original_history.append(text)
        # Keep last 50 entries
        if len(self.original_history) > 50:
            self.original_history.pop(0)

        full_text = "\n\n".join(self.original_history)
        self.original_buffer.set_text(full_text)
        self._scroll_to_end(self.original_scroll, self.original_buffer)

    def set_translated_text(self, text):
        """Add translated text to history and display."""
        GLib.idle_add(self._add_translated, text)

    def _add_translated(self, text):
        self.translated_history.append(text)
        # Keep last 50 entries
        if len(self.translated_history) > 50:
            self.translated_history.pop(0)

        full_text = "\n\n".join(self.translated_history)
        self.translated_buffer.set_text(full_text)
        self._scroll_to_end(self.translated_scroll, self.translated_buffer)

    def set_status(self, status):
        """Set status message."""
        GLib.idle_add(self._set_status, status)

    def _set_status(self, status):
        self.original_buffer.set_text(status)

    def clear_history(self):
        """Clear all history."""
        self.original_history = []
        self.translated_history = []
        GLib.idle_add(self._clear_buffers)

    def _clear_buffers(self):
        self.original_buffer.set_text("")
        self.translated_buffer.set_text("")


class OverlayApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="com.local.livetranslator")
        self.window = None

    def do_activate(self):
        if not self.window:
            self.window = CaptionOverlay(self)
        self.window.present()


if __name__ == "__main__":
    # Test overlay
    app = OverlayApp()

    def test_update():
        if app.window:
            app.window.set_original_text("Hello, this is a test.")
            app.window.set_translated_text("Привет, это тест.")
            GLib.timeout_add(2000, add_more)
        return False

    def add_more():
        if app.window:
            app.window.set_original_text("This is the second sentence.")
            app.window.set_translated_text("Это второе предложение.")
            GLib.timeout_add(2000, add_even_more)
        return False

    def add_even_more():
        if app.window:
            app.window.set_original_text("And a third one to test scrolling.")
            app.window.set_translated_text("И третье для проверки прокрутки.")
        return False

    GLib.timeout_add(1000, test_update)
    app.run(None)
