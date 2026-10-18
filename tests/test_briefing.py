import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.briefing import Briefing, draft_item, workflow
from backend.db import Draft, Item, initialize, make_engine
from backend.ingest import parse_feed, persist
from backend.main import create_app
from backend.sources import SOURCES

EVIDENCE = {"id": "source-1", "excerpt": "The publisher released a new local coding model with downloadable weights.", "title": "A new coding model"}


class FakeProvider:
    model = "test-model"

    def __init__(self, quote=None, evidence_id="source-1", supported=True, fail=False):
        self.quote = quote or EVIDENCE["excerpt"]
        self.evidence_id = evidence_id
        self.supported = supported
        self.fail = fail
        self.calls = 0

    async def generate(self, system, payload, schema, output_tokens):
        self.calls += 1
        if self.fail:
            raise TimeoutError()
        if schema is Briefing:
            return {"headline": "Publisher announces a coding model", "category": "announcement", "limitations": "Only a publisher excerpt; not independently verified.", "claims": [{"text": "The publisher says it released a local coding model.", "evidence_id": self.evidence_id, "quote": self.quote}]}, {"output_tokens": 40}
        return {"supported": self.supported, "issues": [] if self.supported else ["Unsupported comparison"]}, {"output_tokens": 20}


def test_missing_evidence_prevents_model_calls():
    provider = FakeProvider()
    result = asyncio.run(workflow(provider).ainvoke({"evidence": {**EVIDENCE, "excerpt": ""}}))
    assert result["status"] == "awaiting_evidence"
    assert provider.calls == 0


def test_no_provider_prepares_evidence_without_faking_ai():
    result = asyncio.run(workflow().ainvoke({"evidence": EVIDENCE}))
    assert result["status"] == "awaiting_model"
    assert "output" not in result


@pytest.mark.parametrize("kwargs", [{"quote": "A quotation that never appeared in this article."}, {"evidence_id": "invented-source"}])
def test_invalid_citations_are_held_before_review(kwargs):
    provider = FakeProvider(**kwargs)
    result = asyncio.run(workflow(provider).ainvoke({"evidence": EVIDENCE}))
    assert result["status"] == "held"
    assert provider.calls == 1
    assert result["issues"]


@pytest.mark.parametrize("supported, status", [(True, "needs_review"), (False, "held")])
def test_reviewer_never_publishes(supported, status):
    provider = FakeProvider(supported=supported)
    result = asyncio.run(workflow(provider).ainvoke({"evidence": EVIDENCE}))
    assert result["status"] == status
    assert provider.calls == 2


def test_schema_rejects_invented_fields_and_empty_claims():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Briefing.model_validate({"headline": "A model launch", "category": "announcement", "claims": [], "limitations": "Unknown limitations", "verified": True})


def test_persistence_cache_revision_and_read_only_api(tmp_path):
    url = f"sqlite:///{tmp_path / 'draft.db'}"
    engine = make_engine(url)
    factory = initialize(engine)
    xml = f'<rss><channel><item><title>Model launch</title><link>https://huggingface.co/blog/model</link><description>{EVIDENCE["excerpt"]}</description></item></channel></rss>'.encode()
    record = parse_feed(xml, SOURCES[0])[0]
    with factory.begin() as session:
        persist(session, [record])
    provider = FakeProvider(evidence_id=record["id"])
    first = asyncio.run(draft_item(factory, record["id"], provider))
    assert first["status"] == "needs_review"
    assert asyncio.run(draft_item(factory, record["id"], provider))["cached"]
    assert provider.calls == 2
    with factory.begin() as session:
        item = session.get(Item, record["id"])
        assert item.is_reviewed is False
        persist(session, parse_feed(xml.replace(b"Model launch", b"Corrected launch"), SOURCES[0]))
    second = asyncio.run(draft_item(factory, record["id"], provider))
    assert second["id"] != first["id"]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Draft)) == 2
    with TestClient(create_app(url)) as client:
        response = client.get("/api/drafts").json()
        assert response["publication_enabled"] is False
        assert sum(row["superseded"] for row in response["drafts"]) == 1
        assert client.post("/api/drafts").status_code == 405
        assert client.get("/api/pipeline").json()["worker"]["state"] == "not_observed"
    engine.dispose()


def test_provider_failure_retains_trace_and_is_not_published(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'draft.db'}")
    factory = initialize(engine)
    xml = f'<rss><channel><item><title>Model launch</title><link>https://huggingface.co/blog/model</link><description>{EVIDENCE["excerpt"]}</description></item></channel></rss>'.encode()
    record = parse_feed(xml, SOURCES[0])[0]
    with factory.begin() as session:
        persist(session, [record])
    result = asyncio.run(draft_item(factory, record["id"], FakeProvider(fail=True)))
    assert result["status"] == "failed"
    with factory() as session:
        draft = session.get(Draft, result["id"])
        assert draft.trace[0]["stage"] == "prepare"
        assert draft.output is None
        assert session.get(Item, record["id"]).is_reviewed is False
    provider = FakeProvider(evidence_id=record["id"])
    assert asyncio.run(draft_item(factory, record["id"], provider))["cached"]
    assert provider.calls == 0
    assert asyncio.run(draft_item(factory, record["id"], provider, retry_failed=True))["status"] == "needs_review"
    from datetime import timedelta
    from backend.db import now
    with factory.begin() as session:
        draft = session.get(Draft, result["id"])
        draft.status = "writing"
        draft.updated_at = now() - timedelta(minutes=6)
    assert asyncio.run(draft_item(factory, record["id"], provider))["status"] == "needs_review"
    assert provider.calls == 4
    engine.dispose()
