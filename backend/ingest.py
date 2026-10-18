import argparse
import asyncio
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx
from defusedxml import ElementTree
from .db import EvidenceVersion, FetchRun, Item, ModelSnapshot, initialize, make_engine, now
from .sources import SOURCES

MAX_BYTES = 8_000_000


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "div", "br", "li"}:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


class ArticleExcerpt(HTMLParser):
    """Keep text only from semantic article/main content; never retain page markup."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.content_depth = 0
        self.hidden_depth = 0
        self.skip_tags = {"script", "style", "noscript", "svg", "nav", "header", "footer", "aside", "form"}

    def handle_starttag(self, tag, attrs):
        if tag in {"article", "main"}:
            self.content_depth += 1
        if tag in self.skip_tags:
            self.hidden_depth += 1
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3"} and self.content_depth:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in self.skip_tags:
            self.hidden_depth = max(0, self.hidden_depth - 1)
        if tag in {"article", "main"}:
            self.content_depth = max(0, self.content_depth - 1)
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3"} and self.content_depth:
            self.parts.append(" ")

    def handle_data(self, data):
        if self.content_depth and not self.hidden_depth:
            self.parts.append(data)


def plain(value, limit=800):
    parser = TextOnly()
    parser.feed(value or "")
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()[:limit]


def article_excerpt(body, limit=1200):
    if len(body) > MAX_BYTES:
        raise ValueError("Article exceeds size limit")
    parser = ArticleExcerpt()
    parser.feed(body.decode("utf-8", errors="replace"))
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()[:limit]


def allowed_link(url, source):
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname == urlparse(source.website).hostname and not parsed.username and not parsed.password and parsed.port in (None, 443)


def parse_date(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            result = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)


def local_name(tag):
    return tag.split("}")[-1]


def parse_feed(body, source, limit=40):
    if len(body) > MAX_BYTES:
        raise ValueError("Feed exceeds size limit")
    root = ElementTree.fromstring(body, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    if local_name(root.tag) not in {"rss", "feed", "RDF"}:
        raise ValueError("Response is not a feed")
    results = {}
    for entry in root.iter():
        if local_name(entry.tag) not in {"item", "entry"}:
            continue
        fields = {}
        link = ""
        for child in entry:
            key = local_name(child.tag)
            fields[key] = "".join(child.itertext())
            if key == "link" and child.attrib.get("rel", "alternate") == "alternate":
                link = child.attrib.get("href") or child.text or ""
        title = plain(fields.get("title"), 250)
        link = link.strip()
        try:
            valid = allowed_link(link, source)
        except ValueError:
            valid = False
        if not title or not valid:
            continue
        excerpt = plain(fields.get("description") or fields.get("summary") or fields.get("content") or fields.get("encoded"))
        item_id = hashlib.sha256(f"{source.id}:{link}".encode()).hexdigest()
        content_hash = hashlib.sha256(f"{title}\n{excerpt}".encode()).hexdigest()
        results[item_id] = dict(id=item_id, source_id=source.id, topic=source.topic, title=title, url=link, excerpt=excerpt, published_at=parse_date(fields.get("published") or fields.get("pubDate") or fields.get("updated")), content_hash=content_hash)
    return sorted(results.values(), key=lambda item: item["published_at"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)[:limit]


def parse_github_releases(body, source, limit=10):
    if len(body) > MAX_BYTES:
        raise ValueError("Response exceeds size limit")
    payload = json.loads(body)
    if not isinstance(payload, list):
        raise ValueError("Response is not a release list")
    records = []
    for release in payload[:limit]:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        title = plain(release.get("name") or release.get("tag_name"), 250)
        if release.get("prerelease"):
            title = f"[Pre-release] {title}"[:250]
        url = release.get("html_url", "")
        try:
            valid = allowed_link(url, source)
        except ValueError:
            valid = False
        if not title or not valid:
            continue
        excerpt = plain(release.get("body"), 800)
        item_id = hashlib.sha256(f"{source.id}:{url}".encode()).hexdigest()
        content_hash = hashlib.sha256(f"{title}\n{excerpt}".encode()).hexdigest()
        records.append(dict(id=item_id, source_id=source.id, topic=source.topic, title=title, url=url,
                            excerpt=excerpt, published_at=parse_date(release.get("published_at")), content_hash=content_hash))
    return records


def parse_hf_models(body, source, limit=40):
    if len(body) > MAX_BYTES:
        raise ValueError("Response exceeds size limit")
    payload = json.loads(body)
    if not isinstance(payload, list):
        raise ValueError("Response is not a model list")
    records = []
    fetched_at = now().replace(minute=0, second=0, microsecond=0)
    for rank, model in enumerate(payload[:limit], start=1):
        if not isinstance(model, dict):
            continue
        repo_id = model.get("modelId") or model.get("id")
        if not isinstance(repo_id, str) or len(repo_id) > 180 or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo_id):
            continue
        author, name = repo_id.split("/", 1)
        card = model.get("cardData") if isinstance(model.get("cardData"), dict) else {}
        try:
            downloads = max(0, min(2_147_483_647, int(model.get("downloads") or 0)))
            likes = max(0, min(2_147_483_647, int(model.get("likes") or 0)))
        except (ValueError, TypeError, OverflowError):
            downloads, likes = 0, 0
        records.append({
            "id": hashlib.sha256(f"{repo_id.lower()}:{fetched_at.isoformat()}".encode()).hexdigest(), "repo_id": repo_id,
            "author": author[:120], "name": name[:180], "description": plain(card.get("description"), 500),
            "url": f"https://huggingface.co/{repo_id}", "license": str(card.get("license"))[:80] if card.get("license") else None,
            "downloads": downloads, "likes": likes, "pipeline_tag": str(model.get("pipeline_tag"))[:80] if model.get("pipeline_tag") else None,
            "trend_rank": rank,
            "last_modified": parse_date(model.get("lastModified")), "fetched_at": fetched_at,
        })
    return records


def persist(session, records):
    added = 0
    for record in records:
        item = session.get(Item, record["id"])
        if item and item.content_hash == record["content_hash"]:
            continue
        version_id = hashlib.sha256(f'{record["id"]}:{record["content_hash"]}'.encode()).hexdigest()
        if not session.get(EvidenceVersion, version_id):
            session.add(EvidenceVersion(id=version_id, item_id=record["id"], title=record["title"], excerpt=record["excerpt"], content_hash=record["content_hash"]))
        if item:
            for key, value in record.items():
                setattr(item, key, value)
            item.fetched_at = now()
            item.is_reviewed = False
        else:
            session.add(Item(**record))
            added += 1
    return added


async def collect(factory, source):
    result = {"source": source.id, "success": False, "count": 0, "new_count": 0}
    try:
        headers = {"User-Agent": "Signaldesk/0.1 (public research reader)"}
        if source.kind == "github_releases":
            headers.update({"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
        async with httpx.AsyncClient(timeout=25, follow_redirects=False, headers=headers) as client:
            async with client.stream("GET", source.url) as response:
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise ValueError("Feed exceeds size limit")
        if source.kind == "github_releases":
            records = parse_github_releases(bytes(body), source)
        elif source.kind == "hf_models":
            records = parse_hf_models(bytes(body), source)
        else:
            records = parse_feed(bytes(body), source)
        if source.kind == "rss":
            candidates = [record for record in records if len(record["excerpt"]) < 120][:2]
            if candidates:
                async with httpx.AsyncClient(timeout=15, follow_redirects=False, headers={"User-Agent": "Signaldesk/0.1 (short evidence excerpt reader)", "Accept": "text/html"}) as client:
                    for record in candidates:
                        try:
                            async with client.stream("GET", record["url"]) as response:
                                response.raise_for_status()
                                if "text/html" not in response.headers.get("content-type", "").lower():
                                    continue
                                page = bytearray()
                                async for chunk in response.aiter_bytes():
                                    page.extend(chunk)
                                    if len(page) > MAX_BYTES:
                                        raise ValueError("Article exceeds size limit")
                            excerpt = article_excerpt(bytes(page))
                            if len(excerpt) >= 160:
                                record["excerpt"] = excerpt
                                record["content_hash"] = hashlib.sha256(f'{record["title"]}\n{excerpt}'.encode()).hexdigest()
                        except (httpx.HTTPError, ValueError):
                            continue
        with factory.begin() as session:
            if source.kind == "hf_models":
                added = 0
                for record in records:
                    if not session.get(ModelSnapshot, record["id"]):
                        added += 1
                    session.merge(ModelSnapshot(**record))
                session.query(ModelSnapshot).filter(ModelSnapshot.fetched_at < now() - timedelta(days=30)).delete(synchronize_session=False)
                result["new_count"] = added
            else:
                result["new_count"] = persist(session, records)
            result.update(success=True, count=len(records))
            session.add(FetchRun(source_id=source.id, success=True, count=len(records), new_count=result["new_count"]))
    except Exception as exc:
        error = type(exc).__name__
        if isinstance(exc, httpx.HTTPStatusError):
            result["status_code"] = exc.response.status_code
            if exc.response.status_code in (429, 503):
                retry = exc.response.headers.get("Retry-After", "")
                if retry.isdigit():
                    result["retry_after"] = min(int(retry), 604800)
                else:
                    retry_date = parse_date(retry)
                    if retry_date:
                        result["retry_after"] = max(0, min(604800, int((retry_date - now()).total_seconds())))
        with factory.begin() as session:
            session.add(FetchRun(source_id=source.id, success=False, error=error))
        result["error"] = error
    return result


async def run(source_id=None):
    engine = make_engine()
    factory = initialize(engine)
    sources = [source for source in SOURCES if not source_id or source.id == source_id]
    results = await asyncio.gather(*(collect(factory, source) for source in sources))
    print(json.dumps(results, indent=2))
    engine.dispose()
    return all(result["success"] for result in results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=[source.id for source in SOURCES])
    args = parser.parse_args()
    raise SystemExit(0 if asyncio.run(run(args.source)) else 1)
