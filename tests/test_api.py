from fastapi.testclient import TestClient

from backend.db import Draft, FetchRun, Item, initialize, make_engine
from backend.ingest import parse_feed, persist
from backend.main import create_app
from backend.sources import SOURCES


def test_empty_source_status_and_unconfigured_connectors(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'api.db'}")) as client:
        assert client.get("/health").json()["status"] == "ok"
        payload = client.get("/api/sources").json()
        automatic = [source for source in payload["sources"] if source["kind"] != "manual"]
        manual = [source for source in payload["sources"] if source["kind"] == "manual"]
        assert automatic and all(source["status"] == "not_checked" for source in automatic)
        assert len(manual) == 1 and manual[0]["status"] == "manual"
        assert payload["connectors"] == {"x": "not_configured", "inference": "not_configured"}
        assert client.get("/api/items").json() == {"items": []}
        assert client.get("/api/capabilities").json()["draft_generation"] is False
        assert client.post("/api/drafts/run", json={"limit": 1}).status_code == 404


def test_public_demo_hides_private_drafts_and_disables_mutations(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGNALDESK_PUBLIC_DEMO", "true")
    monkeypatch.setenv("SIGNALDESK_LOCAL_DRAFT_ACTIONS", "true")
    monkeypatch.setenv("SIGNALDESK_LOCAL_PROXY_ACTIONS", "true")
    monkeypatch.setenv("SIGNALDESK_LOCAL_X_INTAKE", "true")
    url = f"sqlite:///{tmp_path / 'public-demo.db'}"
    engine = make_engine(url)
    factory = initialize(engine)
    with factory.begin() as session:
        session.add(Item(id="private-item", source_id="test", topic="models", title="Private headline", url="https://example.com", excerpt="Private excerpt", content_hash="hash"))
        session.add(Item(id="manual-x", source_id="x-manual", topic="models", title="Private pasted post", url="https://x.com/account/status/123", excerpt="User-provided text", content_hash="x-hash"))
        session.add(Draft(id="private-draft", item_id="private-item", evidence_hash="hash", evidence={"excerpt": "private evidence"}, status="needs_review", model="private-model", pipeline_version="test", output={"headline": "Private draft"}, issues=[], trace=[]))
    with TestClient(create_app(url)) as client:
        assert client.get("/api/drafts").json() == {"drafts": [], "publication_enabled": False}
        assert client.get("/api/pipeline").json()["draft_counts"] == {}
        assert all(item["source_id"] != "x-manual" for item in client.get("/api/items").json()["items"])
        assert "x-manual" not in [source["id"] for source in client.get("/api/sources").json()["sources"]]
        capabilities = client.get("/api/capabilities").json()
        assert capabilities["public_demo"] is True
        assert capabilities["draft_queue"] is False
        assert capabilities["draft_generation"] is False
        assert capabilities["local_x_intake"] is False
        assert client.post("/api/drafts/run", json={"limit": 1}).status_code == 404
        assert client.post("/api/local-signals/x", json={"url": "https://x.com/a/status/123", "text": "A valid length post", "topic": "models"}).status_code == 404
    engine.dispose()


def test_filters_are_bounded_and_search_is_literal(tmp_path):
    url = f"sqlite:///{tmp_path / 'api.db'}"
    engine = make_engine(url)
    factory = initialize(engine)
    xml = b'<rss><channel><item><title>Model with 50% gains</title><link>https://huggingface.co/blog/a</link></item><item><title>Another model</title><link>https://huggingface.co/blog/b</link></item></channel></rss>'
    with factory.begin() as session:
        persist(session, parse_feed(xml, SOURCES[0]))
        session.add(FetchRun(source_id=SOURCES[0].id, success=False, error="ConnectTimeout"))
    with TestClient(create_app(url)) as client:
        assert client.get("/api/items?topic=unknown").status_code == 422
        assert client.get("/api/items?limit=121").status_code == 422
        assert client.get("/api/items", params={"q": "a" * 121}).status_code == 422
        assert len(client.get("/api/items", params={"q": "%"}).json()["items"]) == 1
        assert client.get("/api/items?topic=gpu").json()["items"] == []
        item = client.get("/api/items").json()["items"][0]
        assert item["evidence_status"] == "source_excerpt"
        assert item["editorial_status"] == "unreviewed"
        source = client.get("/api/sources").json()["sources"][0]
        assert source["status"] == "error"
        assert source["count"] == 2
        assert source["newest_observed"] is None
        assert client.get("/api/items").headers["X-Content-Type-Options"] == "nosniff"
    engine.dispose()
