"""Calls the OpenAI Chat Completions API with structured output (JSON schema).

OPENAI_API_KEY and OPENAI_MODEL come from the environment. Requests only go to
api.openai.com and redirects are not followed, so the key cannot leak elsewhere.
"""
import json
import os

import httpx

API_URL = "https://api.openai.com/v1/chat/completions"
TIMEOUT = httpx.Timeout(90.0, connect=10.0)


class AIServiceError(Exception):
    """`message` is safe to show to the user (never contains the key)."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class OpenAIClient:
    def __init__(self, api_key: str | None = None, model: str | None = None,
                 transport: httpx.BaseTransport | None = None):
        self.api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY") or None
        self.model = model if model is not None else os.getenv("OPENAI_MODEL") or None
        self._transport = transport

    def ensure_configured(self) -> None:
        if not self.api_key or not self.model:
            raise AIServiceError("AI review is not configured (OPENAI_API_KEY and OPENAI_MODEL).", 503)

    def complete_json(self, system: str, user: str, schema: dict, schema_name: str) -> dict:
        """Returns the parsed JSON object the model produced for `schema`."""
        self.ensure_configured()
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
        }
        try:
            with httpx.Client(timeout=TIMEOUT, follow_redirects=False, transport=self._transport) as http:
                response = http.post(API_URL, json=body, headers={"Authorization": f"Bearer {self.api_key}"})
        except httpx.TimeoutException:
            raise AIServiceError("The AI service did not respond in time. Try again later.", 504) from None
        except httpx.HTTPError:
            raise AIServiceError("Could not reach the AI service. Try again later.") from None

        status = response.status_code
        if status == 401:
            raise AIServiceError("The AI service rejected the configured API key.")
        if status == 429:
            raise AIServiceError("The AI service is rate limited or out of quota. Try again later.", 429)
        if status != 200:
            raise AIServiceError(f"The AI service returned an error ({status}).")

        try:
            choice = response.json()["choices"][0]
            message = choice["message"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise AIServiceError("The AI service returned an invalid response.") from None
        if message.get("refusal"):
            raise AIServiceError("The AI service declined to review this request.")
        if choice.get("finish_reason") == "length":
            raise AIServiceError("The AI service's answer was cut off. Try again.")
        try:
            parsed = json.loads(message.get("content") or "")
        except ValueError:
            raise AIServiceError("The AI service returned an invalid review.") from None
        if not isinstance(parsed, dict):
            raise AIServiceError("The AI service returned an invalid review.")
        return parsed
