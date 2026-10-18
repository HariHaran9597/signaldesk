"""Write a sanitized, read-only JSON snapshot for the public static demo."""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import ModelSnapshot, make_engine, now
from .main import create_app


def build_snapshot(client: TestClient) -> dict:
    def get(path: str) -> dict:
        response = client.get(path)
        response.raise_for_status()
        return response.json()

    feed = get("/api/items?limit=120")
    source_data = get("/api/sources")
    model_data = get("/api/models?limit=40")
    pipeline = get("/api/pipeline")
    items = []
    for source_item in feed["items"]:
        item = dict(source_item)
        excerpt = item.get("excerpt") or ""
        item["excerpt"] = excerpt[:320].rstrip() + ("…" if len(excerpt) > 320 else "")
        items.append(item)
    items = [item for item in items if item["source_id"] != "x-manual"]
    models = []
    for source_model in model_data["models"]:
        model = dict(source_model)
        description = model.get("description") or ""
        model["description"] = description[:500].rstrip() + ("…" if len(description) > 500 else "")
        models.append(model)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
        "sources": [source for source in source_data["sources"] if source["id"] != "x-manual"],
        "models": models,
        "pipeline": {**pipeline, "draft_counts": {}},
        "capabilities": {
            "local_x_intake": False,
            "draft_generation": False,
            "draft_queue": False,
            "draft_provider": None,
            "public_demo": True,
        },
    }


def history_from_database() -> dict[str, list[dict]]:
    engine = make_engine()
    history: dict[str, list[dict]] = {}
    try:
        with Session(engine) as session:
            rows = session.scalars(select(ModelSnapshot).where(ModelSnapshot.fetched_at >= now() - timedelta(days=8)).order_by(ModelSnapshot.fetched_at)).all()
            for row in rows:
                history.setdefault(row.repo_id, []).append({"observed_at": row.fetched_at.replace(tzinfo=timezone.utc).isoformat(), "downloads": row.downloads})
    finally:
        engine.dispose()
    return history


def update_model_history(models: list[dict], history: dict, observed_at: datetime) -> tuple[list[dict], dict]:
    cutoff = observed_at - timedelta(days=8)
    cleaned: dict[str, list[dict]] = {}
    for repo_id, points in history.items():
        if not isinstance(repo_id, str) or not isinstance(points, list):
            continue
        valid = []
        for point in points:
            try:
                timestamp = datetime.fromisoformat(point["observed_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
                downloads = int(point["downloads"])
            except (AttributeError, KeyError, TypeError, ValueError):
                continue
            if downloads >= 0 and timestamp >= cutoff:
                valid.append({"observed_at": timestamp.isoformat(), "downloads": downloads})
        cleaned[repo_id] = sorted(valid, key=lambda point: point["observed_at"])

    enriched = []
    for original in models:
        model = dict(original)
        points = cleaned.setdefault(model["id"], [])
        current_downloads = int(model.get("downloads") or 0)
        last_at = datetime.fromisoformat(points[-1]["observed_at"]) if points else None
        if last_at is None or current_downloads != points[-1]["downloads"] or observed_at - last_at >= timedelta(hours=24):
            points.append({"observed_at": observed_at.isoformat(), "downloads": current_downloads})
        points[:] = [point for point in points if datetime.fromisoformat(point["observed_at"]) >= cutoff]

        baselines = []
        for age, field in ((timedelta(hours=23), "download_change_24h"), (timedelta(days=6), "download_change_7d")):
            eligible = [point for point in points[:-1] if datetime.fromisoformat(point["observed_at"]) <= observed_at - age]
            baseline = max(eligible, key=lambda point: point["observed_at"]) if eligible else None
            model[field] = current_downloads - baseline["downloads"] if baseline else None
        enriched.append(model)
    return enriched, cleaned


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("frontend/public/demo-data.json"))
    parser.add_argument("--history", type=Path, default=Path("frontend/public/model-history.json"))
    args = parser.parse_args()
    with TestClient(create_app()) as client:
        snapshot = build_snapshot(client)
    if not snapshot["items"]:
        raise SystemExit("Refusing to export an empty public demo snapshot")
    successful_sources = sum(source["status"] == "ok" for source in snapshot["sources"])
    if successful_sources < 5:
        raise SystemExit(f"Only {successful_sources} sources succeeded; preserving the previous public snapshot")
    if args.history.exists():
        try:
            stored = json.loads(args.history.read_text(encoding="utf-8"))
            history = stored.get("models", stored) if isinstance(stored, dict) else {}
        except (OSError, json.JSONDecodeError):
            history = {}
    else:
        history = history_from_database()
    observed_at = datetime.fromisoformat(snapshot["generated_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
    snapshot["models"], updated_history = update_model_history(snapshot["models"], history, observed_at)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    args.history.parent.mkdir(parents=True, exist_ok=True)
    args.history.write_text(json.dumps({"schema_version": 1, "models": updated_history}, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Wrote {len(snapshot['items'])} public items and {len(snapshot['models'])} model cards to {args.output}")


if __name__ == "__main__":
    main()
