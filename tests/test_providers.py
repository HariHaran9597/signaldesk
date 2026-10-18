import asyncio
import json

import httpx
import pytest

from backend.briefing import Review
from backend.providers import Experiential, ProviderError

MODEL = "deepseek/deepseek-v4.1-flash-1017:free"


def response(cost=0, finish="stop"):
    return {"choices": [{"finish_reason": finish, "message": {"content": '{"supported":true,"issues":[]}'}}], "usage": {"cost": cost, "prompt_tokens": 20, "completion_tokens": 10}}


def test_paid_model_is_rejected_before_network():
    with pytest.raises(ProviderError, match="free_only_model_required"):
        Experiential("test-key", MODEL.removesuffix(":free"))


def test_free_request_limits_schema_and_cost():
    seen = []
    def handler(request):
        assert request.url.host == "api.experientiallabs.ai"
        assert request.headers["authorization"] == "Bearer test-key"
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": MODEL}]})
        body = json.loads(request.content)
        assert body["model"].endswith(":free")
        assert body["max_tokens"] == 2000
        assert body["gateway"]["routing"]["allow_fallbacks"] is False
        return httpx.Response(200, json=response())
    provider = Experiential("test-key", MODEL, max_calls=1, transport=httpx.MockTransport(handler))
    result, usage = asyncio.run(provider.generate("Review", {}, Review, 400))
    assert result["supported"] is True
    assert usage["cost_usd"] == "0"
    with pytest.raises(ProviderError, match="run_request_limit"):
        asyncio.run(provider.generate("Review", {}, Review, 400))
    assert len(seen) == 2


@pytest.mark.parametrize("cost", [None, 0.01, "unknown", "NaN"])
def test_unknown_or_nonzero_cost_stops_following_calls(cost):
    calls = []
    def handler(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": MODEL}]})
        return httpx.Response(200, json=response(cost))
    provider = Experiential("test-key", MODEL, transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="free_cost_not_confirmed"):
        asyncio.run(provider.generate("Review", {}, Review, 400))
    with pytest.raises(ProviderError, match="provider_stopped"):
        asyncio.run(provider.generate("Review", {}, Review, 400))
    assert len(calls) == 2


@pytest.mark.parametrize("status", [302, 401, 429, 503])
def test_errors_and_redirects_never_fallback(status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"Location": "https://other.example/"}, json={"error": "private diagnostic"})
    provider = Experiential("test-key", MODEL, transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match=f"provider_http_{status}"):
        asyncio.run(provider.generate("Review", {}, Review, 400))
    assert provider.blocked
    assert len(calls) == 1


def test_unavailable_free_lane_does_not_send_completion():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [{"id": MODEL.removesuffix(":free")}]})
    provider = Experiential("test-key", MODEL, transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="free_model_unavailable"):
        asyncio.run(provider.generate("Review", {}, Review, 400))
    assert len(calls) == 1


def test_truncated_response_retains_cost_without_accepting_draft():
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": MODEL}]})
        return httpx.Response(200, json=response(finish="length"))
    provider = Experiential("test-key", MODEL, transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="incomplete_model_response"):
        asyncio.run(provider.generate("Review", {}, Review, 400))
    assert provider.last_usage["cost_usd"] == "0"
