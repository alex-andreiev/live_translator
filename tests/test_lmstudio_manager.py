"""Tests for the LM Studio model manager widget and its download plumbing."""
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from live_translator.ai.providers import create_adapter, ProviderError
from live_translator.ai.providers.lmstudio import parse_progress
from live_translator.ai.providers.lmstudio_catalog import TRANSLATION_MODELS

GEMMA = {"type": "llm", "key": "google/gemma-4-e4b", "display_name": "Gemma 4 E4B",
         "params_string": "7.5B", "size_bytes": 6326937801,
         "quantization": {"name": "Q4_K_M"}, "max_context_length": 131072,
         "loaded_instances": []}


def _gtk():
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import Gtk
    if not Gtk.init_check():
        raise unittest.SkipTest("no display")
    return Gtk


class ProgressTests(unittest.TestCase):
    def test_progress_is_parsed_from_a_bar(self):
        self.assertEqual(parse_progress("[###  ] 88.33% | 3.90 GB / 4.41 GB | 755 KB/s"),
                         "Downloading 88% (3.90 GB of 4.41 GB)")

    def test_last_reading_in_a_chunk_wins(self):
        chunk = "1% | 10 MB / 1.9 GB\r7% | 140 MB / 1.9 GB\r"
        self.assertIn("140 MB", parse_progress(chunk))

    def test_non_progress_output_is_ignored(self):
        for text in ("", "Searching staff picks", "Error: not found"):
            self.assertIsNone(parse_progress(text))


class DownloadTests(unittest.TestCase):
    def _download(self, chunks, returncode=0, cancel=None):
        process = MagicMock()
        process.stdout.read.side_effect = list(chunks) + [""]
        process.returncode = returncode
        seen = []
        with patch('live_translator.ai.providers.lmstudio.shutil.which', return_value='/bin/lms'), \
             patch('live_translator.ai.providers.lmstudio.subprocess.Popen', return_value=process) as popen:
            adapter = create_adapter('lmstudio')
            result = adapter.download('m', on_progress=seen.append, cancel=cancel)
        return result, seen, popen, process

    def test_progress_is_reported_and_command_is_correct(self):
        _, seen, popen, _ = self._download(["50% | 1 GB / 2 GB"])
        self.assertTrue(any("50%" in s for s in seen))
        command = popen.call_args.args[0]
        self.assertEqual(command[1:], ["get", "m", "-y", "--gguf"])

    def test_a_failed_download_surfaces_the_lms_error(self):
        with self.assertRaisesRegex(ProviderError, "No staff picks"):
            self._download(["Searching\nError: No staff picks found.\n"], returncode=1)

    def test_failure_without_an_error_line_still_raises(self):
        with self.assertRaisesRegex(ProviderError, "Download failed"):
            self._download(["some output"], returncode=1)

    def test_cancelling_terminates_the_process(self):
        with self.assertRaisesRegex(ProviderError, "cancelled"):
            self._download(["1% | 1 MB / 2 GB"], cancel=lambda: True)

    def test_a_missing_cli_is_reported(self):
        with patch('live_translator.ai.providers.lmstudio.shutil.which', return_value=None), \
             patch('live_translator.ai.providers.lmstudio.Path.home',
                   return_value=__import__('pathlib').Path('/nonexistent')):
            with self.assertRaisesRegex(ProviderError, "lms CLI"):
                create_adapter('lmstudio').download('m')


