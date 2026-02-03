"""
Settings dialog for Live Translator
"""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, GLib
import threading

from live_translator.utils import get_settings


def get_ollama_models():
    """Fetch list of available Ollama models."""
    try:
        import ollama
        response = ollama.list()
        # Handle both old dict format and new object format
        if hasattr(response, 'models'):
            return [m.model for m in response.models]
        elif isinstance(response, dict):
            return [m.get('name') or m.get('model') for m in response.get('models', [])]
        return []
    except Exception as e:
        print(f"Error fetching Ollama models: {e}")
        return []

class SettingsDialog(Gtk.Window):
    def __init__(self, parent, on_apply_callback=None):
        super().__init__(title="Settings", transient_for=parent, modal=True)
        self.set_default_size(500, 600)
        self.parent_window = parent
        self.on_apply_callback = on_apply_callback
        self.settings = get_settings()
        self._is_waiting_for_reload = False

        # Main container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        main_box.set_margin_top(10)
        main_box.set_margin_bottom(10)
        main_box.set_margin_start(10)
        main_box.set_margin_end(10)
        self.set_child(main_box)

        # Notebook for tabs
        notebook = Gtk.Notebook()
        notebook.set_vexpand(True)
        main_box.append(notebook)

        # Appearance tab
        appearance_page = self._create_appearance_tab()
        notebook.append_page(appearance_page, Gtk.Label(label="Appearance"))

        # Transcription tab
        transcription_page = self._create_transcription_tab()
        notebook.append_page(transcription_page, Gtk.Label(label="Transcription"))

        # Speakers tab
        speakers_page = self._create_speakers_tab()
        notebook.append_page(speakers_page, Gtk.Label(label="Speakers"))

        # Translation tab
        translation_page = self._create_translation_tab()
        notebook.append_page(translation_page, Gtk.Label(label="Translation"))

        # Logging tab
        logging_page = self._create_logging_tab()
        notebook.append_page(logging_page, Gtk.Label(label="Logging"))

        # AI Assistant tab
        ai_page = self._create_ai_tab()
        notebook.append_page(ai_page, Gtk.Label(label="AI Assistant"))

        # Reverse Translation tab
        reverse_page = self._create_reverse_translation_tab()
        notebook.append_page(reverse_page, Gtk.Label(label="Reverse"))

        # Buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        button_box.set_halign(Gtk.Align.END)
        main_box.append(button_box)

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda b: self.close())
        button_box.append(cancel_btn)

        self.apply_btn = Gtk.Button(label="Apply")
        self.apply_btn.connect("clicked", self._on_apply)
        button_box.append(self.apply_btn)

        self.save_btn = Gtk.Button(label="Save")
        self.save_btn.add_css_class("suggested-action")
        self.save_btn.connect("clicked", self._on_save)
        button_box.append(self.save_btn)

        self.reload_spinner = Gtk.Spinner()
        self.reload_spinner.set_visible(False)
        button_box.append(self.reload_spinner)

        self.reload_status_label = Gtk.Label(label="Applying model changes...")
        self.reload_status_label.add_css_class("dim-label")
        self.reload_status_label.set_visible(False)
        button_box.append(self.reload_status_label)

    def _wrap_in_scrolled_window(self, box):
        """Wrap a box in a scrolled window for proper scrolling."""
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_child(box)
        return scrolled

    def _create_appearance_tab(self):
        """Create appearance settings tab."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        box.set_margin_top(15)
        box.set_margin_start(15)
        box.set_margin_end(15)

        # Opacity
        opacity_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        opacity_label = Gtk.Label(label="Window Opacity:")
        opacity_label.set_xalign(0)
        opacity_label.set_hexpand(True)
        opacity_box.append(opacity_label)

        self.opacity_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.3, 1.0, 0.05)
        self.opacity_scale.set_value(self.settings.get("appearance", "opacity", 0.95))
        self.opacity_scale.set_size_request(200, -1)
        opacity_box.append(self.opacity_scale)
        box.append(opacity_box)

        # Background color
        bg_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        bg_label = Gtk.Label(label="Background Color:")
        bg_label.set_xalign(0)
        bg_label.set_hexpand(True)
        bg_box.append(bg_label)

        self.bg_color_btn = Gtk.ColorButton()
        bg_color = Gdk.RGBA()
        bg_color.parse(self.settings.get("appearance", "background_color", "rgba(30, 30, 30, 0.95)"))
        self.bg_color_btn.set_rgba(bg_color)
        self.bg_color_btn.set_use_alpha(True)
        bg_box.append(self.bg_color_btn)
        box.append(bg_box)

        # Original text color
        orig_color_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        orig_color_label = Gtk.Label(label="Original Text Color:")
        orig_color_label.set_xalign(0)
        orig_color_label.set_hexpand(True)
        orig_color_box.append(orig_color_label)

        self.orig_color_btn = Gtk.ColorButton()
        orig_color = Gdk.RGBA()
        orig_color.parse(self.settings.get("appearance", "original_text_color", "#ffffff"))
        self.orig_color_btn.set_rgba(orig_color)
        orig_color_box.append(self.orig_color_btn)
        box.append(orig_color_box)

        # Translated text color
        trans_color_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        trans_color_label = Gtk.Label(label="Translated Text Color:")
        trans_color_label.set_xalign(0)
        trans_color_label.set_hexpand(True)
        trans_color_box.append(trans_color_label)

        self.trans_color_btn = Gtk.ColorButton()
        trans_color = Gdk.RGBA()
        trans_color.parse(self.settings.get("appearance", "translated_text_color", "#4fc3f7"))
        self.trans_color_btn.set_rgba(trans_color)
        trans_color_box.append(self.trans_color_btn)
        box.append(trans_color_box)

        # Original font size
        orig_size_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        orig_size_label = Gtk.Label(label="Original Font Size:")
        orig_size_label.set_xalign(0)
        orig_size_label.set_hexpand(True)
        orig_size_box.append(orig_size_label)

        self.orig_size_spin = Gtk.SpinButton.new_with_range(8, 32, 1)
        self.orig_size_spin.set_value(self.settings.get("appearance", "original_font_size", 14))
        orig_size_box.append(self.orig_size_spin)
        box.append(orig_size_box)

        # Translated font size
        trans_size_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        trans_size_label = Gtk.Label(label="Translated Font Size:")
        trans_size_label.set_xalign(0)
        trans_size_label.set_hexpand(True)
        trans_size_box.append(trans_size_label)

        self.trans_size_spin = Gtk.SpinButton.new_with_range(8, 32, 1)
        self.trans_size_spin.set_value(self.settings.get("appearance", "translated_font_size", 16))
        trans_size_box.append(self.trans_size_spin)
        box.append(trans_size_box)

        return self._wrap_in_scrolled_window(box)

    def _create_transcription_tab(self):
        """Create transcription settings tab."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        box.set_margin_top(15)
        box.set_margin_start(15)
        box.set_margin_end(15)

        # Whisper model
        model_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        model_label = Gtk.Label(label="Whisper Model:")
        model_label.set_xalign(0)
        model_label.set_hexpand(True)
        model_box.append(model_label)

        self.whisper_model_combo = Gtk.ComboBoxText()
        for model in ["tiny", "base", "small", "medium", "large-v2", "large-v3"]:
            self.whisper_model_combo.append_text(model)
        current_model = self.settings.get("transcription", "whisper_model", "base")
        self.whisper_model_combo.set_active(["tiny", "base", "small", "medium", "large-v2", "large-v3"].index(current_model))
        model_box.append(self.whisper_model_combo)
        box.append(model_box)

        # Device
        device_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        device_label = Gtk.Label(label="Device:")
        device_label.set_xalign(0)
        device_label.set_hexpand(True)
        device_box.append(device_label)

        self.device_combo = Gtk.ComboBoxText()
        self.device_combo.append_text("cpu")
        self.device_combo.append_text("cuda")
        current_device = self.settings.get("transcription", "device", "cpu")
        self.device_combo.set_active(0 if current_device == "cpu" else 1)
        device_box.append(self.device_combo)
        box.append(device_box)

        # Compute type
        compute_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        compute_label = Gtk.Label(label="Compute Type:")
        compute_label.set_xalign(0)
        compute_label.set_hexpand(True)
        compute_box.append(compute_label)

        self.compute_combo = Gtk.ComboBoxText()
        for ct in ["int8", "float16", "float32"]:
            self.compute_combo.append_text(ct)
        current_compute = self.settings.get("transcription", "compute_type", "int8")
        self.compute_combo.set_active(["int8", "float16", "float32"].index(current_compute))
        compute_box.append(self.compute_combo)
        box.append(compute_box)

        # Source language
        lang_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        lang_label = Gtk.Label(label="Source Language:")
        lang_label.set_xalign(0)
        lang_label.set_hexpand(True)
        lang_box.append(lang_label)

        self.source_lang_entry = Gtk.Entry()
        self.source_lang_entry.set_text(self.settings.get("transcription", "source_language", "en"))
        self.source_lang_entry.set_size_request(100, -1)
        lang_box.append(self.source_lang_entry)
        box.append(lang_box)

        # Transcription-only mode
        transcription_only_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        transcription_only_label = Gtk.Label(label="Transcription Only (No Translation):")
        transcription_only_label.set_xalign(0)
        transcription_only_label.set_hexpand(True)
        transcription_only_box.append(transcription_only_label)

        self.transcription_only_switch = Gtk.Switch()
        self.transcription_only_switch.set_active(
            self.settings.get("transcription", "transcription_only_mode", False)
        )
        self.transcription_only_switch.set_valign(Gtk.Align.CENTER)
        transcription_only_box.append(self.transcription_only_switch)
        box.append(transcription_only_box)

        # Speaker Diarization section
        diar_label = Gtk.Label(label="Speaker Diarization (Local)")
        diar_label.set_xalign(0)
        diar_label.add_css_class("heading")
        box.append(diar_label)

        # Enable diarization
        diar_enable_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        diar_enable_label = Gtk.Label(label="Enable Speaker Detection:")
        diar_enable_label.set_xalign(0)
        diar_enable_label.set_hexpand(True)
        diar_enable_box.append(diar_enable_label)

        self.diarization_switch = Gtk.Switch()
        self.diarization_switch.set_active(self.settings.get("transcription", "enable_diarization", False))
        self.diarization_switch.set_valign(Gtk.Align.CENTER)
        diar_enable_box.append(self.diarization_switch)
        box.append(diar_enable_box)

        # Number of speakers
        num_speakers_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        num_speakers_label = Gtk.Label(label="Number of Speakers:")
        num_speakers_label.set_xalign(0)
        num_speakers_label.set_hexpand(True)
        num_speakers_box.append(num_speakers_label)

        self.num_speakers_spin = Gtk.SpinButton.new_with_range(0, 10, 1)
        self.num_speakers_spin.set_value(self.settings.get("transcription", "num_speakers", 0))
        num_speakers_box.append(self.num_speakers_spin)
        box.append(num_speakers_box)

        # Diarization info
        diar_info = Gtk.Label(label="0 = auto-detect speakers\nNo HuggingFace token required (uses local model)")
        diar_info.set_xalign(0)
        diar_info.add_css_class("dim-label")
        box.append(diar_info)

        # Performance Optimization section
        perf_label = Gtk.Label(label="Performance Optimization")
        perf_label.set_xalign(0)
        perf_label.add_css_class("heading")
        box.append(perf_label)

        # Audio chunk duration
        chunk_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        chunk_label = Gtk.Label(label="Audio Chunk Duration (sec):")
        chunk_label.set_xalign(0)
        chunk_label.set_hexpand(True)
        chunk_box.append(chunk_label)

        self.audio_chunk_spin = Gtk.SpinButton.new_with_range(0.1, 1.0, 0.05)
        self.audio_chunk_spin.set_value(self.settings.get("transcription", "audio_chunk_duration", 0.25))
        chunk_box.append(self.audio_chunk_spin)
        box.append(chunk_box)

        # Min audio length
        min_audio_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        min_audio_label = Gtk.Label(label="Min Audio Before Processing (sec):")
        min_audio_label.set_xalign(0)
        min_audio_label.set_hexpand(True)
        min_audio_box.append(min_audio_label)

        self.min_audio_spin = Gtk.SpinButton.new_with_range(0.3, 2.0, 0.1)
        self.min_audio_spin.set_value(self.settings.get("transcription", "min_audio_length", 0.5))
        min_audio_box.append(self.min_audio_spin)
        box.append(min_audio_box)

        # Beam size
        beam_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        beam_label = Gtk.Label(label="Beam Size (higher = more accurate, slower):")
        beam_label.set_xalign(0)
        beam_label.set_hexpand(True)
        beam_box.append(beam_label)

        self.beam_spin = Gtk.SpinButton.new_with_range(1, 10, 1)
        self.beam_spin.set_value(self.settings.get("transcription", "beam_size", 3))
        beam_box.append(self.beam_spin)
        box.append(beam_box)

        # Min silence duration
        silence_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        silence_label = Gtk.Label(label="Min Silence Duration (ms):")
        silence_label.set_xalign(0)
        silence_label.set_hexpand(True)
        silence_box.append(silence_label)

        self.silence_spin = Gtk.SpinButton.new_with_range(100, 1000, 50)
        self.silence_spin.set_value(self.settings.get("transcription", "min_silence_duration_ms", 300))
        silence_box.append(self.silence_spin)
        box.append(silence_box)

        # Speech padding
        pad_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        pad_label = Gtk.Label(label="Speech Padding (ms):")
        pad_label.set_xalign(0)
        pad_label.set_hexpand(True)
        pad_box.append(pad_label)

        self.pad_spin = Gtk.SpinButton.new_with_range(0, 500, 50)
        self.pad_spin.set_value(self.settings.get("transcription", "speech_pad_ms", 100))
        pad_box.append(self.pad_spin)
        box.append(pad_box)

        # No speech threshold
        threshold_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        threshold_label = Gtk.Label(label="No Speech Threshold (0.0-1.0):")
        threshold_label.set_xalign(0)
        threshold_label.set_hexpand(True)
        threshold_box.append(threshold_label)

        self.threshold_spin = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.05)
        self.threshold_spin.set_value(self.settings.get("transcription", "no_speech_threshold", 0.4))
        threshold_box.append(self.threshold_spin)
        box.append(threshold_box)

        # Auto-detect language section
        autodetect_label = Gtk.Label(label="Language Detection")
        autodetect_label.set_xalign(0)
        autodetect_label.add_css_class("heading")
        box.append(autodetect_label)

        # Auto-detect language switch
        autodetect_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        autodetect_text = Gtk.Label(label="Auto-Detect Language:")
        autodetect_text.set_xalign(0)
        autodetect_text.set_hexpand(True)
        autodetect_box.append(autodetect_text)

        self.auto_detect_lang_switch = Gtk.Switch()
        self.auto_detect_lang_switch.set_active(self.settings.get("transcription", "auto_detect_language", True))
        self.auto_detect_lang_switch.set_valign(Gtk.Align.CENTER)
        autodetect_box.append(self.auto_detect_lang_switch)
        box.append(autodetect_box)

        # Expected languages
        exp_lang_label = Gtk.Label(label="Expected Languages (comma-separated):")
        exp_lang_label.set_xalign(0)
        box.append(exp_lang_label)

        exp_lang_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.expected_langs_entry = Gtk.Entry()
        expected_langs = self.settings.get("transcription", "expected_languages", ["Russian", "Ukrainian", "English"])
        self.expected_langs_entry.set_text(", ".join(expected_langs) if isinstance(expected_langs, list) else str(expected_langs))
        self.expected_langs_entry.set_hexpand(True)
        exp_lang_box.append(self.expected_langs_entry)
        box.append(exp_lang_box)

        # Expected languages info
        exp_lang_info = Gtk.Label(label="List of languages to expect in audio.\nHelps optimize transcription accuracy.\nExample: Russian, Ukrainian, English")
        exp_lang_info.set_xalign(0)
        exp_lang_info.add_css_class("dim-label")
        box.append(exp_lang_info)

        # Auto-detect info
        autodetect_info = Gtk.Label(label="If enabled: Whisper auto-detects spoken language.\nIf it matches target language, translation is skipped and logging continues.")
        autodetect_info.set_xalign(0)
        autodetect_info.add_css_class("dim-label")
        box.append(autodetect_info)

        # Optimization info
        opt_info = Gtk.Label(label="Reduce beam size and silence duration for faster processing.\nIncrease for better accuracy at the cost of speed.")
        opt_info.set_xalign(0)
        opt_info.add_css_class("dim-label")
        box.append(opt_info)

        # Note
        note_label = Gtk.Label(label="Changes apply immediately. Model/device changes may take a few seconds to reload.")
        note_label.set_xalign(0)
        note_label.add_css_class("dim-label")
        box.append(note_label)

        return self._wrap_in_scrolled_window(box)

    def _create_speakers_tab(self):
        """Create speaker colors settings tab."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        box.set_margin_top(15)
        box.set_margin_start(15)
        box.set_margin_end(15)

        info_label = Gtk.Label(label="Configure colors for each detected speaker")
        info_label.set_xalign(0)
        box.append(info_label)

        # Speaker color buttons
        self.speaker_color_btns = {}

        for i in range(1, 7):
            color_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            color_label = Gtk.Label(label=f"Speaker {i}:")
            color_label.set_xalign(0)
            color_label.set_hexpand(True)
            color_box.append(color_label)

            color_btn = Gtk.ColorButton()
            color = Gdk.RGBA()
            color.parse(self.settings.get("speakers", f"speaker_{i}_color", "#ffffff"))
            color_btn.set_rgba(color)
            color_box.append(color_btn)
            box.append(color_box)

            self.speaker_color_btns[i] = color_btn

        # Unknown speaker color
        unknown_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        unknown_label = Gtk.Label(label="Unknown Speaker:")
        unknown_label.set_xalign(0)
        unknown_label.set_hexpand(True)
        unknown_box.append(unknown_label)
        self.unknown_speaker_color_btn = Gtk.ColorButton()
        unknown_color = Gdk.RGBA()
        unknown_color.parse(self.settings.get("speakers", "unknown_speaker_color", "#b2bec3"))
        self.unknown_speaker_color_btn.set_rgba(unknown_color)
        unknown_box.append(self.unknown_speaker_color_btn)
        box.append(unknown_box)

        return self._wrap_in_scrolled_window(box)

    def _create_translation_tab(self):
        """Create translation settings tab."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        box.set_margin_top(15)
        box.set_margin_start(15)
        box.set_margin_end(15)

        # Model selection
        model_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        model_label = Gtk.Label(label="Ollama Model:")
        model_label.set_xalign(0)
        model_label.set_hexpand(True)
        model_box.append(model_label)

        self.model_combo = Gtk.ComboBoxText()
        self.model_combo.set_size_request(250, -1)
        model_box.append(self.model_combo)

        refresh_btn = Gtk.Button()
        refresh_btn.set_icon_name("view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Refresh model list")
        refresh_btn.connect("clicked", self._on_refresh_models)
        model_box.append(refresh_btn)

        box.append(model_box)

        # Load models in background
        self.ollama_models = []
        self._load_ollama_models()

        # Target language
        target_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        target_label = Gtk.Label(label="Target Language:")
        target_label.set_xalign(0)
        target_label.set_hexpand(True)
        target_box.append(target_label)

        self.target_lang_entry = Gtk.Entry()
        self.target_lang_entry.set_text(self.settings.get("translation", "target_language", "Russian"))
        self.target_lang_entry.set_size_request(200, -1)
        target_box.append(self.target_lang_entry)
        box.append(target_box)

        # Prompt
        prompt_label = Gtk.Label(label="Translation Prompt:")
        prompt_label.set_xalign(0)
        box.append(prompt_label)

        prompt_scroll = Gtk.ScrolledWindow()
        prompt_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        prompt_scroll.set_vexpand(True)
        prompt_scroll.set_min_content_height(150)

        self.prompt_text = Gtk.TextView()
        self.prompt_text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.prompt_buffer = self.prompt_text.get_buffer()
        self.prompt_buffer.set_text(self.settings.get("translation", "prompt",
            "Translate the following text to {target_language}. Output ONLY the translation, nothing else:\n\n{text}"))
        prompt_scroll.set_child(self.prompt_text)
        box.append(prompt_scroll)

        # Prompt variables help
        help_label = Gtk.Label(label="Variables: {text} = input text, {target_language} = target language")
        help_label.set_xalign(0)
        help_label.add_css_class("dim-label")
        box.append(help_label)

        return self._wrap_in_scrolled_window(box)

    def _create_logging_tab(self):
        """Create logging settings tab."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        box.set_margin_top(15)
        box.set_margin_start(15)
        box.set_margin_end(15)

        # Enable logging
        enable_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        enable_label = Gtk.Label(label="Enable Logging:")
        enable_label.set_xalign(0)
        enable_label.set_hexpand(True)
        enable_box.append(enable_label)

        self.logging_enabled_switch = Gtk.Switch()
        self.logging_enabled_switch.set_active(self.settings.get("logging", "enabled", True))
        self.logging_enabled_switch.set_valign(Gtk.Align.CENTER)
        enable_box.append(self.logging_enabled_switch)
        box.append(enable_box)

        # Log path
        path_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        path_label = Gtk.Label(label="Log Directory:")
        path_label.set_xalign(0)
        path_label.set_hexpand(True)
        path_box.append(path_label)

        self.log_path_entry = Gtk.Entry()
        self.log_path_entry.set_text(self.settings.get("logging", "log_path", "~/.local/share/live-translator/logs"))
        self.log_path_entry.set_hexpand(True)
        path_box.append(self.log_path_entry)

        browse_btn = Gtk.Button()
        browse_btn.set_icon_name("folder-open-symbolic")
        browse_btn.set_tooltip_text("Browse")
        browse_btn.connect("clicked", self._on_browse_log_path)
        path_box.append(browse_btn)
        box.append(path_box)

        # Log original text
        log_orig_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        log_orig_label = Gtk.Label(label="Log Original Text:")
        log_orig_label.set_xalign(0)
        log_orig_label.set_hexpand(True)
        log_orig_box.append(log_orig_label)

        self.log_original_switch = Gtk.Switch()
        self.log_original_switch.set_active(self.settings.get("logging", "log_original", True))
        self.log_original_switch.set_valign(Gtk.Align.CENTER)
        log_orig_box.append(self.log_original_switch)
        box.append(log_orig_box)

        # Log translated text
        log_trans_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        log_trans_label = Gtk.Label(label="Log Translated Text:")
        log_trans_label.set_xalign(0)
        log_trans_label.set_hexpand(True)
        log_trans_box.append(log_trans_label)

        self.log_translated_switch = Gtk.Switch()
        self.log_translated_switch.set_active(self.settings.get("logging", "log_translated", True))
        self.log_translated_switch.set_valign(Gtk.Align.CENTER)
        log_trans_box.append(self.log_translated_switch)
        box.append(log_trans_box)

        # Open logs folder button
        open_btn = Gtk.Button(label="Open Logs Folder")
        open_btn.connect("clicked", self._on_open_logs_folder)
        box.append(open_btn)

        # Info label
        info_label = Gtk.Label(label="Logs are saved daily with timestamp in filename.")
        info_label.set_xalign(0)
        info_label.add_css_class("dim-label")
        box.append(info_label)

        return self._wrap_in_scrolled_window(box)

    def _create_ai_tab(self):
        """Create AI Assistant settings tab."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        box.set_margin_top(15)
        box.set_margin_start(15)
        box.set_margin_end(15)

        # Enable AI Assistant
        enable_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        enable_label = Gtk.Label(label="Enable AI Assistant:")
        enable_label.set_xalign(0)
        enable_label.set_hexpand(True)
        enable_box.append(enable_label)

        self.ai_enabled_switch = Gtk.Switch()
        self.ai_enabled_switch.set_active(self.settings.get("ai_assistant", "enabled", True))
        self.ai_enabled_switch.set_valign(Gtk.Align.CENTER)
        enable_box.append(self.ai_enabled_switch)
        box.append(enable_box)

        # Use same model as translation
        same_model_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        same_model_label = Gtk.Label(label="Use Translation Model:")
        same_model_label.set_xalign(0)
        same_model_label.set_hexpand(True)
        same_model_box.append(same_model_label)

        self.ai_use_trans_model_switch = Gtk.Switch()
        self.ai_use_trans_model_switch.set_active(self.settings.get("ai_assistant", "use_translation_model", True))
        self.ai_use_trans_model_switch.set_valign(Gtk.Align.CENTER)
        self.ai_use_trans_model_switch.connect("state-set", self._on_ai_model_switch_changed)
        same_model_box.append(self.ai_use_trans_model_switch)
        box.append(same_model_box)

        # AI Model selection (shown when not using translation model)
        self.ai_model_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        ai_model_label = Gtk.Label(label="AI Model:")
        ai_model_label.set_xalign(0)
        ai_model_label.set_hexpand(True)
        self.ai_model_box.append(ai_model_label)

        self.ai_model_combo = Gtk.ComboBoxText()
        self.ai_model_combo.set_size_request(250, -1)
        self.ai_model_box.append(self.ai_model_combo)
        self.ai_model_box.set_visible(not self.ai_use_trans_model_switch.get_active())
        box.append(self.ai_model_box)

        # Load AI models in background
        self._load_ai_ollama_models()

        # Context entries
        context_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        context_label = Gtk.Label(label="Context Entries:")
        context_label.set_xalign(0)
        context_label.set_hexpand(True)
        context_box.append(context_label)

        self.ai_context_spin = Gtk.SpinButton.new_with_range(1, 50, 1)
        self.ai_context_spin.set_value(self.settings.get("ai_assistant", "context_entries", 10))
        context_box.append(self.ai_context_spin)
        box.append(context_box)

        # Auto-detect questions
        auto_detect_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        auto_detect_label = Gtk.Label(label="Auto-Detect Questions:")
        auto_detect_label.set_xalign(0)
        auto_detect_label.set_hexpand(True)
        auto_detect_box.append(auto_detect_label)

        self.ai_auto_detect_switch = Gtk.Switch()
        self.ai_auto_detect_switch.set_active(self.settings.get("ai_assistant", "auto_detect_questions", True))
        self.ai_auto_detect_switch.set_valign(Gtk.Align.CENTER)
        auto_detect_box.append(self.ai_auto_detect_switch)
        box.append(auto_detect_box)

        # Auto-detect info
        auto_detect_info = Gtk.Label(label="Automatically detect and answer questions from transcribed speech")
        auto_detect_info.set_xalign(0)
        auto_detect_info.add_css_class("dim-label")
        box.append(auto_detect_info)

        # Show tips on failure
        tips_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        tips_label = Gtk.Label(label="Show Tips When No Answer:")
        tips_label.set_xalign(0)
        tips_label.set_hexpand(True)
        tips_box.append(tips_label)

        self.ai_tips_switch = Gtk.Switch()
        self.ai_tips_switch.set_active(self.settings.get("ai_assistant", "show_tips_on_failure", True))
        self.ai_tips_switch.set_valign(Gtk.Align.CENTER)
        tips_box.append(self.ai_tips_switch)
        box.append(tips_box)

        # Auto translate response
        auto_trans_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        auto_trans_label = Gtk.Label(label="Auto-Translate Response:")
        auto_trans_label.set_xalign(0)
        auto_trans_label.set_hexpand(True)
        auto_trans_box.append(auto_trans_label)

        self.ai_auto_translate_switch = Gtk.Switch()
        self.ai_auto_translate_switch.set_active(self.settings.get("ai_assistant", "auto_translate_response", True))
        self.ai_auto_translate_switch.set_valign(Gtk.Align.CENTER)
        auto_trans_box.append(self.ai_auto_translate_switch)
        box.append(auto_trans_box)

        # AI Response Color
        ai_color_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        ai_color_label = Gtk.Label(label="AI Response Color:")
        ai_color_label.set_xalign(0)
        ai_color_label.set_hexpand(True)
        ai_color_box.append(ai_color_label)

        self.ai_color_btn = Gtk.ColorButton()
        ai_color = Gdk.RGBA()
        ai_color.parse(self.settings.get("appearance", "ai_response_color", "#a5d6a7"))
        self.ai_color_btn.set_rgba(ai_color)
        ai_color_box.append(self.ai_color_btn)
        box.append(ai_color_box)

        # AI Font Size
        ai_size_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        ai_size_label = Gtk.Label(label="AI Response Font Size:")
        ai_size_label.set_xalign(0)
        ai_size_label.set_hexpand(True)
        ai_size_box.append(ai_size_label)

        self.ai_size_spin = Gtk.SpinButton.new_with_range(8, 32, 1)
        self.ai_size_spin.set_value(self.settings.get("appearance", "ai_font_size", 14))
        ai_size_box.append(self.ai_size_spin)
        box.append(ai_size_box)

        # Info label
        info_label = Gtk.Label(label="AI Assistant provides Q&A, summaries, and learning help\nbased on recent transcription context.")
        info_label.set_xalign(0)
        info_label.add_css_class("dim-label")
        box.append(info_label)

        return self._wrap_in_scrolled_window(box)

    def _on_ai_model_switch_changed(self, switch, state):
        """Toggle AI model selection visibility."""
        self.ai_model_box.set_visible(not state)

    def _create_reverse_translation_tab(self):
        """Create reverse translation (speech-to-speech) settings tab."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        box.set_margin_top(15)
        box.set_margin_start(15)
        box.set_margin_end(15)

        # Section header
        header = Gtk.Label(label="<b>Speech-to-Speech Translation</b>")
        header.set_use_markup(True)
        header.set_xalign(0)
        box.append(header)

        desc = Gtk.Label(label="Translate your microphone speech and output\nto a virtual microphone for video calls.")
        desc.set_xalign(0)
        desc.add_css_class("dim-label")
        box.append(desc)

        # Enable switch
        enable_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        enable_label = Gtk.Label(label="Enable Reverse Translation:")
        enable_label.set_xalign(0)
        enable_label.set_hexpand(True)
        enable_box.append(enable_label)

        self.reverse_enabled_switch = Gtk.Switch()
        self.reverse_enabled_switch.set_active(self.settings.get("reverse_translation", "enabled", False))
        enable_box.append(self.reverse_enabled_switch)
        box.append(enable_box)

        # Auto-start with app
        auto_start_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        auto_start_label = Gtk.Label(label="Auto-start with application:")
        auto_start_label.set_xalign(0)
        auto_start_label.set_hexpand(True)
        auto_start_box.append(auto_start_label)

        self.reverse_auto_start_switch = Gtk.Switch()
        self.reverse_auto_start_switch.set_active(self.settings.get("reverse_translation", "auto_start", False))
        auto_start_box.append(self.reverse_auto_start_switch)
        box.append(auto_start_box)

        # Separator
        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Source language (your language)
        source_lang_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        source_lang_label = Gtk.Label(label="Your Language:")
        source_lang_label.set_xalign(0)
        source_lang_label.set_hexpand(True)
        source_lang_box.append(source_lang_label)

        self.reverse_source_lang_entry = Gtk.Entry()
        self.reverse_source_lang_entry.set_text(self.settings.get("reverse_translation", "source_language", "Russian"))
        self.reverse_source_lang_entry.set_size_request(150, -1)
        source_lang_box.append(self.reverse_source_lang_entry)
        box.append(source_lang_box)

        # Target language (what others hear)
        target_lang_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        target_lang_label = Gtk.Label(label="Output Language:")
        target_lang_label.set_xalign(0)
        target_lang_label.set_hexpand(True)
        target_lang_box.append(target_lang_label)

        self.reverse_target_lang_entry = Gtk.Entry()
        self.reverse_target_lang_entry.set_text(self.settings.get("reverse_translation", "target_language", "English"))
        self.reverse_target_lang_entry.set_size_request(150, -1)
        target_lang_box.append(self.reverse_target_lang_entry)
        box.append(target_lang_box)

        # Separator
        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Input device selection
        input_dev_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        input_dev_label = Gtk.Label(label="Input Device (Microphone):")
        input_dev_label.set_xalign(0)
        input_dev_label.set_hexpand(True)
        input_dev_box.append(input_dev_label)

        self.reverse_input_device_combo = Gtk.ComboBoxText()
        self.reverse_input_device_combo.append_text("Default")
        self.reverse_input_device_combo.set_active(0)
        input_dev_box.append(self.reverse_input_device_combo)
        box.append(input_dev_box)

        # Refresh devices button
        refresh_dev_btn = Gtk.Button(label="Refresh Devices")
        refresh_dev_btn.connect("clicked", self._on_refresh_input_devices)
        box.append(refresh_dev_btn)

        # Load devices in background
        self._load_input_devices()

        # Separator
        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # TTS section header
        tts_header = Gtk.Label(label="<b>Text-to-Speech Settings</b>")
        tts_header.set_use_markup(True)
        tts_header.set_xalign(0)
        box.append(tts_header)

        # TTS engine selection
        tts_engine_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        tts_engine_label = Gtk.Label(label="TTS Engine:")
        tts_engine_label.set_xalign(0)
        tts_engine_label.set_hexpand(True)
        tts_engine_box.append(tts_engine_label)

        self.reverse_tts_engine_combo = Gtk.ComboBoxText()
        self.reverse_tts_engine_combo.append_text("piper")
        self.reverse_tts_engine_combo.append_text("espeak")
        current_engine = self.settings.get("reverse_translation", "tts_engine", "piper")
        self.reverse_tts_engine_combo.set_active(0 if current_engine == "piper" else 1)
        tts_engine_box.append(self.reverse_tts_engine_combo)
        box.append(tts_engine_box)

        # TTS voice
        tts_voice_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        tts_voice_label = Gtk.Label(label="Voice:")
        tts_voice_label.set_xalign(0)
        tts_voice_label.set_hexpand(True)
        tts_voice_box.append(tts_voice_label)

        self.reverse_tts_voice_entry = Gtk.Entry()
        self.reverse_tts_voice_entry.set_text(self.settings.get("reverse_translation", "tts_voice", ""))
        self.reverse_tts_voice_entry.set_placeholder_text("Leave empty for default")
        self.reverse_tts_voice_entry.set_size_request(200, -1)
        tts_voice_box.append(self.reverse_tts_voice_entry)
        box.append(tts_voice_box)

        # TTS speed
        tts_speed_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        tts_speed_label = Gtk.Label(label="Speech Speed:")
        tts_speed_label.set_xalign(0)
        tts_speed_label.set_hexpand(True)
        tts_speed_box.append(tts_speed_label)

        self.reverse_tts_speed_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.5, 2.0, 0.1)
        self.reverse_tts_speed_scale.set_value(self.settings.get("reverse_translation", "tts_speed", 1.0))
        self.reverse_tts_speed_scale.set_size_request(150, -1)
        tts_speed_box.append(self.reverse_tts_speed_scale)
        box.append(tts_speed_box)

        # Separator
        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Virtual sink name
        sink_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        sink_label = Gtk.Label(label="Virtual Mic Name:")
        sink_label.set_xalign(0)
        sink_label.set_hexpand(True)
        sink_box.append(sink_label)

        self.reverse_sink_name_entry = Gtk.Entry()
        self.reverse_sink_name_entry.set_text(self.settings.get("reverse_translation", "virtual_sink_name", "LiveTranslator_VirtualMic"))
        self.reverse_sink_name_entry.set_size_request(200, -1)
        sink_box.append(self.reverse_sink_name_entry)
        box.append(sink_box)

        # Info about virtual mic
        virtual_info = Gtk.Label(label="Select 'Monitor of [Virtual Mic Name]' as input\nin your video call application.")
        virtual_info.set_xalign(0)
        virtual_info.add_css_class("dim-label")
        box.append(virtual_info)

        return self._wrap_in_scrolled_window(box)

    def _load_input_devices(self):
        """Load input devices in background."""
        def fetch_devices():
            try:
                from mic_capture import MicCapture
                devices = MicCapture.list_devices()
                GLib.idle_add(self._populate_input_devices, devices)
            except Exception as e:
                print(f"Error loading input devices: {e}")

        threading.Thread(target=fetch_devices, daemon=True).start()

    def _populate_input_devices(self, devices):
        """Populate input device combo."""
        self.reverse_input_device_combo.remove_all()
        self.reverse_input_device_combo.append_text("Default")

        current_device = self.settings.get("reverse_translation", "input_device", "")
        active_index = 0

        for i, dev in enumerate(devices):
            name = dev.get('name', dev.get('description', f'Device {i}'))
            self.reverse_input_device_combo.append_text(name)
            if name == current_device:
                active_index = i + 1  # +1 because of "Default" at index 0

        self.reverse_input_device_combo.set_active(active_index)

    def _on_refresh_input_devices(self, button):
        """Refresh input device list."""
        self.reverse_input_device_combo.remove_all()
        self.reverse_input_device_combo.append_text("Loading...")
        self.reverse_input_device_combo.set_active(0)
        self._load_input_devices()

    def _load_ai_ollama_models(self):
        """Load Ollama models for AI assistant."""
        def fetch_models():
            models = get_ollama_models()
            GLib.idle_add(self._populate_ai_model_combo, models)

        threading.Thread(target=fetch_models, daemon=True).start()

    def _populate_ai_model_combo(self, models):
        """Populate AI model combo box with fetched models."""
        self.ai_model_combo.remove_all()

        current_model = self.settings.get("ai_assistant", "model", "mistral:7b")
        active_index = 0

        for i, model in enumerate(models):
            self.ai_model_combo.append_text(model)
            if model == current_model:
                active_index = i

        if models:
            self.ai_model_combo.set_active(active_index)
        else:
            self.ai_model_combo.append_text("No models found")
            self.ai_model_combo.set_active(0)

    def _on_browse_log_path(self, button):
        """Open folder chooser for log path."""
        dialog = Gtk.FileDialog()
        dialog.set_title("Select Log Directory")

        def on_folder_selected(dialog, result):
            try:
                folder = dialog.select_folder_finish(result)
                if folder:
                    self.log_path_entry.set_text(folder.get_path())
            except Exception:
                pass

        dialog.select_folder(self, None, on_folder_selected)

    def _on_open_logs_folder(self, button):
        """Open logs folder in file manager."""
        import subprocess
        import os
        log_path = os.path.expanduser(self.log_path_entry.get_text())
        if os.path.exists(log_path):
            subprocess.Popen(["xdg-open", log_path])
        else:
            # Create directory and open
            os.makedirs(log_path, exist_ok=True)
            subprocess.Popen(["xdg-open", log_path])

    def _rgba_to_css(self, rgba):
        """Convert Gdk.RGBA to CSS color string."""
        if rgba.alpha < 1.0:
            return f"rgba({int(rgba.red*255)}, {int(rgba.green*255)}, {int(rgba.blue*255)}, {rgba.alpha:.2f})"
        else:
            return f"#{int(rgba.red*255):02x}{int(rgba.green*255):02x}{int(rgba.blue*255):02x}"

    def _collect_settings(self):
        """Collect all settings from UI."""
        # Appearance
        self.settings.set("appearance", "opacity", self.opacity_scale.get_value())
        self.settings.set("appearance", "background_color", self._rgba_to_css(self.bg_color_btn.get_rgba()))
        self.settings.set("appearance", "original_text_color", self._rgba_to_css(self.orig_color_btn.get_rgba()))
        self.settings.set("appearance", "translated_text_color", self._rgba_to_css(self.trans_color_btn.get_rgba()))
        self.settings.set("appearance", "original_font_size", int(self.orig_size_spin.get_value()))
        self.settings.set("appearance", "translated_font_size", int(self.trans_size_spin.get_value()))

        # Transcription
        self.settings.set("transcription", "whisper_model", self.whisper_model_combo.get_active_text())
        self.settings.set("transcription", "device", self.device_combo.get_active_text())
        self.settings.set("transcription", "compute_type", self.compute_combo.get_active_text())
        self.settings.set("transcription", "source_language", self.source_lang_entry.get_text())
        self.settings.set("transcription", "transcription_only_mode", self.transcription_only_switch.get_active())
        self.settings.set("transcription", "enable_diarization", self.diarization_switch.get_active())
        num_speakers = int(self.num_speakers_spin.get_value())
        self.settings.set("transcription", "num_speakers", num_speakers if num_speakers > 0 else None)
        
        # Performance optimization settings
        self.settings.set("transcription", "audio_chunk_duration", self.audio_chunk_spin.get_value())
        self.settings.set("transcription", "min_audio_length", self.min_audio_spin.get_value())
        self.settings.set("transcription", "beam_size", int(self.beam_spin.get_value()))
        self.settings.set("transcription", "min_silence_duration_ms", int(self.silence_spin.get_value()))
        self.settings.set("transcription", "speech_pad_ms", int(self.pad_spin.get_value()))
        self.settings.set("transcription", "no_speech_threshold", self.threshold_spin.get_value())
        
        # Language detection settings
        self.settings.set("transcription", "auto_detect_language", self.auto_detect_lang_switch.get_active())
        
        # Parse expected languages from comma-separated string
        expected_langs_str = self.expected_langs_entry.get_text()
        expected_langs = [lang.strip() for lang in expected_langs_str.split(",") if lang.strip()]
        self.settings.set("transcription", "expected_languages", expected_langs)

        # Speakers
        for i in range(1, 7):
            self.settings.set("speakers", f"speaker_{i}_color", self._rgba_to_css(self.speaker_color_btns[i].get_rgba()))
        self.settings.set("speakers", "unknown_speaker_color", self._rgba_to_css(self.unknown_speaker_color_btn.get_rgba()))

        # Translation
        self.settings.set("translation", "provider", "ollama")
        selected_model = self.model_combo.get_active_text()
        if selected_model:
            self.settings.set("translation", "model", selected_model)
        self.settings.set("translation", "target_language", self.target_lang_entry.get_text())

        start_iter = self.prompt_buffer.get_start_iter()
        end_iter = self.prompt_buffer.get_end_iter()
        self.settings.set("translation", "prompt", self.prompt_buffer.get_text(start_iter, end_iter, False))

        # Logging
        self.settings.set("logging", "enabled", self.logging_enabled_switch.get_active())
        self.settings.set("logging", "log_path", self.log_path_entry.get_text())
        self.settings.set("logging", "log_original", self.log_original_switch.get_active())
        self.settings.set("logging", "log_translated", self.log_translated_switch.get_active())

        # AI Assistant
        self.settings.set("ai_assistant", "enabled", self.ai_enabled_switch.get_active())
        self.settings.set("ai_assistant", "use_translation_model", self.ai_use_trans_model_switch.get_active())
        selected_ai_model = self.ai_model_combo.get_active_text()
        if selected_ai_model and selected_ai_model != "No models found":
            self.settings.set("ai_assistant", "model", selected_ai_model)
        self.settings.set("ai_assistant", "context_entries", int(self.ai_context_spin.get_value()))
        self.settings.set("ai_assistant", "auto_detect_questions", self.ai_auto_detect_switch.get_active())
        self.settings.set("ai_assistant", "show_tips_on_failure", self.ai_tips_switch.get_active())
        self.settings.set("ai_assistant", "auto_translate_response", self.ai_auto_translate_switch.get_active())
        self.settings.set("appearance", "ai_response_color", self._rgba_to_css(self.ai_color_btn.get_rgba()))
        self.settings.set("appearance", "ai_font_size", int(self.ai_size_spin.get_value()))

        # Reverse Translation
        self.settings.set("reverse_translation", "enabled", self.reverse_enabled_switch.get_active())
        self.settings.set("reverse_translation", "auto_start", self.reverse_auto_start_switch.get_active())
        self.settings.set("reverse_translation", "source_language", self.reverse_source_lang_entry.get_text())
        self.settings.set("reverse_translation", "target_language", self.reverse_target_lang_entry.get_text())
        
        # Input device (skip "Default" which means empty string)
        selected_device = self.reverse_input_device_combo.get_active_text()
        if selected_device and selected_device not in ["Default", "Loading..."]:
            self.settings.set("reverse_translation", "input_device", selected_device)
        else:
            self.settings.set("reverse_translation", "input_device", "")
        
        self.settings.set("reverse_translation", "tts_engine", self.reverse_tts_engine_combo.get_active_text())
        self.settings.set("reverse_translation", "tts_voice", self.reverse_tts_voice_entry.get_text())
        self.settings.set("reverse_translation", "tts_speed", self.reverse_tts_speed_scale.get_value())
        self.settings.set("reverse_translation", "virtual_sink_name", self.reverse_sink_name_entry.get_text())

    def _validate_settings(self):
        """Validate all settings before applying."""
        errors = []

        # Validate target language
        target_lang = self.target_lang_entry.get_text().strip()
        if not target_lang:
            errors.append("Target language cannot be empty")

        # Validate source language
        source_lang = self.source_lang_entry.get_text().strip()
        if not source_lang:
            errors.append("Source language cannot be empty")

        # Validate log path
        log_path = self.log_path_entry.get_text().strip()
        if not log_path:
            errors.append("Log path cannot be empty")

        # Validate virtual sink name for reverse translation
        sink_name = self.reverse_sink_name_entry.get_text().strip()
        if not sink_name:
            errors.append("Virtual sink name cannot be empty")

        return errors

    def _show_validation_errors(self, errors):
        """Show validation error dialog."""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Validation Errors"
        )
        dialog.format_secondary_text("\n".join(errors))
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def _on_apply(self, button):
        """Apply settings without saving."""
        if self._is_waiting_for_reload:
            return

        errors = self._validate_settings()
        if errors:
            self._show_validation_errors(errors)
            return
        self._collect_settings()
        if self.on_apply_callback:
            result = self.on_apply_callback(self.settings)
            self._handle_apply_result(result)

    def _on_save(self, button):
        """Save settings and close."""
        if self._is_waiting_for_reload:
            return

        errors = self._validate_settings()
        if errors:
            self._show_validation_errors(errors)
            return
        self._collect_settings()
        self.settings.save()
        if self.on_apply_callback:
            result = self.on_apply_callback(self.settings)
            self._handle_apply_result(result)
        self.close()

    def _handle_apply_result(self, result):
        """Handle app response after applying settings."""
        if isinstance(result, dict) and result.get("transcriber_reload_in_progress"):
            self._set_reload_waiting_state(True)
            GLib.timeout_add(300, self._poll_reload_state)

    def _set_reload_waiting_state(self, waiting):
        """Show/hide reload indicator and block repeated Apply clicks."""
        self._is_waiting_for_reload = waiting
        self.apply_btn.set_sensitive(not waiting)
        self.save_btn.set_sensitive(not waiting)
        self.reload_spinner.set_visible(waiting)
        self.reload_status_label.set_visible(waiting)
        if waiting:
            self.reload_spinner.start()
        else:
            self.reload_spinner.stop()

    def _poll_reload_state(self):
        """Poll app state and unlock controls when model reload is complete."""
        app = getattr(self.parent_window, "app", None)
        is_busy = bool(app and hasattr(app, "is_transcriber_reload_in_progress") and app.is_transcriber_reload_in_progress())
        if is_busy:
            return True

        self._set_reload_waiting_state(False)
        return False

    def _load_ollama_models(self):
        """Load Ollama models in background thread."""
        def fetch_models():
            models = get_ollama_models()
            GLib.idle_add(self._populate_model_combo, models)

        threading.Thread(target=fetch_models, daemon=True).start()

    def _populate_model_combo(self, models):
        """Populate model combo box with fetched models."""
        self.ollama_models = models
        self.model_combo.remove_all()

        current_model = self.settings.get("translation", "model", "mistral:7b")
        active_index = 0

        for i, model in enumerate(models):
            self.model_combo.append_text(model)
            if model == current_model:
                active_index = i

        if models:
            self.model_combo.set_active(active_index)
        else:
            # No models found, add placeholder
            self.model_combo.append_text("No models found")
            self.model_combo.set_active(0)

    def _on_refresh_models(self, button):
        """Refresh model list."""
        self.model_combo.remove_all()
        self.model_combo.append_text("Loading...")
        self.model_combo.set_active(0)
        self._load_ollama_models()
