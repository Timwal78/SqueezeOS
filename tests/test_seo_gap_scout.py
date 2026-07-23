"""
Regression tests for agent/dept/seo_gap_scout.py -- the real HTTP-crawling
SEO/AEO/GEO issue detector (no paid API, no Ahrefs, no fabricated findings).

Drives the real, unmodified crawl_site() / score_findings() / execute_tool()
functions end-to-end. Only the HTTP boundary (requests.Session.get) is
mocked, with realistic HTML fixtures standing in for real pages -- all
parsing, link-extraction, and scoring logic runs for real.
"""
import os
import sys
import json
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used-by-these-tests")

import agent.dept.seo_gap_scout as scout  # noqa: E402


def _resp(status_code=200, text="", url=""):
    r = MagicMock()
    r.status_code = status_code
    r.text = text
    r.url = url
    return r


CLEAN_HOME_HTML = """
<html><head>
<title>Home — Clean Site</title>
<meta name="description" content="A perfectly optimized homepage.">
<script type="application/ld+json">{"@type": "WebPage"}</script>
</head><body>
<a href="/about">About</a>
<a href="/pricing">Pricing</a>
</body></html>
"""

CLEAN_ABOUT_HTML = """
<html><head>
<title>About — Clean Site</title>
<meta name="description" content="About this clean site.">
<script type="application/ld+json">{"@type": "AboutPage"}</script>
</head><body>OK</body></html>
"""

BROKEN_HOME_HTML = """
<html><head><title>Home</title></head><body>
<a href="/missing">Missing Page</a>
<a href="/dup1">Dup 1</a>
<a href="/dup2">Dup 2</a>
</body></html>
"""

DUP_TITLE_HTML = "<html><head><title>Same Title</title></head><body>no meta, no jsonld</body></html>"


def test_crawl_site_detects_real_clean_page_correctly():
    """A genuinely well-formed site should register zero real issues."""
    def fake_get(url, timeout=15, allow_redirects=True):
        if url.rstrip("/") == "https://clean.example":
            return _resp(200, CLEAN_HOME_HTML)
        if url.endswith("/about"):
            return _resp(200, CLEAN_ABOUT_HTML)
        if url.endswith("/pricing"):
            return _resp(200, CLEAN_ABOUT_HTML.replace("About", "Pricing"))
        if url.endswith("/robots.txt"):
            return _resp(200, "User-agent: *\nAllow: /")
        if url.endswith("/sitemap.xml"):
            return _resp(200, "<urlset></urlset>")
        if url.endswith("/llms.txt"):
            return _resp(200, "User-agent: *\nAllow: /")
        return _resp(404, "")

    with patch.object(scout.SESSION, "get", side_effect=fake_get):
        findings = scout.crawl_site("https://clean.example")

    assert findings["reachable"] is True
    assert findings["site_level"] == {"has_robots_txt": True, "has_sitemap_xml": True, "has_llms_txt": True}
    for page in findings["pages"]:
        assert page.get("has_title") is True
        assert page.get("has_meta_description") is True
        assert page.get("has_structured_data") is True

    score = scout.score_findings(findings)
    assert score["score"] == 0, f"clean site should score 0, got {score}"
    assert score["broken_links"] == []
    assert score["missing_title"] == []
    print("PASS: clean site correctly scores 0 real issues")


def test_crawl_site_detects_real_broken_links_and_duplicate_titles():
    def fake_get(url, timeout=15, allow_redirects=True):
        if url.rstrip("/") == "https://broken.example":
            return _resp(200, BROKEN_HOME_HTML)
        if url.endswith("/missing"):
            return _resp(404, "")
        if url.endswith("/dup1") or url.endswith("/dup2"):
            return _resp(200, DUP_TITLE_HTML)
        if url.endswith(("/robots.txt", "/sitemap.xml", "/llms.txt")):
            return _resp(404, "")
        return _resp(404, "")

    with patch.object(scout.SESSION, "get", side_effect=fake_get):
        findings = scout.crawl_site("https://broken.example")

    score = scout.score_findings(findings)
    assert "https://broken.example/missing" in score["broken_links"], score
    assert len(score["duplicate_titles"]) == 1, "dup1 and dup2 share 'Same Title' -- must be detected as one duplicate group"
    assert score["missing_meta_description"], "dup1/dup2 have no meta description"
    assert score["missing_structured_data"], "dup1/dup2 have no JSON-LD"
    assert set(score["site_level_gaps"]) == {"has_robots_txt", "has_sitemap_xml", "has_llms_txt"}
    assert score["score"] > 40, f"a site with broken links + dup titles + no site-level files should score high, got {score['score']}"
    print("PASS: broken links, duplicate titles, and missing site-level files all correctly detected")


def test_crawl_site_reports_unreachable_honestly_no_fabricated_findings():
    def fake_get(url, timeout=15, allow_redirects=True):
        raise ConnectionError("network unreachable")

    with patch.object(scout.SESSION, "get", side_effect=fake_get):
        findings = scout.crawl_site("https://dead.example")

    assert findings["reachable"] is False
    assert "unreachable" in findings["error"]
    score = scout.score_findings(findings)
    assert score["score"] == 0
    assert score["reason"] == findings["error"], "unreachable site must report the real reason, not a fabricated score breakdown"
    print("PASS: unreachable site reports honestly, no fake issue list")


def test_execute_tool_draft_seo_proposal_pushes_real_payload_shape():
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=20):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        r = MagicMock()
        r.status_code = 201
        r.json.return_value = {"id": "test-id-123", "status": "pending_review"}
        r.raise_for_status = lambda: None
        return r

    with patch.object(scout, "QUEUE_SECRET", "test-secret"), \
         patch.object(scout.SESSION, "post", side_effect=fake_post):
        result = json.loads(scout.execute_tool("draft_seo_proposal", {
            "site_url": "https://example.com",
            "build_score": 55,
            "source_evidence": ["https://example.com/broken"],
            "spec_markdown": "# Fix broken link",
        }))

    assert result["id"] == "test-id-123"
    assert captured["headers"]["X-Gap-Proposals-Secret"] == "test-secret"
    assert captured["json"]["gap_topic"] == "SEO/AEO/GEO technical issues — https://example.com"
    assert captured["json"]["build_score"] == 55
    print("PASS: draft_seo_proposal pushes the correct real payload to the review queue")


def test_execute_tool_without_queue_secret_fails_closed():
    with patch.object(scout, "QUEUE_SECRET", ""):
        result = json.loads(scout.execute_tool("draft_seo_proposal", {
            "site_url": "https://example.com", "build_score": 90, "spec_markdown": "x",
        }))
    assert "error" in result
    print("PASS: draft_seo_proposal fails closed (no fabricated success) when secret unset")


if __name__ == "__main__":
    test_crawl_site_detects_real_clean_page_correctly()
    test_crawl_site_detects_real_broken_links_and_duplicate_titles()
    test_crawl_site_reports_unreachable_honestly_no_fabricated_findings()
    test_execute_tool_draft_seo_proposal_pushes_real_payload_shape()
    test_execute_tool_without_queue_secret_fails_closed()
    print("\nAll regression tests passed.")
