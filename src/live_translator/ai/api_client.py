"""Shared API facade for translation, reverse mode and the assistant."""
from .providers import create_adapter, ProviderError


class APIClient:
    def __init__(self, provider="ollama", model="mistral:7b", timeout=30):
        self.provider = provider
        self.model = model
        self.timeout = timeout
        self.last_error = None

    def set_settings(self, provider=None, model=None, timeout=None):
        if provider is not None:
            self.provider = provider
        if model is not None:
            self.model = model
        if timeout is not None:
            self.timeout = timeout

    def generate(self, prompt):
        self.last_error = None
        if not prompt or not prompt.strip() or self.provider == "none":
            return None
        from live_translator.utils.settings import get_settings
        options = get_settings().get("providers", self.provider, {}).copy()
        options.setdefault("timeout", self.timeout)
        try:
            if not self.model.strip():
                raise ProviderError("Select a model in Settings.")
            return create_adapter(self.provider, **options).generate(self.model, prompt)
        except Exception as exc:
            # Do not print SDK exception bodies that may include user content or keys.
            self.last_error = str(exc) if isinstance(exc, ProviderError) else "Provider request failed. Check connection settings."
            print(f"{self.provider}: {self.last_error}")
            return None


def generate_text(prompt, provider="ollama", model="mistral:7b", timeout=30):
    return APIClient(provider, model, timeout).generate(prompt)
