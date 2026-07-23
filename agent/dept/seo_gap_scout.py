"""
SML SEO GAP SCOUT
==================
The SEO/AEO/GEO technical-issue module that gap_synthesist.py's docstring
explicitly deferred ("do not build without a fresh, explicit ask") — built
now that Timothy has given that explicit ask (2026-07-21).

Deliberately NOT built on Ahrefs or any paid crawler service — the connected
Ahrefs account returned "Insufficient plan" on both site-audit-projects and
management-projects (confirmed live, not assumed), and Timothy explicitly
does not want a paid subscription. This scout crawls sites directly over
plain HTTP instead: real GET requests, real HTML parsing, zero third-party
API cost. If a target site is unreachable, that's reported as unreachable —
never faked as "no issues found."

Detects real, structural, unambiguous technical issues:
  - Broken internal links (non-2xx / unreachable)
  - Missing <title> or duplicate titles across pages
  - Missing meta description
  - Missing structured data (no application/ld+json block)
  - Missing llms.txt / sitemap.xml / robots.txt at site root

SAME SAFETY PATTERN AS gap_synthesist.py — ZERO CUSTODY, ZERO AUTO-DEPLOY:
this agent never edits a live site, never opens a PR, never deploys a fix.
Its only side effect is one HTTP POST per qualifying finding, adding a
drafted spec to the existing human-review queue
(core/api/gap_proposals_bp.py). Approving a proposal there does not deploy
anything either — building the actual fix remains a separate, ordinary dev
task.

Env:
  ANTHROPIC_API_KEY            (required)
  SQUEEZEOS_BASE_URL           (default: https://squeezeos-api.onrender.com)
  GAP_PROPOSALS_QUEUE_SECRET   (required to push drafts into the review queue
                                 — same secret gap_synthesist.py uses)
  SEO_SCAN_SITES                comma-separated site URLs to crawl
                                 (default: https://www.scriptmasterlabs.com)
  SEO_MAX_LINKS_PER_SITE        internal links to sample per site (default 15)
"""

import os, sys, json, datetime, re
from urllib.parse import urljoin, urlparse
import requests
import anthropic

ANTH_KEY      = os.environ["ANTHROPIC_API_KEY"]
MODEL         = os.environ.get("DEPT_MODEL", "claude-sonnet-5")
SQUEEZEOS     = os.environ.get("SQUEEZEOS_BASE_URL", "https://squeezeos-api.onrender.com").rstrip("/")
QUEUE_SECRET  = os.environ.get("GAP_PROPOSALS_QUEUE_SECRET", "")
OUTPUT_DIR    = os.environ.get("SEO_OUTPUT_DIR", "agent/outputs")
SCAN_SITES    = [s.strip() for s in os.environ.get("SEO_SCAN_SITES", "https://www.scriptmasterlabs.com").split(",") if s.strip()]
MAX_LINKS     = int(os.environ.get("SEO_MAX_LINKS_PER_SITE", "15"))

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "SMLSEOGapScout/1.0 (agent.scriptmasterlabs.com)"


def _fetch(url: str, timeout: int = 15):
    try:
        return SESSION.get(url, timeout=timeout, allow_redirects=True)
    except Exception:
        return None


def _extract_internal_links(html: str, base_url: str, domain: str) -> set:
    links = set()
    for m in re.finditer(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE):
        href = m.group(1)
        if href.startswith("#") or href.lower().startswith(("mailto:", "javascript:", "tel:")):
            continue
        full = urljoin(base_url, href).split("#")[0]
        if urlparse(full).netloc == domain:
            links.add(full)
    return links


