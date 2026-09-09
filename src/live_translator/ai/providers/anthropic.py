import os
from .base import ProviderError


class AnthropicAdapter:
    def __init__(self, api_key="", base_url="", timeout=30, **kwargs):
        self.options = {"timeout": timeout}
        if api_key or os.environ.get("ANTHROPIC_API_KEY"):
            self.options["api_key"] = api_key or os.environ["ANTHROPIC_API_KEY"]
        if base_url:
            self.options["base_url"] = base_url

    def _client(self):
        try:
            import anthropic
        except ImportError:
            raise ProviderError('Install the optional dependency: pip install "live-translator[anthropic]"') from None
        return anthropic.Anthropic(**self.options)

    def list_models(self):
        with self._client() as client:
            return [m.id for m in client.models.list()]

    def generate(self, model, prompt):
        with self._client() as client:
            response = client.messages.create(model=model, max_tokens=1024,
                                             messages=[{"role": "user", "content": prompt}])
            return "\n".join(b.text for b in response.content if b.type == "text").strip()
