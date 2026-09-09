"""Tests for hardware detection, setting recommendations and the LM Studio catalog."""
import subprocess
import unittest
from unittest.mock import patch, MagicMock

from live_translator.ai.providers import create_adapter
from live_translator.ai.providers.lmstudio_catalog import (
    TRANSLATION_MODELS, describe_catalog, describe_commands, fitting_models, setup_commands)
from live_translator.processing.whisper_models import WHISPER_MODELS, estimated_vram_mb
from live_translator.utils import hardware as hw


def machine(vram_total=None, vram_free=None, cores=16, ram=32, cuda=1):
    return {"cpu_cores": cores, "total_ram_gb": ram,
            "cuda_devices": cuda if vram_total else 0,
            "compute_types": {"cpu": {"int8", "float32"},
                              "cuda": {"int8", "float16", "float32"} if vram_total else set()},
            "gpu_name": "Test GPU" if vram_total else None,
            "vram_total_mb": vram_total, "vram_free_mb": vram_free}


class VramEstimateTests(unittest.TestCase):
    def test_estimates_are_ordered_and_quantization_aware(self):
        for compute in ("int8", "float16"):
            sizes = [estimated_vram_mb(m, compute) for m in
                     ("tiny", "base", "small", "medium", "large-v3")]
            self.assertEqual(sizes, sorted(sizes))
        for model in WHISPER_MODELS:
            self.assertLess(estimated_vram_mb(model, "int8"),
                            estimated_vram_mb(model, "float16"))
        self.assertIsNone(estimated_vram_mb("custom-finetune"))


class TranscriptionRecommendationTests(unittest.TestCase):
    def test_cpu_only_machine_never_recommends_cuda(self):
        for cores in (2, 8, 16):
            settings, reasons = hw.recommend_transcription(machine(cores=cores))
            self.assertEqual(settings["device"], "cpu")
            self.assertEqual(settings["compute_type"], "int8")
            self.assertFalse(settings["enable_diarization"])
            self.assertTrue(reasons)

    def test_large_models_are_never_recommended_for_live_use(self):
        settings, _ = hw.recommend_transcription(machine(vram_total=24576))
        self.assertIn(settings["whisper_model"], hw.LIVE_MODEL_ORDER)

    def test_llm_reserve_shrinks_the_chosen_model(self):
        unreserved, _ = hw.recommend_transcription(machine(vram_total=8188))
        reserved, _ = hw.recommend_transcription(machine(vram_total=8188), llm_reserve_mb=6000)
        order = hw.LIVE_MODEL_ORDER
        self.assertLessEqual(order.index(unreserved["whisper_model"]),
                             order.index(reserved["whisper_model"])
                             if reserved["device"] == "cuda" else len(order))

    def test_an_llm_that_fills_the_gpu_pushes_whisper_to_cpu(self):
        settings, reasons = hw.recommend_transcription(machine(vram_total=8188),
                                                       llm_reserve_mb=8000)
        self.assertEqual(settings["device"], "cpu")
        self.assertTrue(any("too little VRAM" in r for r in reasons))

    def test_recommendation_plans_from_total_not_transient_free_vram(self):
        """A model loaded right now must not permanently shrink the plan."""
        busy = hw.recommend_transcription(machine(vram_total=8188, vram_free=300))
        idle = hw.recommend_transcription(machine(vram_total=8188, vram_free=8000))
        self.assertEqual(busy[0], idle[0])


class SetupPlanTests(unittest.TestCase):
    def _plan(self, hardware, installed):
        with patch.object(hw, '_installed_local_models', return_value=installed):
            return hw.recommend_setup(hardware, refine=False)

    def test_both_models_are_budgeted_against_one_gpu(self):
        plan = self._plan(machine(vram_total=8188),
                          [("ollama", "llama3.1:latest", 5600)])
        whisper = estimated_vram_mb(plan["transcription"]["whisper_model"],
                                    plan["transcription"]["compute_type"])
        self.assertEqual(plan["translation"], {"provider": "ollama", "model": "llama3.1:latest"})
        self.assertLessEqual(whisper + 5600, 8188)

    def test_oversized_models_yield_suggestions_instead_of_a_bad_pick(self):
        plan = self._plan(machine(vram_total=8188), [("lmstudio", "google/gemma-4-e4b", 6676)])
        self.assertIsNone(plan["translation"])
        self.assertTrue(plan["suggestions"])
        self.assertTrue(all(e[2] * 1024 < 8188 for e in plan["suggestions"]))

    def test_code_and_reasoning_models_are_filtered_out(self):
        plan = self._plan(machine(vram_total=8188),
                          [("ollama", "qwen2.5-coder:14b", 3000),
                           ("ollama", "deepseek-r1:7b", 3000),
                           ("ollama", "nomic-embed-text:latest", 300)])
        self.assertIsNone(plan["translation"])

    def test_reasoning_models_are_excluded_from_live_translation(self):
        """They emit a think block first; measured at ~27s/sentence versus ~1.5s."""
        plan = self._plan(machine(vram_total=8188),
                          [("ollama", "qwen3:latest", 3000),
                           ("ollama", "qwq:32b", 3000),
                           ("ollama", "deepseek-r1:7b", 3000)])
        self.assertIsNone(plan["translation"])

    def test_no_gpu_prefers_the_lightest_installed_model(self):
        plan = self._plan(machine(), [("ollama", "mistral:7b", 4400),
                                      ("ollama", "llama3.2:latest", 2000)])
        self.assertEqual(plan["transcription"]["device"], "cpu")
        self.assertEqual(plan["translation"]["model"], "llama3.2:latest")

    def test_unreachable_providers_do_not_raise(self):
        plan = self._plan(machine(vram_total=8188), [])
        self.assertIsNone(plan["translation"])
        self.assertIn("hardware", plan)


