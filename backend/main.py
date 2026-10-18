from contextlib import asynccontextmanager
from datetime import timedelta, timezone
import ipaddress
import hashlib
import os
import re
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from .db import CollectionJob, Draft, FetchRun, Item, ModelSnapshot, WorkerPulse, initialize, make_engine, now
from .ingest import parse_date, persist
from .sources import SOURCES, TOPICS
from .worker import aware


class ManualXSignal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    url: str = Field(min_length=10, max_length=500)
    text: str = Field(min_length=10, max_length=2800)
    topic: str = Field(pattern="^(models|agents|gpu)$")
    created_at: str | None = Field(default=None, max_length=64)


class DraftRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    limit: int = Field(default=1, ge=1, le=1)


def iso(value):
    if not value:
        return None
    return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.isoformat()


def create_app(database_url=None):
    if database_url is None:
        load_dotenv()
    engine = make_engine(database_url)
    factory = initialize(engine)

    @asynccontextmanager
    async def lifespan(app):
        yield
        engine.dispose()

    app = FastAPI(title="Signaldesk", version="0.1.0", lifespan=lifespan)
    app.state.draft_run_active = False

    @app.middleware("http")
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.get("/health")
    def health():
        with factory() as session:
            session.execute(select(1))
        return {"status": "ok", "stage": "evidence-workflow-preview"}

    @app.get("/api/sources")
    def sources():
        result = []
        public_demo = os.getenv("SIGNALDESK_PUBLIC_DEMO", "false").lower() == "true"
        with factory() as session:
            for source in SOURCES:
                run = session.scalar(select(FetchRun).where(FetchRun.source_id == source.id).order_by(FetchRun.id.desc()).limit(1))
                newest = session.scalar(select(func.max(ModelSnapshot.fetched_at))) if source.kind == "hf_models" else session.scalar(select(func.max(Item.published_at)).where(Item.source_id == source.id))
                count = session.scalar(select(func.count()).select_from(ModelSnapshot).where(ModelSnapshot.fetched_at == newest)) if source.kind == "hf_models" and newest else session.scalar(select(func.count()).select_from(Item).where(Item.source_id == source.id))
                result.append({"id": source.id, "name": source.name, "topic": source.topic, "website": source.website, "kind": source.kind, "status": "not_checked" if not run else "ok" if run.success else "error", "checked_at": iso(run.checked_at) if run else None, "newest_observed": iso(newest), "count": count, "error": run.error if run else None})
            generated = session.scalar(select(func.count()).select_from(Draft).where(Draft.model != "none"))
            manual_count = 0 if public_demo else session.scalar(select(func.count()).select_from(Item).where(Item.source_id == "x-manual"))
        if not public_demo:
            result.append({"id": "x-manual", "name": "X posts (manual capture)", "topic": "models", "website": "https://x.com", "kind": "manual", "status": "manual", "checked_at": None, "newest_observed": None, "count": manual_count, "error": None})
        return {"sources": result, "connectors": {"x": "not_configured" if public_demo else "manual_intake_enabled" if os.getenv("SIGNALDESK_LOCAL_X_INTAKE", "false").lower() == "true" else "not_configured", "inference": "not_exposed" if public_demo else "workflow_used" if generated else "not_configured"}}

    @app.get("/api/capabilities")
    def capabilities():
        public_demo = os.getenv("SIGNALDESK_PUBLIC_DEMO", "false").lower() == "true"
        provider = os.getenv("INFERENCE_PROVIDER", "evidence").lower()
        inference_ready = provider == "ollama" or (provider == "experiential" and bool(os.getenv("EXPLABS_API_KEY")))
        local_actions = os.getenv("SIGNALDESK_LOCAL_DRAFT_ACTIONS", "false").lower() == "true"
        return {"local_x_intake": not public_demo and os.getenv("SIGNALDESK_LOCAL_X_INTAKE", "false").lower() == "true",
                "draft_generation": not public_demo and local_actions and inference_ready,
                "draft_queue": not public_demo,
                "public_demo": public_demo,
                "draft_provider": provider if inference_ready and not public_demo else None}

    @app.post("/api/drafts/run", status_code=202)
    async def run_local_draft(payload: DraftRunRequest, request: Request, background_tasks: BackgroundTasks):
        if os.getenv("SIGNALDESK_PUBLIC_DEMO", "false").lower() == "true" or os.getenv("SIGNALDESK_LOCAL_DRAFT_ACTIONS", "false").lower() != "true":
            raise HTTPException(404, "Local draft generation is disabled")
        peer = request.client.host if request.client else ""
        try:
            loopback = ipaddress.ip_address(peer).is_loopback
        except ValueError:
            loopback = False
        if not loopback and os.getenv("SIGNALDESK_LOCAL_PROXY_ACTIONS", "false").lower() != "true":
            raise HTTPException(403, "Draft generation is available on the local preview only")
        provider_name = os.getenv("INFERENCE_PROVIDER", "evidence").lower()
        if provider_name not in {"experiential", "ollama"}:
            raise HTTPException(503, "Configure a model provider before generating drafts")
        if provider_name == "experiential" and not os.getenv("EXPLABS_API_KEY"):
            raise HTTPException(503, "The configured hosted provider has no server-side key")
        if app.state.draft_run_active:
            raise HTTPException(409, "A draft batch is already running")
        app.state.draft_run_active = True

        async def run_batch():
            try:
                from .briefing import run as run_briefings
                await run_briefings(limit=payload.limit, provider_name=provider_name)
            finally:
                app.state.draft_run_active = False

        background_tasks.add_task(run_batch)
        return {"status": "started", "limit": payload.limit, "provider": provider_name,
                "message": "One draft batch started. Review its evidence and model output before using it."}

    @app.post("/api/local-signals/x", status_code=201)
    def add_manual_x_signal(signal: ManualXSignal, request: Request):
        if os.getenv("SIGNALDESK_PUBLIC_DEMO", "false").lower() == "true" or os.getenv("SIGNALDESK_LOCAL_X_INTAKE", "false").lower() != "true":
            raise HTTPException(404, "Manual X capture is disabled")
        peer = request.client.host if request.client else ""
        try:
            if not ipaddress.ip_address(peer).is_loopback:
                raise HTTPException(403, "Manual X capture is available on this local preview only")
        except ValueError:
            raise HTTPException(403, "Manual X capture is available on this local preview only")
        parsed = urlparse(signal.url)
        try:
            valid_host = parsed.port in (None, 443)
        except ValueError:
            valid_host = False
        if parsed.scheme != "https" or parsed.hostname not in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"} or parsed.username or parsed.password or not valid_host:
            raise HTTPException(422, "Use the HTTPS link to an X post")
        match = re.fullmatch(r"/(?:[A-Za-z0-9_]{1,15}/status/|i/web/status/)([0-9]{1,30})/?", parsed.path)
        if not match:
            raise HTTPException(422, "Link must point to one X post")
        post_id = match.group(1)
        text = re.sub(r"\s+", " ", signal.text).strip()
        title = text[:180] + ("…" if len(text) > 180 else "")
        item_id = hashlib.sha256(f"x-manual:{post_id}".encode()).hexdigest()
        content_hash = hashlib.sha256(f"{title}\n{text}".encode()).hexdigest()
        record = {"id": item_id, "source_id": "x-manual", "topic": signal.topic, "title": title, "url": signal.url,
                  "excerpt": text[:1200], "published_at": parse_date(signal.created_at), "content_hash": content_hash}
        with factory.begin() as session:
            persist(session, [record])
        return {"id": item_id, "message": "X post added to the local evidence queue. The pasted text is unverified until it is checked against primary sources."}

    @app.get("/api/items")
    def items(topic: str | None = None, q: str = Query(default="", max_length=120), limit: int = Query(default=60, ge=1, le=120)):
        if topic and topic not in TOPICS:
            raise HTTPException(422, "Unknown topic")
        statement = select(Item)
        if os.getenv("SIGNALDESK_PUBLIC_DEMO", "false").lower() == "true":
            statement = statement.where(Item.source_id != "x-manual")
        if topic:
            statement = statement.where(Item.topic == topic)
        if q:
            statement = statement.where(Item.title.icontains(q, autoescape=True))
        statement = statement.order_by(func.coalesce(Item.published_at, Item.fetched_at).desc(), Item.id).limit(limit)
        with factory() as session:
            records = session.scalars(statement).all()
            return {"items": [{"id": item.id, "source_id": item.source_id, "topic": item.topic, "title": item.title, "url": item.url, "excerpt": item.excerpt, "published_at": iso(item.published_at), "fetched_at": iso(item.fetched_at), "evidence_status": "source_excerpt", "editorial_status": "reviewed" if item.is_reviewed else "unreviewed"} for item in records]}

    @app.get("/api/models")
    def models(limit: int = Query(default=40, ge=1, le=80)):
        current = now()
        cutoff = current - timedelta(days=8)
        with factory() as session:
            snapshots = session.scalars(select(ModelSnapshot).where(ModelSnapshot.fetched_at >= cutoff).order_by(ModelSnapshot.fetched_at)).all()
            history: dict[str, list[ModelSnapshot]] = {}
            for snapshot in snapshots:
                history.setdefault(snapshot.repo_id, []).append(snapshot)
            records = []
            for repo_id, versions in history.items():
                latest = versions[-1]
                older_day = [v for v in versions if aware(v.fetched_at) <= current - timedelta(hours=23)]
                older_week = [v for v in versions if aware(v.fetched_at) <= current - timedelta(days=6)]
                records.append({"id": latest.repo_id, "author": latest.author, "name": latest.name,
                                "description": latest.description, "url": latest.url, "license": latest.license,
                                "downloads": latest.downloads, "likes": latest.likes, "pipeline_tag": latest.pipeline_tag,
                                "last_modified": iso(latest.last_modified), "trend_rank": latest.trend_rank,
                                "download_change_24h": latest.downloads - older_day[-1].downloads if older_day else None,
                                "download_change_7d": latest.downloads - older_week[-1].downloads if older_week else None})
        has_history = any(model["download_change_24h"] is not None for model in records)
        records.sort(key=lambda model: (model["download_change_24h"] if has_history and model["download_change_24h"] is not None else model["downloads"], model["downloads"]), reverse=True)
        return {"models": records[:limit], "updated_at": iso(current) if records else None,
                "method": "Hourly Hugging Face download snapshots; when 24-hour history exists, discovery sorts by download growth. Popularity is not a quality ranking."}

    @app.get("/api/pipeline")
    def pipeline():
        current = now()
        with factory() as session:
            heartbeat = session.get(WorkerPulse, "collector")
            jobs = []
            source_names = {source.id: source.name for source in SOURCES}
            for job in session.scalars(select(CollectionJob).order_by(CollectionJob.source_id)):
                last_new = session.scalar(select(func.max(FetchRun.checked_at)).where(FetchRun.source_id == job.source_id, FetchRun.new_count > 0))
                jobs.append({"source_id": job.source_id, "source_name": source_names.get(job.source_id, job.source_id), "next_due": iso(job.next_due),
                             "failures": job.failures, "last_success": iso(job.last_success),
                             "last_new_item": iso(last_new),
                             "state": "collecting" if job.lease_until and aware(job.lease_until) > current else "retry_wait" if job.failures else "scheduled",
                             "check_overdue": aware(job.next_due) < current - timedelta(minutes=5)})
            counts = {} if os.getenv("SIGNALDESK_PUBLIC_DEMO", "false").lower() == "true" else dict(session.execute(select(Draft.status, func.count()).group_by(Draft.status)).all())
        return {"worker": {"state": "recent_heartbeat" if heartbeat and current - aware(heartbeat.seen_at) < timedelta(seconds=120) else "not_observed",
                           "last_seen": iso(heartbeat.seen_at) if heartbeat else None}, "jobs": jobs,
                "draft_counts": counts, "publication_enabled": False}

    @app.get("/api/drafts")
    def drafts(limit: int = Query(default=30, ge=1, le=100)):
        if os.getenv("SIGNALDESK_PUBLIC_DEMO", "false").lower() == "true":
            return {"drafts": [], "publication_enabled": False}
        with factory() as session:
            rows = session.execute(select(Draft, Item.content_hash).join(Item, Draft.item_id == Item.id).order_by(Draft.updated_at.desc()).limit(limit)).all()
            return {"drafts": [{"id": draft.id, "item_id": draft.item_id, "status": draft.status,
                                "superseded": draft.evidence_hash != current_hash,
                                "evidence": draft.evidence, "output": draft.output,
                                "issues": draft.issues, "trace": draft.trace,
                                "model": draft.model, "pipeline_version": draft.pipeline_version,
                                "updated_at": iso(draft.updated_at)} for draft, current_hash in rows],
                    "publication_enabled": False}

    return app
