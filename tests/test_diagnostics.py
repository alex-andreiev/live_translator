"""The system check must catch real misconfigurations, and never crash on a broken check."""
import unittest
from unittest.mock import MagicMock, patch

from live_translator.utils import diagnostics as diag
from live_translator.utils.diagnostics import Check, OK, WARN, FAIL


def settings(**overrides):
    values = {("transcription", "device"): "cuda",
              ("transcription", "compute_type"): "float16",
              ("transcription", "whisper_model"): "small",
              ("translation", "provider"): "ollama",
              ("translation", "model"): "mistral:7b",
              ("logging", "log_path"): "~/.local/share/live-translator/logs"}
    values.update({tuple(k.split(".")): v for k, v in overrides.items()})
    stub = MagicMock()
    stub.get.side_effect = lambda c, k, d=None: values.get((c, k), d)
    return stub


class ReportingTests(unittest.TestCase):
    def test_fix_is_shown_only_for_problems(self):
        self.assertNotIn("fix:", Check("n", OK, "fine", "do a thing").line())
        self.assertIn("fix: do a thing", Check("n", FAIL, "broken", "do a thing").line())

    def test_summary_distinguishes_blocking_from_degraded(self):
        self.assertIn("All checks passed", diag.summarize([Check("a", OK, "")]))
        self.assertIn("No blocking problems", diag.summarize([Check("a", WARN, "")]))
        self.assertIn("will stop the app", diag.summarize([Check("a", FAIL, "")]))


class GpuCheckTests(unittest.TestCase):
    def _gpu(self, devices, supported, **overrides):
        module = MagicMock()
        module.get_cuda_device_count.return_value = devices
        module.get_supported_compute_types.return_value = supported
        with patch.dict('sys.modules', {'ctranslate2': module}), \
             patch.object(diag, '_cudnn_present', return_value=True):
            return diag.check_gpu(settings(**overrides))

    def test_cuda_selected_without_a_device_is_a_failure(self):
        results = self._gpu(0, {"int8"})
        device = next(r for r in results if r.name == "CUDA device")
        self.assertEqual(device.status, FAIL)
        self.assertIn("set Device to cpu", device.fix)

    def test_unsupported_compute_type_is_a_failure_and_lists_alternatives(self):
        results = self._gpu(1, {"int8", "float32"})
        compute = next(r for r in results if r.name.startswith("Compute type"))
        self.assertEqual(compute.status, FAIL)
        self.assertIn("int8", compute.detail)

    def test_a_valid_gpu_configuration_passes(self):
        self.assertTrue(all(r.status == OK for r in self._gpu(1, {"float16", "int8"})))

    def test_cpu_device_does_not_demand_cuda(self):
        results = self._gpu(0, {"int8"}, **{"transcription.device": "cpu",
                                            "transcription.compute_type": "int8"})
        self.assertTrue(all(r.status == OK for r in results))

    def test_missing_cudnn_warns_without_blocking(self):
        module = MagicMock()
        module.get_cuda_device_count.return_value = 1
        module.get_supported_compute_types.return_value = {"float16"}
        with patch.dict('sys.modules', {'ctranslate2': module}), \
             patch.object(diag, '_cudnn_present', return_value=False):
            results = diag.check_gpu(settings())
        cudnn = next(r for r in results if "cuDNN" in r.name)
        self.assertEqual(cudnn.status, WARN)


class TranslationCheckTests(unittest.TestCase):
    def _check(self, models=None, error=None, **overrides):
        adapter = MagicMock()
        if error:
            adapter.list_models.side_effect = error
        else:
            adapter.list_models.return_value = models or []
        with patch('live_translator.ai.providers.create_adapter', return_value=adapter):
            return diag.check_translation(settings(**overrides))

    def test_disabled_provider_is_reported_as_intentional(self):
        results = self._check(**{"translation.provider": "none"})
        self.assertEqual(results[0].status, OK)
        self.assertIn("transcription only", results[0].detail)

    def test_missing_model_is_a_failure(self):
        results = self._check(**{"translation.model": ""})
        self.assertEqual(results[0].status, FAIL)

    def test_a_model_the_provider_does_not_have_is_flagged(self):
        """The exact case of a cancelled download leaving a stale model in settings."""
        results = self._check(models=["other:7b"])
        model = next(r for r in results if r.name == "Translation model")
        self.assertEqual(model.status, WARN)
        self.assertIn("not in the provider's list", model.detail)

    def test_an_available_model_passes(self):
        results = self._check(models=["mistral:7b"])
        self.assertTrue(all(r.status == OK for r in results))

    def test_an_unreachable_provider_is_a_failure(self):
        from live_translator.ai.providers import ProviderError
        results = self._check(error=ProviderError("Cannot reach provider"))
        self.assertEqual(results[0].status, FAIL)
        self.assertIn("Cannot reach", results[0].detail)


class VramCheckTests(unittest.TestCase):
    def _check(self, total, llm_mb, model="medium"):
        with patch('live_translator.utils.hardware.detect_hardware',
                   return_value={"vram_total_mb": total, "cuda_devices": 1,
                                 "cpu_cores": 8, "compute_types": {}}), \
             patch('live_translator.utils.hardware.local_llm_footprint_mb', return_value=llm_mb), \
             patch('live_translator.processing.whisper_models.is_model_cached', return_value=True):
            results = diag.check_models(settings(**{"transcription.whisper_model": model}))
        return next((r for r in results if r.name == "VRAM budget"), None)

    def test_a_combination_that_does_not_fit_is_a_failure(self):
        budget = self._check(total=8188, llm_mb=6676)
        self.assertEqual(budget.status, FAIL)
        self.assertIn("Recommend for this machine", budget.fix)

    def test_a_combination_that_fits_passes(self):
        self.assertEqual(self._check(total=8188, llm_mb=3000).status, OK)

    def test_uncached_model_warns_about_the_download(self):
        with patch('live_translator.utils.hardware.detect_hardware',
                   return_value={"vram_total_mb": None, "cuda_devices": 0, "cpu_cores": 8,
                                 "compute_types": {}}), \
             patch('live_translator.processing.whisper_models.is_model_cached', return_value=False):
            results = diag.check_models(settings())
        download = next(r for r in results if "downloaded" in r.name)
        self.assertEqual(download.status, WARN)


class RobustnessTests(unittest.TestCase):
    def test_a_crashing_check_does_not_hide_the_others(self):
        with patch.object(diag, 'check_translation', side_effect=RuntimeError("boom")):
            results = diag.run_checks(settings())
        self.assertTrue(any(r.status == WARN and "boom" in r.detail for r in results))
        self.assertTrue(any(r.name.startswith("Python package") for r in results))

    def test_missing_audio_tools_are_reported_as_blocking(self):
        with patch.object(diag.shutil, 'which', return_value=None):
            results = diag.check_audio()
        backend = next(r for r in results if r.name == "Audio capture backend")
        self.assertEqual(backend.status, FAIL)
        self.assertIn("pipewire-utils", backend.fix)

    def test_render_includes_every_check_and_the_summary(self):
        text = diag.render([Check("a", OK, "fine"), Check("b", FAIL, "broken", "fix it")])
        self.assertIn("[PASS] a", text)
        self.assertIn("[FAIL] b", text)
        self.assertIn("fix: fix it", text)
        self.assertIn("will stop the app", text)


if __name__ == '__main__':
    unittest.main()