def crawl_site(base_url: str) -> dict:
    """Real HTTP crawl of one site's homepage plus a sample of its internal
    links. Direct requests only -- no scraping service, no paid API."""
    domain = urlparse(base_url).netloc
    findings = {"base_url": base_url, "reachable": False, "pages": [], "site_level": {}}

    home = _fetch(base_url)
    if home is None or home.status_code >= 400:
        findings["error"] = f"unreachable (status={getattr(home, 'status_code', None)})"
        return findings
    findings["reachable"] = True

    robots  = _fetch(urljoin(base_url, "/robots.txt"))
    sitemap = _fetch(urljoin(base_url, "/sitemap.xml"))
    llms    = _fetch(urljoin(base_url, "/llms.txt"))
    findings["site_level"] = {
        "has_robots_txt":  bool(robots and robots.status_code == 200),
        "has_sitemap_xml": bool(sitemap and sitemap.status_code == 200),
        "has_llms_txt":    bool(llms and llms.status_code == 200),
    }

    links = _extract_internal_links(home.text, base_url, domain)
    to_check = [base_url] + [u for u in links if u != base_url][:MAX_LINKS]

    seen_titles: dict = {}
    for url in to_check:
        resp = home if url == base_url else _fetch(url)
        page = {"url": url}
        if resp is None:
            page["status"] = "unreachable"
            findings["pages"].append(page)
            continue
        page["status_code"] = resp.status_code
        if resp.status_code >= 400:
            findings["pages"].append(page)
            continue
        html = resp.text
        title_m = re.search(r'<title[^>]*>([^<]*)</title>', html, re.IGNORECASE)
        title = title_m.group(1).strip() if title_m else None
        desc_m = re.search(
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']',
            html, re.IGNORECASE,
        )
        description = desc_m.group(1).strip() if desc_m else None
        page.update({
            "title": title,
            "has_title": bool(title),
            "has_meta_description": bool(description),
            "has_structured_data": "application/ld+json" in html,
        })
        if title:
            seen_titles.setdefault(title, []).append(url)
        findings["pages"].append(page)

    findings["duplicate_titles"] = {t: urls for t, urls in seen_titles.items() if len(urls) > 1}
    return findings


def score_findings(findings: dict) -> dict:
    """Deterministic severity score from REAL counts in `findings` -- no
    fabricated numbers, no LLM guessing at severity. build-worthiness for
    the review queue mirrors gap_synthesist.py's score_gap style."""
    if not findings.get("reachable"):
        return {"score": 0, "reason": findings.get("error", "unreachable")}

    pages = findings.get("pages", [])
    ok_pages = [p for p in pages if p.get("status_code", 200) < 400 and "status" not in p]
    broken   = [p["url"] for p in pages if p.get("status_code", 200) >= 400 or p.get("status") == "unreachable"]
    no_title = [p["url"] for p in ok_pages if not p.get("has_title")]
    no_desc  = [p["url"] for p in ok_pages if not p.get("has_meta_description")]
    no_sd    = [p["url"] for p in ok_pages if not p.get("has_structured_data")]
    dup_titles = findings.get("duplicate_titles", {})
    site = findings.get("site_level", {})

    weight = (
        len(broken) * 15 + len(no_title) * 10 + len(no_desc) * 6 + len(no_sd) * 4
        + len(dup_titles) * 8
        + (0 if site.get("has_llms_txt") else 12)
        + (0 if site.get("has_sitemap_xml") else 8)
        + (0 if site.get("has_robots_txt") else 5)
    )

    return {
        "score": min(100, weight),
        "broken_links": broken,
        "missing_title": no_title,
        "missing_meta_description": no_desc,
        "missing_structured_data": no_sd,
        "duplicate_titles": dup_titles,
        "site_level_gaps": [k for k, v in site.items() if not v],
        "pages_checked": len(pages),
    }


def _push_to_queue(record: dict) -> dict:
    if not QUEUE_SECRET:
        return {"error": "GAP_PROPOSALS_QUEUE_SECRET not set -- cannot push to review queue"}
    try:
        r = SESSION.post(
            f"{SQUEEZEOS}/api/gap-proposals/submit",
            json=record,
            headers={"X-Gap-Proposals-Secret": QUEUE_SECRET},
            timeout=20,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)[:200]}


TOOLS = [
    {
        "name": "crawl_and_score_site",
        "description": "Crawl one real site over plain HTTP (homepage + sampled internal links) and return a deterministic severity score plus the exact real issues found (broken links, missing titles/meta/structured data, duplicate titles, missing llms.txt/sitemap.xml/robots.txt). No paid API, no fabricated data -- unreachable sites are reported as unreachable.",
        "input_schema": {
            "type": "object",
            "properties": {"base_url": {"type": "string"}},
            "required": ["base_url"],
        },
    },
    {
        "name": "draft_seo_proposal",
        "description": "Assemble a concrete technical fix spec for one site's real detected SEO/AEO/GEO issues and push it into the same human-approval review queue gap_synthesist.py uses. Does NOT edit the live site, open a PR, or deploy anything -- only queues a draft for Timothy to review.",
        "input_schema": {
            "type": "object",
            "properties": {
                "site_url":        {"type": "string"},
                "build_score":     {"type": "number"},
                "source_evidence": {"type": "array", "items": {"type": "string"}, "description": "Real URLs/issues this was drafted from"},
                "spec_markdown":   {"type": "string", "description": "Full technical fix spec in markdown: exact issues found (cite real URLs), proposed fix per issue, effort estimate"},
            },
            "required": ["site_url", "build_score", "spec_markdown"],
        },
    },
]


