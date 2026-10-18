"""Durable hourly collection. Run one cycle with --once, or keep the process running."""
import argparse
import asyncio
import json
from datetime import timedelta, timezone
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from .db import CollectionJob, FetchRun, WorkerPulse, initialize, make_engine, now
from .ingest import collect
from .sources import SOURCES

INTERVAL_SECONDS = 3600
LEASE_SECONDS = 180


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def seed_jobs(factory, at=None):
    for source in SOURCES:
        try:
            with factory.begin() as session:
                if not session.get(CollectionJob, source.id):
                    session.add(CollectionJob(source_id=source.id, next_due=at or now()))
        except IntegrityError:
            pass


def claim(factory, source_id, at=None):
    at = at or now()
    token = str(uuid4())
    with factory.begin() as session:
        result = session.execute(update(CollectionJob).where(
            CollectionJob.source_id == source_id,
            CollectionJob.next_due <= at,
            or_(CollectionJob.lease_until.is_(None), CollectionJob.lease_until <= at),
        ).values(lease_until=at + timedelta(seconds=LEASE_SECONDS), lease_token=token))
        return token if result.rowcount == 1 else None


def finish(factory, source_id, token, result, at=None):
    at = at or now()
    with factory.begin() as session:
        job = session.get(CollectionJob, source_id)
        if not job or job.lease_token != token:
            return False
        failures = 0 if result["success"] else job.failures + 1
        delay = INTERVAL_SECONDS if result["success"] else min(3600, 60 * 2 ** min(failures - 1, 6))
        delay = max(delay, result.get("retry_after", 0))
        result = session.execute(update(CollectionJob).where(
            CollectionJob.source_id == source_id, CollectionJob.lease_token == token,
        ).values(next_due=at + timedelta(seconds=delay), failures=failures,
                 last_success=at if failures == 0 else job.last_success,
                 lease_until=None, lease_token=None))
        return result.rowcount == 1


def pulse(factory):
    with factory.begin() as session:
        session.merge(WorkerPulse(id="collector", seen_at=now()))


async def tick(factory, collector=collect):
    seed_jobs(factory)
    pulse(factory)

    async def run_source(source):
        token = claim(factory, source.id)
        if not token:
            return None
        try:
            async with asyncio.timeout(90):
                result = await collector(factory, source)
        except Exception as exc:
            result = {"source": source.id, "success": False, "error": type(exc).__name__}
            with factory.begin() as session:
                session.add(FetchRun(source_id=source.id, success=False, error=type(exc).__name__))
        finish(factory, source.id, token, result)
        return result

    results = await asyncio.gather(*(run_source(source) for source in SOURCES))
    pulse(factory)
    return [result for result in results if result]


async def run(once=False):
    engine = make_engine()
    factory = initialize(engine)
    try:
        while True:
            results = await tick(factory)
            if results or once:
                print(json.dumps({"event": "collection_cycle", "results": results}), flush=True)
            if once:
                return all(result["success"] for result in results)
            await asyncio.sleep(30)
    finally:
        engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    try:
        raise SystemExit(0 if asyncio.run(run(args.once)) else 1)
    except KeyboardInterrupt:
        pass
