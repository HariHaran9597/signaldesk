from fastapi.testclient import TestClient
from datetime import datetime, timedelta, timezone

from backend.db import Draft, Item, initialize, make_engine
from backend.export_demo import build_snapshot, update_model_history
from backend.main import create_app


def test_public_snapshot_truncates_excerpts_and_excludes_review_queue(tmp_path):
    url = f"sqlite:///{tmp_path / 'snapshot.db'}"
    engine = make_engine(url)
    factory = initialize(engine)
    with factory.begin() as session:
        session.add(Item(id="item-1", source_id="huggingface", topic="models", title="Public title", url="https://huggingface.co/blog/example", excerpt="a" * 700, content_hash="hash"))
        session.add(Item(id="manual-x", source_id="x-manual", topic="models", title="Private pasted post", url="https://x.com/account/status/123", excerpt="user-provided text", content_hash="x-hash"))
        session.add(Draft(id="draft-1", item_id="item-1", evidence_hash="hash", evidence={"excerpt": "private evidence"}, status="needs_review", model="private-model", pipeline_version="test", output={"headline": "private draft"}, issues=[], trace=[]))

    with TestClient(create_app(url)) as client:
        snapshot = build_snapshot(client)

    assert snapshot["items"][0]["excerpt"] == "a" * 320 + "…"
    assert all(item["source_id"] != "x-manual" for item in snapshot["items"])
    assert "drafts" not in snapshot
    assert all(source["id"] != "x-manual" for source in snapshot["sources"])
    assert snapshot["capabilities"]["draft_queue"] is False
    assert "private draft" not in str(snapshot)
    engine.dispose()


def test_model_history_computes_changes_from_prior_observations():
    observed = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
    history = {"org/model": [{"observed_at": (observed - timedelta(days=1)).isoformat(), "downloads": 100}]}
    models, updated = update_model_history([{"id": "org/model", "downloads": 145}], history, observed)

    assert models[0]["download_change_24h"] == 45
    assert models[0]["download_change_7d"] is None
    assert updated["org/model"][-1] == {"observed_at": observed.isoformat(), "downloads": 145}
