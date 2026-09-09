from .base import HTTPAdapter, ProviderError


class OllamaAdapter(HTTPAdapter):
    default_url = "http://localhost:11434"

    def list_models(self):
        return [m.get("name") or m["model"] for m in self.request("/api/tags").get("models", [])]

    def generate(self, model, prompt):
        result = self.request("/api/generate", {"model": model, "prompt": prompt, "stream": False}).get("response")
        if not isinstance(result, str) or not result.strip():
            raise ProviderError("Ollama returned no text completion.")
        return result.strip()