def execute_tool(name: str, inputs: dict) -> str:
    if name == "crawl_and_score_site":
        findings = crawl_site(inputs.get("base_url", ""))
        result = score_findings(findings)
        result["base_url"] = inputs.get("base_url", "")
        return json.dumps(result)
    elif name == "draft_seo_proposal":
        record = {
            "gap_topic":       f"SEO/AEO/GEO technical issues — {inputs.get('site_url', '')}",
            "gap_intensity":   inputs.get("build_score", 0),
            "proposed_route":  "",
            "extends":         "N/A — direct site fix, not a new API",
            "effort_estimate": "small — config/markup changes, no new deps",
            "build_score":     inputs.get("build_score", 0),
            "source_evidence": inputs.get("source_evidence", []),
            "spec_markdown":   inputs.get("spec_markdown", ""),
        }
        return json.dumps(_push_to_queue(record))
    return json.dumps({"error": f"Unknown tool: {name}"})


def run() -> dict:
    client = anthropic.Anthropic(api_key=ANTH_KEY)
    today  = datetime.date.today().isoformat()

    system = f"""You are the SML SEO Gap Scout. Your job is to crawl real sites over plain HTTP (no paid API), find real technical SEO/AEO/GEO issues, and draft concrete fix specs for the sites worth fixing. You NEVER edit a live site, open a PR, or deploy anything -- your only action tool (draft_seo_proposal) pushes a spec into a review queue Timothy must approve manually, and approval still doesn't deploy anything.

Today: {today}
Sites to scan: {json.dumps(SCAN_SITES)}

PROCEDURE:
1. Call crawl_and_score_site once per site in the scan list.
2. If a site is unreachable, report that honestly -- do not invent findings for it.
3. For any site scoring >= 40, call draft_seo_proposal with a real, specific spec_markdown: list the exact real issues found (cite real URLs from the crawl result), propose a concrete fix per issue category (e.g. add llms.txt with X content, add missing meta description to these N pages, fix these M broken links), and give an honest effort estimate.
4. Do not call draft_seo_proposal for a site scoring below 40, and do not fabricate an issue that wasn't in the real crawl result.
5. Output structured JSON:

{{
  "date": "{today}",
  "sites_scanned": <int>,
  "queued": [
    {{"topic": "...", "score": <int>, "id": "<proposal_id from draft_seo_proposal result, if any>"}}
  ],
  "below_threshold": [{{"site": "...", "score": <int>}}],
  "unreachable": ["<site>", ...],
  "recommended_next_step": "<one concrete action for Timothy>"
}}"""

    messages = [{"role": "user", "content": f"Run the SEO/AEO/GEO scan + score + draft cycle for {today}."}]
    tool_calls = 0
    resp = None

    for _ in range(20):
        resp = client.messages.create(model=MODEL, max_tokens=8192, system=system, tools=TOOLS, messages=messages)
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "end_turn":
            break
        if resp.stop_reason == "tool_use":
            results = []
            for blk in resp.content:
                if blk.type == "tool_use":
                    tool_calls += 1
                    print(f"  [SEO:{blk.name}] {json.dumps(blk.input)[:80]}")
                    results.append({"type": "tool_result", "tool_use_id": blk.id, "content": execute_tool(blk.name, blk.input)})
            messages.append({"role": "user", "content": results})

    final_text = next((b.text for b in resp.content if hasattr(b, "text")), "") if resp else ""
    output = {"date": today, "tool_calls": tool_calls, "raw": final_text}
    m = re.search(r'\{[\s\S]*\}', final_text)
    if m:
        try:
            output.update(json.loads(m.group()))
        except json.JSONDecodeError:
            pass

    os.makedirs(f"{OUTPUT_DIR}/seo_gaps", exist_ok=True)
    path = f"{OUTPUT_DIR}/seo_gaps/{today}_seo_scan.json"
    with open(path, "w") as f:
        json.dump(output, f, indent=2)
    queued = output.get("queued", [])
    print(f"\n[SEO GAP SCOUT] Sites scanned: {output.get('sites_scanned', '?')}")
    print(f"[SEO GAP SCOUT] Queued for review: {len(queued)}")
    for q in queued[:3]:
        print(f"  -> {q.get('topic', '')[:60]} score={q.get('score')}")
    return output


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
