from __future__ import annotations

import httpx


class AiProviderError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class ResponsesProvider:
    """No provider bodies/credentials in exceptions, logs or public responses."""

    def __init__(self, *, api_key: str, model: str, max_output_tokens: int):
        self.api_key = api_key
        self.model = model
        self.max_output_tokens = max_output_tokens

    def respond(self, *, instructions: str, items: list[dict], tools: list[dict], timeout: float) -> dict:
        try:
            with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                response = client.post(
                    "https://api.openai.com/v1/responses",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model, "instructions": instructions,
                          "input": items, "tools": tools, "store": False,
                          "include": ["reasoning.encrypted_content"],
                          "parallel_tool_calls": False,
                          "max_output_tokens": self.max_output_tokens},
                )
                if response.status_code in {401, 403}:
                    raise AiProviderError("AI_PROVIDER_ACCESS")
                if response.status_code == 429:
                    raise AiProviderError("AI_PROVIDER_LIMIT")
                if not response.is_success:
                    raise AiProviderError("AI_PROVIDER_UNAVAILABLE")
                data = response.json()
        except httpx.TimeoutException:
            raise AiProviderError("AI_PROVIDER_TIMEOUT") from None
        except (httpx.HTTPError, ValueError):
            raise AiProviderError("AI_PROVIDER_UNAVAILABLE") from None
        if not isinstance(data, dict) or data.get("status") != "completed" or not isinstance(data.get("output"), list):
            raise AiProviderError("AI_PROVIDER_INCOMPLETE")
        return data
