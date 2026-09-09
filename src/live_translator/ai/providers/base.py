"""Small dependency-free HTTP transport shared by provider adapters."""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class ProviderError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward credentials to a redirect destination.


class HTTPAdapter:
    default_url = ""
    key_env = ""
    requires_key = False

    def __init__(self, base_url="", api_key="", timeout=30, **kwargs):
        self.base_url = (base_url or self.default_url).rstrip("/")
        self.api_key = api_key or os.environ.get(self.key_env, "")
        self.timeout = float(timeout)
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ProviderError("Enter a valid HTTP(S) server URL without credentials, query or fragment.")
        if self.api_key and parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ProviderError("API keys require HTTPS except for a local server.")

    def request(self, path, payload=None):
        if self.requires_key and not self.api_key:
            raise ProviderError(f"Enter an API key or set {self.key_env}.")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(self.base_url + path, headers=headers,
                          data=json.dumps(payload).encode() if payload is not None else None)
        try:
            with build_opener(NoRedirect()).open(request, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            hints = {401: "Check the API key.", 403: "Access denied.", 404: "Check the endpoint, model and server version.",
                     429: "Rate limit or quota reached. Try later."}
            # Auth failures are the one case where a body could echo credentials.
            detail = "" if exc.code in (401, 403) else self._error_detail(exc)
            raise ProviderError(f"HTTP {exc.code}. {hints.get(exc.code, 'Provider request failed.')}{detail}") from None
        except (URLError, TimeoutError, OSError):
            raise ProviderError("Cannot reach provider or request timed out. Check server, URL and timeout.") from None
        except (ValueError, TypeError):
            raise ProviderError("Provider returned invalid JSON.") from None

    @staticmethod
    def _error_detail(exc):
        """Provider-supplied message; far more actionable than a bare status code."""
        try:
            body = json.loads(exc.read().decode("utf-8", "replace"))
        except Exception:
            return ""
        if not isinstance(body, dict):
            return ""
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message")
        elif isinstance(error, str):
            message = error
        else:
            message = body.get("message")
        if not isinstance(message, str) or not message.strip():
            return ""
        return " " + " ".join(message.split())[:200]

    def list_models(self):
        return [m["id"] for m in self.request("/models").get("data", []) if m.get("id")]

    def generate(self, model, prompt):
        response = self.request("/chat/completions", self.chat_payload(model, prompt))
        try:
            result = response["choices"][0]["message"]["content"]
            if not isinstance(result, str) or not result.strip():
                raise ValueError()
            return result.strip()
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderError("Provider returned no text completion.") from None

    def chat_payload(self, model, prompt):
        return {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}
