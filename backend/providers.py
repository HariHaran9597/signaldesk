"""Hosted inference with a fixed destination, free-only model IDs, and no fallback."""
import asyncio
import json
import re
from decimal import Decimal, InvalidOperation

import httpx

BASE_URL = "https://api.experientiallabs.ai/api/v1"


class ProviderError(Exception):
    pass


class Experiential:
    def __init__(self, api_key, model, max_calls=6, transport=None):
        if not api_key:
            raise ProviderError("missing_api_key")
        if not re.fullmatch(r"[a-zA-Z0-9_./-]+:free", model):
            raise ProviderError("free_only_model_required")
        self.api_key = api_key
        self.model = model
        self.max_calls = max(1, min(40, max_calls))
        self.calls = 0
        self.available = False
        self.blocked = False
        self.transport = transport
        self.last_usage = None

    async def request(self, method, path, payload=None):
        async with asyncio.timeout(120):
            async with httpx.AsyncClient(timeout=115, trust_env=False, follow_redirects=False,
                                         transport=self.transport) as client:
                async with client.stream(method, BASE_URL + path, headers={"Authorization": f"Bearer {self.api_key}"}, json=payload) as response:
                    if response.status_code != 200:
                        self.blocked = True
                        raise ProviderError(f"provider_http_{response.status_code}")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 2_000_000:
                            self.blocked = True
                            raise ProviderError("provider_response_too_large")
        return json.loads(body)

    async def preflight(self):
        if self.blocked:
            raise ProviderError("provider_stopped")
        catalog = await self.request("GET", "/models")
        if not any(entry.get("id") == self.model for entry in catalog.get("data", [])):
            self.blocked = True
            raise ProviderError("free_model_unavailable")
        self.available = True

    async def generate(self, system, payload, schema, output_tokens):
        self.last_usage = None
        if self.blocked:
            raise ProviderError("provider_stopped")
        if self.calls >= self.max_calls:
            raise ProviderError("run_request_limit")
        if not self.available:
            await self.preflight()
        self.calls += 1
        result = await self.request("POST", "/chat/completions", {
            "model": self.model,
            "messages": [{"role": "system", "content": system + "\nReturn JSON matching this schema: " + json.dumps(schema.model_json_schema())},
                         {"role": "user", "content": json.dumps(payload)}],
            "max_tokens": min(output_tokens + 1600, 2400),
            "response_format": {"type": "json_object"},
            "gateway": {"routing": {"allow_fallbacks": False}},
        })
        usage = result.get("usage", {})
        cost = usage.get("cost")
        try:
            zero_cost = cost is not None and Decimal(str(cost)).is_finite() and Decimal(str(cost)) == 0
        except InvalidOperation:
            zero_cost = False
        if not zero_cost or usage.get("is_byok") is True:
            self.blocked = True
            raise ProviderError("free_cost_not_confirmed")
        self.last_usage = {"provider": "experiential", "model": self.model,
                           "input_tokens": usage.get("prompt_tokens", 0),
                           "output_tokens": usage.get("completion_tokens", 0), "cost_usd": "0"}
        ignored = result.get("x-experiential-ignored-parameters", [])
        if "max_tokens" in ignored:
            self.blocked = True
            raise ProviderError("output_limit_not_honored")
        choice = result.get("choices", [{}])[0]
        if choice.get("finish_reason") != "stop":
            raise ProviderError("incomplete_model_response")
        parsed = schema.model_validate_json(choice.get("message", {}).get("content", ""))
        return parsed.model_dump(), self.last_usage
