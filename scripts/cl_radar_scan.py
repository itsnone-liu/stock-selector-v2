#!/usr/bin/env python3
"""CL-1 Capital Logic Radar scan v0 — GitHub + arXiv keyword sweep.

Fail-closed: every failure is logged to SCAN_META.json, never silent.
Output: data/cl_radar/raw/*.json + data/cl_radar/catalog_v0.{json,md}
Run: python3 scripts/cl_radar_scan.py   (stdlib only)
"""
import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "cl_radar"
RAW = OUT / "raw"
RAW.mkdir(parents=True, exist_ok=True)

RUN_TS = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# domain, query  (domains = CAPITAL_LOGIC_MAP cells: C1成本 C2筹码 C3吸筹 C4推进 C5浮盈 C6兑现 ASH=A股限定)
GH_QUERIES = [
    ("C1", "anchored vwap"), ("C1", "volume profile trading"),
    ("C1", "cost basis stocks"), ("C1", "筹码分布"), ("C1", "筹码 股票"),
    ("C2", "turnover rate stock china"), ("C2", "shareholder structure stock"),
    ("C2", "holding period stock"),
    ("C3", "wyckoff"), ("C3", "accumulation distribution indicator"),
    ("C3", "stealth trading"), ("C3", "order splitting"), ("C3", "absorption order flow"),
    ("C4", "price impact"), ("C4", "kyle lambda"), ("C4", "order flow imbalance"),
    ("C4", "cumulative volume delta"), ("C4", "market microstructure china"),
    ("C5", "disposition effect"), ("C5", "trapped traders"), ("C5", "unrealized gains"),
    ("C6", "informed trading"), ("C6", "profit taking"), ("C6", "volume climax"),
    ("ASH", "A股 量化"), ("ASH", "主力资金"), ("ASH", "龙虎榜"), ("ASH", "joinquant"),
]

ARXIV_QUERIES = [
    ("C1", 'all:"volume weighted average price"'),
    ("C2", 'all:"volume profile" AND all:equity'),
    ("C3", 'all:"stealth trading"'),
    ("C3", 'all:"order splitting"'),
    ("C4", 'all:"price impact" AND all:"order flow"'),
    ("C4", 'all:Amihud AND all:illiquidity'),
    ("C5", 'all:"disposition effect"'),
    ("C5", 'all:"capital gains overhang"'),
    ("C6", 'all:"informed selling"'),
    ("C6", 'all:"profit taking" AND all:volume'),
]

UA = {"User-Agent": "capital-logic-radar/0.1 (research scan)"}
meta = {"run": RUN_TS, "github": [], "arxiv": [], "errors": []}


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def gh_scan():
    seen = {}
    for i, (dom, q) in enumerate(GH_QUERIES):
        slug = urllib.parse.quote(q.replace(" ", "_"))
        path = RAW / f"gh_{i:02d}_{dom}_{slug}.json"
        url = ("https://api.github.com/search/repositories?"
               + urllib.parse.urlencode({"q": q, "sort": "stars", "order": "desc", "per_page": 8}))
        try:
            data = json.loads(fetch(url))
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            n = 0
            for it in data.get("items", []):
                key = it["full_name"]
                n += 1
                if key not in seen or it["stargazers_count"] > seen[key]["stars"]:
                    seen[key] = {
                        "repo": key, "stars": it["stargazers_count"],
                        "lang": it.get("language"), "desc": (it.get("description") or "")[:220],
                        "url": it["html_url"], "pushed": (it.get("pushed_at") or "")[:10],
                        "domains": [dom], "first_query": q,
                    }
                else:
                    if dom not in seen[key]["domains"]:
                        seen[key]["domains"].append(dom)
            meta["github"].append({"q": q, "domain": dom, "hits": data.get("total_count"), "kept": n})
            print(f"[gh {i+1}/{len(GH_QUERIES)}] {dom} '{q}' total={data.get('total_count')} kept={n}", flush=True)
        except Exception as e:  # fail-closed: log, continue
            meta["errors"].append({"source": "github", "q": q, "error": repr(e)})
            print(f"[gh ERROR] '{q}': {e}", flush=True)
        time.sleep(7)  # unauth search limit 10/min
    return seen


def arxiv_scan():
    seen = {}
    for i, (dom, q) in enumerate(ARXIV_QUERIES):
        url = ("https://export.arxiv.org/api/query?"
               + urllib.parse.urlencode({"search_query": q, "max_results": 8, "sortBy": "relevance"}))
        try:
            xml = fetch(url)
            (RAW / f"arxiv_{i:02d}_{dom}.xml").write_text(xml, encoding="utf-8")
            ns = {"a": "http://www.w3.org/2005/Atom"}
            root = ET.fromstring(xml)
            n = 0
            for e in root.findall("a:entry", ns):
                aid = e.findtext("a:id", "", ns)
                if aid in seen:
                    if dom not in seen[aid]["domains"]:
                        seen[aid]["domains"].append(dom)
                    continue
                n += 1
                seen[aid] = {
                    "paper_id": aid, "title": " ".join(e.findtext("a:title", "", ns).split()),
                    "published": e.findtext("a:published", "", ns)[:10],
                    "summary": " ".join(e.findtext("a:summary", "", ns).split())[:300],
                    "domains": [dom], "query": q,
                }
            meta["arxiv"].append({"q": q, "domain": dom, "kept": n})
            print(f"[arxiv {i+1}/{len(ARXIV_QUERIES)}] {dom} '{q}' kept={n}", flush=True)
        except Exception as e:
            meta["errors"].append({"source": "arxiv", "q": q, "error": repr(e)})
            print(f"[arxiv ERROR] '{q}': {e}", flush=True)
        time.sleep(3)
    return seen


def compile_catalog(gh, ax):
    gh_sorted = sorted(gh.values(), key=lambda x: -x["stars"])
    (OUT / "catalog_v0.json").write_text(
        json.dumps({"run": RUN_TS, "github": gh_sorted, "arxiv": list(ax.values())},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# CL-1 Radar Catalog v0 — {RUN_TS}", "",
             f"GitHub: {len(gh_sorted)} unique repos from {len(GH_QUERIES)} queries; "
             f"arXiv: {len(ax)} papers from {len(ARXIV_QUERIES)} queries; errors: {len(meta['errors'])}", "",
             "## GitHub repos (deduped, by stars)", ""]
    for r in gh_sorted:
        lines.append(f"- [{'/'.join(r['domains'])}] **{r['repo']}** ★{r['stars']} ({r['lang']}, pushed {r['pushed']}) — {r['desc']}")
    lines += ["", "## arXiv papers (by relevance)", ""]
    for p in ax.values():
        lines.append(f"- [{'/'.join(p['domains'])}] **{p['title']}** ({p['published']}) {p['paper_id']}")
        lines.append(f"  - {p['summary']}")
    (OUT / "catalog_v0.md").write_text("\n".join(lines), encoding="utf-8")
    meta["summary"] = {"gh_repos": len(gh_sorted), "arxiv_papers": len(ax), "errors": len(meta["errors"])}
    (RAW / "SCAN_META.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nDONE: {len(gh_sorted)} repos, {len(ax)} papers, {len(meta['errors'])} errors -> {OUT}", flush=True)


if __name__ == "__main__":
    gh = gh_scan()
    ax = arxiv_scan()
    compile_catalog(gh, ax)