class ModelRowTests(unittest.TestCase):
    def setUp(self):
        _gtk()
        from live_translator.ui.lmstudio_manager import ModelRow
        self.ModelRow = ModelRow

    def test_verdicts_reflect_the_budget(self):
        row = self.ModelRow("m", 4096, True)
        self.assertEqual(row.verdict(8192)[0], "fits")
        self.assertEqual(row.verdict(4300)[0], "tight")
        self.assertEqual(row.verdict(2048)[0], "too-large")
        self.assertEqual(row.verdict(None)[0], "unknown")

    def test_summary_states_download_and_load_status(self):
        self.assertIn("not downloaded", self.ModelRow("m", 2048, False).summary(8192))
        self.assertIn("· downloaded ·", self.ModelRow("m", 2048, True).summary(8192))
        self.assertIn("loaded", self.ModelRow("m", 2048, True, instances=1).summary(8192))

    def test_approximate_sizes_are_marked(self):
        def size_field(row):
            # "icon  name  —  <size> · state · verdict"; the verdict also carries a
            # size, so compare only the dedicated size column.
            return row.summary(8192).split("—")[1].split("·")[0].strip()

        self.assertEqual(size_field(self.ModelRow("m", 2048, False, approximate=True)), "~2.0 GB")
        self.assertEqual(size_field(self.ModelRow("m", 2048, True)), "2.0 GB")


class ManagerTests(unittest.TestCase):
    def setUp(self):
        _gtk()
        from live_translator.ui.lmstudio_manager import LMStudioManager
        self.manager = LMStudioManager(lambda: 5685, lambda: {})

    def _adapter(self, entries=(GEMMA,), estimate=6676):
        adapter = MagicMock()
        adapter.model_details.return_value = list(entries)
        adapter.estimate_load_mb.return_value = estimate
        return adapter

    def test_downloaded_and_catalog_rows_are_merged(self):
        rows = self.manager._collect(self._adapter())
        self.assertEqual(rows[0].name, "google/gemma-4-e4b")
        self.assertTrue(rows[0].downloaded)
        # Measured estimate replaces the disk size for the fit verdict.
        self.assertEqual(rows[0].required_mb, 6676)
        self.assertEqual(rows[0].verdict(5685)[0], "too-large")
        self.assertEqual(len(rows), 1 + len(TRANSLATION_MODELS))
        self.assertTrue(all(not r.downloaded for r in rows[1:]))

    def test_a_downloaded_catalog_model_is_not_listed_twice(self):
        entry = {**GEMMA, "key": "qwen/qwen3-4b"}
        names = [r.name for r in self.manager._collect(self._adapter([entry]))]
        self.assertEqual(names.count("qwen3-4b"), 0)
        self.assertIn("qwen/qwen3-4b", names)

    def test_disk_size_is_used_when_no_estimate_is_available(self):
        rows = self.manager._collect(self._adapter(estimate=None))
        self.assertEqual(rows[0].required_mb, rows[0].size_mb)

    def test_buttons_track_the_selected_row_state(self):
        from live_translator.ui.lmstudio_manager import ModelRow
        cases = [
            (ModelRow("a", 2048, False), {"download": True, "load": False, "unload": False, "use": False}),
            (ModelRow("b", 2048, True), {"download": False, "load": True, "unload": False, "use": True}),
            (ModelRow("c", 2048, True, instances=1), {"download": False, "load": False, "unload": True, "use": True}),
        ]
        for row, expected in cases:
            self.manager.rows = [row]
            self.manager._render()
            self.manager.list.select_row(self.manager.list.get_row_at_index(0))
            for key, value in expected.items():
                self.assertEqual(self.manager.buttons[key].get_sensitive(), value,
                                 f"{row.name} {key}")

    def test_use_for_translation_reports_the_chosen_model(self):
        from live_translator.ui.lmstudio_manager import ModelRow
        chosen = []
        self.manager.on_model_chosen = chosen.append
        self.manager.rows = [ModelRow("pick/me", 2048, True)]
        self.manager._render()
        self.manager.list.select_row(self.manager.list.get_row_at_index(0))
        self.manager.buttons["use"].emit("clicked")
        self.assertEqual(chosen, ["pick/me"])

    def test_actions_are_inert_without_a_selection(self):
        self.manager.rows = []
        self.manager._render()
        for key in ("download", "load", "unload", "use"):
            self.manager.buttons[key].emit("clicked")
        self.assertFalse(self.manager.busy)


if __name__ == '__main__':
    unittest.main()
