"""Each integration owns its adapter; consumers use this registry."""
from .base import ProviderError
from .ollama import OllamaAdapter
from .lmstudio import LMStudioAdapter
from .deepseek import DeepSeekAdapter
from .openai import OpenAIAdapter
from .anthropic import AnthropicAdapter

PROVIDERS = {
    "none": ("Disabled (transcription only)", "", ""),
    "ollama": ("Ollama (local)", OllamaAdapter.default_url, "mistral:7b"),
    "lmstudio": ("LM Studio (local)", LMStudioAdapter.default_url, ""),
    "deepseek": ("DeepSeek API", DeepSeekAdapter.default_url, "deepseek-v4-flash"),
    "openai": ("OpenAI API", OpenAIAdapter.default_url, ""),
    "anthropic": ("Anthropic API", "https://api.anthropic.com", ""),
}
ADAPTERS = {"ollama": OllamaAdapter, "lmstudio": LMStudioAdapter, "deepseek": DeepSeekAdapter,
            "openai": OpenAIAdapter, "anthropic": AnthropicAdapter}


def create_adapter(provider, **options):
    if provider not in ADAPTERS:
        raise ProviderError(f"Unsupported provider: {provider}")
    return ADAPTERS[provider](**options)
