import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from backend.db import CollectionJob, FetchRun, initialize, make_engine, now
from backend.sources import SOURCES
from backend.worker import LEASE_SECONDS, aware, claim, finish, seed_jobs, tick


@pytest.fixture
def factory(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'worker.db'}")
    yield initialize(engine)
    engine.dispose()


def test_only_one_claim_and_expired_worker_cannot_finish(factory):
    at = now()
    seed_jobs(factory, at)
    first = claim(factory, "mcp", at)
    assert first
    assert claim(factory, "mcp", at) is None
    later = at + timedelta(seconds=LEASE_SECONDS + 1)
    second = claim(factory, "mcp", later)
    assert second and second != first
    assert not finish(factory, "mcp", first, {"success": True}, later)
    assert finish(factory, "mcp", second, {"success": True}, later)
    assert claim(factory, "mcp", later + timedelta(seconds=30)) is None


def test_schedule_survives_reinitialization_and_respects_retry_after(factory):
    at = now()
    seed_jobs(factory, at)
    token = claim(factory, "mcp", at)
    finish(factory, "mcp", token, {"success": False, "retry_after": 7200}, at)
    seed_jobs(factory, at + timedelta(seconds=60))
    with factory() as session:
        job = session.get(CollectionJob, "mcp")
        assert job.failures == 1
        assert aware(job.next_due) == at + timedelta(seconds=7200)
        assert job.last_success is None
    assert claim(factory, "mcp", at + timedelta(seconds=3600)) is None
    token = claim(factory, "mcp", at + timedelta(seconds=7201))
    finish(factory, "mcp", token, {"success": True}, at + timedelta(seconds=7201))
    with factory() as session:
        assert session.get(CollectionJob, "mcp").failures == 0


def test_worker_records_failure_without_stopping_other_sources(factory):
    async def fake_collect(factory, source):
        if source.id == "mcp":
            raise TimeoutError()
        return {"source": source.id, "success": True}
    results = asyncio.run(tick(factory, fake_collect))
    assert len(results) == len(SOURCES)
    assert sum(result["success"] for result in results) == len(SOURCES) - 1
    with factory() as session:
        assert session.get(CollectionJob, "mcp").failures == 1
        assert session.scalar(select(FetchRun.error)) == "TimeoutError"
    assert asyncio.run(tick(factory, fake_collect)) == []