class DetectionTests(unittest.TestCase):
    def test_missing_nvidia_smi_reports_no_gpu(self):
        with patch.object(hw.shutil, 'which', return_value=None), \
             patch.object(hw, '_compute_types', return_value=({}, 0)):
            detected = hw.detect_hardware()
        self.assertIsNone(detected["vram_total_mb"])
        self.assertIn("no CUDA GPU detected", hw.describe_hardware(detected))

    def test_gpu_query_is_parsed(self):
        with patch.object(hw.shutil, 'which', return_value='/usr/bin/nvidia-smi'), \
             patch.object(hw, '_run', return_value="NVIDIA Test GPU, 8188, 2438\n"), \
             patch.object(hw, '_compute_types', return_value=({"cuda": {"int8"}}, 1)):
            detected = hw.detect_hardware()
        self.assertEqual((detected["vram_total_mb"], detected["vram_free_mb"]), (8188, 2438))
        self.assertIn("8.0 GB VRAM", hw.describe_hardware(detected))

    def test_unparseable_or_failed_query_is_survivable(self):
        for output in (None, "", "garbage output"):
            with patch.object(hw.shutil, 'which', return_value='/usr/bin/nvidia-smi'), \
                 patch.object(hw, '_run', return_value=output), \
                 patch.object(hw, '_compute_types', return_value=({}, 0)):
                self.assertIsNone(hw.detect_hardware()["vram_total_mb"])


class CatalogTests(unittest.TestCase):
    def test_catalog_shortlists_by_budget(self):
        self.assertEqual(fitting_models(0), [])
        small = fitting_models(2.2 * 1024)
        self.assertTrue(small and all(e[2] <= 2.2 for e in small))
        self.assertEqual(len(fitting_models(100 * 1024)), len(TRANSLATION_MODELS))

    def test_catalog_marks_fit_against_a_budget(self):
        rendered = describe_catalog(3 * 1024)
        self.assertIn("✓ fits", rendered)
        self.assertIn("✗ too large", rendered)
        self.assertNotIn("fits", describe_catalog())

    def test_commands_cover_the_lifecycle_and_carry_the_model(self):
        commands = [c for c, _ in setup_commands("my-model", 4096)]
        joined = "\n".join(commands)
        for expected in ("lms ls", "lms ps", "lms get my-model", "--estimate-only",
                         "lms server start", "--context-length 4096", "lms unload --all"):
            self.assertIn(expected, joined)
        self.assertIn("$ lms", describe_commands("my-model"))

    def test_placeholder_used_when_no_model_given(self):
        self.assertIn("lms get <model>", describe_commands())


class EstimatorTests(unittest.TestCase):
    def _estimate(self, returncode=0, stderr="", stdout=""):
        result = MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)
        with patch('live_translator.ai.providers.lmstudio.shutil.which', return_value='/bin/lms'), \
             patch('live_translator.ai.providers.lmstudio.subprocess.run', return_value=result) as run:
            value = create_adapter('lmstudio').estimate_load_mb('m', 8192)
        return value, run

    def test_estimate_is_read_from_stderr_where_lms_writes_it(self):
        value, run = self._estimate(stderr="Estimated GPU Memory:   6.52 GiB\n")
        self.assertEqual(value, 6676)
        self.assertIn("--estimate-only", run.call_args.args[0])
        self.assertIn("8192", run.call_args.args[0])

    def test_mib_and_stdout_are_both_accepted(self):
        self.assertEqual(self._estimate(stdout="Estimated GPU Memory: 512 MiB")[0], 512)

    def test_failures_return_none_rather_than_guessing(self):
        self.assertIsNone(self._estimate(returncode=1, stderr="boom")[0])
        self.assertIsNone(self._estimate(stderr="no estimate here")[0])
        with patch('live_translator.ai.providers.lmstudio.shutil.which', return_value='/bin/lms'), \
             patch('live_translator.ai.providers.lmstudio.subprocess.run',
                   side_effect=subprocess.TimeoutExpired('lms', 120)):
            self.assertIsNone(create_adapter('lmstudio').estimate_load_mb('m'))


if __name__ == '__main__':
    unittest.main()
