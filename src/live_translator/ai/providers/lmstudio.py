"""LM Studio chat, model lifecycle and local server controls."""
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import urlsplit
from .base import HTTPAdapter, ProviderError


_PROGRESS = re.compile(r"([\d.]+)%.*?([\d.]+\s*[KMGT]?B)\s*/\s*([\d.]+\s*[KMGT]?B)")


def parse_progress(text):
    """Last progress reading in a chunk of lms output, or None."""
    matches = _PROGRESS.findall(text.replace("\r", "\n"))
    if not matches:
        return None
    percent, done, total = matches[-1]
    return f"Downloading {float(percent):.0f}% ({done} of {total})"


def describe_model(entry):
    """One-line summary of an /api/v1/models entry for the settings UI."""
    parts = []
    name = entry.get("display_name")
    if name and name != entry.get("key"):
        parts.append(name)
    if entry.get("params_string"):
        parts.append(f"{entry['params_string']} params")
    size = entry.get("size_bytes")
    if isinstance(size, (int, float)) and size > 0:
        parts.append(f"{size / 1e9:.2f} GB on disk")
    quantization = (entry.get("quantization") or {}).get("name")
    if quantization:
        parts.append(quantization)
    context = entry.get("max_context_length")
    if isinstance(context, int) and context > 0:
        parts.append(f"{context:,} token context")
    instances = len(entry.get("loaded_instances") or [])
    parts.append(f"loaded ({instances} instance{'s' if instances != 1 else ''})" if instances
                 else "not loaded — use Load model")
    if (entry.get("capabilities") or {}).get("vision"):
        parts.append("vision")
    return " · ".join(parts)


class LMStudioAdapter(HTTPAdapter):
    default_url = "http://localhost:1234"
    key_env = "LM_STUDIO_API_KEY"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.base_url = self.base_url.removesuffix("/v1")

    def chat_payload(self, model, prompt):
        return super().chat_payload(model, prompt)

    def generate(self, model, prompt):
        # Compatibility API for stateless translation requests.
        client = HTTPAdapter(base_url=self.base_url + "/v1", api_key=self.api_key, timeout=self.timeout)
        return client.generate(model, prompt)

    def model_details(self):
        return [m for m in self.request("/api/v1/models").get("models", []) if m.get("type") == "llm"]

    def list_models(self):
        return [m["key"] for m in self.model_details()]

    def load(self, model):
        return self.request("/api/v1/models/load", {"model": model})

    def unload(self, model):
        instances = [i["id"] for m in self.model_details() if m["key"] == model
                     for i in m.get("loaded_instances", [])]
        if not instances:
            raise ProviderError("Selected model is not loaded. Refresh the model list.")
        for instance in instances:
            self.request("/api/v1/models/unload", {"instance_id": instance})

    def estimate_load_mb(self, model, context_length=None):
        """VRAM the model needs at this context, via `lms load --estimate-only`.

        Authoritative (it accounts for the KV cache) but needs the model downloaded
        and the lms CLI present. Returns None when it cannot be determined.
        """
        executable = self._cli()
        command = [executable, "load", model, "--estimate-only", "-y"]
        if context_length:
            command += ["--context-length", str(int(context_length))]
        try:
            result = subprocess.run(command, capture_output=True, text=True,
                                    timeout=120, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode:
            return None
        # lms reports the estimate on stderr, not stdout.
        match = re.search(r"Estimated GPU Memory:\s*([\d.]+)\s*(GiB|MiB)",
                          f"{result.stderr}\n{result.stdout}")
        if not match:
            return None
        value = float(match.group(1))
        return int(value * 1024) if match.group(2) == "GiB" else int(value)

    def download(self, model, on_progress=None, cancel=None):
        """Download a model with `lms get -y`, reporting progress as it goes.

        `on_progress` receives status text; `cancel` is polled and, when it returns
        True, the download is terminated. Raises ProviderError on failure.
        """
        command = [self._cli(), "get", model, "-y", "--gguf"]
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True)
        except OSError:
            raise ProviderError("Could not start the lms CLI.") from None

        tail = ""
        try:
            while True:
                if cancel is not None and cancel():
                    process.terminate()
                    raise ProviderError("Download cancelled.")
                chunk = process.stdout.read(256)
                if not chunk:
                    break
                tail = (tail + chunk)[-4000:]
                if on_progress:
                    status = parse_progress(chunk)
                    if status:
                        on_progress(status)
        finally:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        if process.returncode:
            message = next((line.strip() for line in reversed(tail.splitlines())
                            if line.strip().startswith("Error")), "")
            raise ProviderError(message or "Download failed. Check the model name and lms output.")
        return True

    @staticmethod
    def _cli():
        """Path to the lms CLI, which LM Studio installs outside PATH by default."""
        executable = shutil.which("lms")
        fallback = Path.home() / ".lmstudio/bin/lms"
        if not executable and fallback.is_file():
            executable = str(fallback)
        if not executable:
            raise ProviderError("Install LM Studio and its lms CLI first (available in ~/.lmstudio/bin).")
        return executable

    def server(self, action):
        parsed = urlsplit(self.base_url)
        if parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ProviderError("Server controls are available only for local LM Studio.")
        if action not in ("start", "stop", "status"):
            raise ProviderError("Unknown server action.")
        command = [self._cli(), "server", action]
        if action == "start":
            command += ["--port", str(parsed.port or 1234)]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise ProviderError("LM Studio command failed or timed out. Check LM Studio.") from None
        if result.returncode:
            raise ProviderError("LM Studio command failed. Check that LM Studio or llmster is running.")
        return result.stdout.strip() or f"Server {action} completed."
