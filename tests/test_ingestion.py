import pytest
from defusedxml.common import DTDForbidden
from sqlalchemy import func, select

from backend.db import EvidenceVersion, Item, initialize, make_engine
from backend.ingest import MAX_BYTES, parse_feed, persist, plain
from backend.sources import SOURCES

SOURCE = SOURCES[0]


def feed(title="A model launch", link="https://huggingface.co/blog/model", date=""):
    return f'<rss><channel><item><title>{title}</title><link>{link}</link><description><![CDATA[<p>Read <b>this</b>.</p><script>bad()</script>]]></description><pubDate>{date}</pubDate></item></channel></rss>'.encode()


def test_rss_preserves_unknown_date_and_strips_markup():
    record = parse_feed(feed(), SOURCE)[0]
    assert record["title"] == "A model launch"
    assert record["published_at"] is None
    assert "bad()" not in record["excerpt"]
    assert "<" not in record["excerpt"]


def test_atom_uses_alternate_link_and_publication_date():
    body = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Launch</title><link rel="self" href="https://evil.example/a"/><link rel="alternate" href="https://huggingface.co/blog/a"/><published>2026-10-01T08:00:00Z</published><updated>2026-10-02T08:00:00Z</updated><summary>Details</summary></entry></feed>'
    record = parse_feed(body, SOURCE)[0]
    assert record["published_at"].day == 1
    assert record["url"] == "https://huggingface.co/blog/a"


@pytest.mark.parametrize("url", ["http://huggingface.co/blog/a", "https://evil.example/a", "https://huggingface.co.evil.example/a", "https://user:pass@huggingface.co/a", "https://127.0.0.1/a", "file:///etc/passwd", "javascript:alert(1)", "https://huggingface.co:invalid/a", "https://huggingface.co:8080/a"])
def test_disallowed_links_are_not_published(url):
    assert parse_feed(feed(link=url), SOURCE) == []


def test_dtd_and_entities_are_rejected():
    with pytest.raises(DTDForbidden):
        parse_feed(b'<!DOCTYPE rss [<!ENTITY secret SYSTEM "file:///etc/passwd">]><rss>&secret;</rss>', SOURCE)


def test_nonfeed_response_is_rejected():
    with pytest.raises(ValueError, match="not a feed"):
        parse_feed(b"<html><body>Log in</body></html>", SOURCE)


def test_oversized_response_is_rejected():
    with pytest.raises(ValueError, match="size limit"):
        parse_feed(b" " * (MAX_BYTES + 1), SOURCE)


def test_excerpts_have_bounded_length():
    assert len(plain("a" * 2000)) == 800


def test_repeated_import_is_idempotent_and_change_keeps_evidence(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    factory = initialize(engine)
    record = parse_feed(feed(), SOURCE)[0]
    with factory.begin() as session:
        assert persist(session, [record]) == 1
    with factory.begin() as session:
        assert persist(session, [record]) == 0
        session.get(Item, record["id"]).is_reviewed = True
    with factory.begin() as session:
        assert persist(session, parse_feed(feed(title="Corrected launch"), SOURCE)) == 0
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Item)) == 1
        assert session.scalar(select(func.count()).select_from(EvidenceVersion)) == 2
        assert session.get(Item, record["id"]).is_reviewed is False
    engine.dispose()
