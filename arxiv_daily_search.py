#!/usr/bin/env python3
"""
arXiv 每日论文搜索 + Semantic Scholar 引用数据增强
支持多类别搜索、去重、引用数据，输出结构化 JSON 供 hermes agent 处理

用法:
    python arxiv_daily_search.py                    # 搜索最近1天的论文
    python arxiv_daily_search.py --days 0           # 不过滤日期，取最新N篇
    python arxiv_daily_search.py --categories cs.CV,cs.AI,cs.LG,cs.CL
    python arxiv_daily_search.py --max-per-cat 30 --no-ss  # 跳过引用查询
"""

import sys, os, json, time, argparse
import urllib.request, urllib.parse, urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
PAPERS_DIR = BASE_DIR / "papers"
CRAWLED_IDS_FILE = BASE_DIR / "crawled_ids.txt"
OUTPUT_JSON = BASE_DIR / "new_papers.json"

DEFAULT_CATS = ["cs.AI", "cs.CL", "cs.CV", "cs.LG"]
MAX_PER_CAT = 30
SS_DELAY = 1.05
ARXIV_DELAY = 3.5

NS = {'a': 'http://www.w3.org/2005/Atom'}


def load_crawled_ids():
    if not CRAWLED_IDS_FILE.exists():
        return set()
    with open(CRAWLED_IDS_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_crawled_ids(new_ids):
    with open(CRAWLED_IDS_FILE, "a", encoding="utf-8") as f:
        for aid in new_ids:
            f.write(aid + "\n")


def search_category(category, max_results):
    url = (
        "https://export.arxiv.org/api/query?"
        f"search_query=cat:{category}"
        f"&sortBy=submittedDate&sortOrder=descending"
        f"&max_results={max_results}"
    )
    req = urllib.request.Request(url, headers={'User-Agent': 'HermesAgent/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
    except Exception as e:
        print(f"  [WARN] arXiv {category}: {e}", file=sys.stderr)
        return 0, []

    root = ET.fromstring(data)
    entries = root.findall('a:entry', NS)
    total_el = root.find('{http://a9.com/-/spec/opensearch/1.1/}totalResults')
    total = int(total_el.text) if total_el is not None else len(entries)

    papers = []
    for entry in entries:
        title = entry.find('a:title', NS).text.strip().replace('\n', ' ')
        raw_id = entry.find('a:id', NS).text.strip()
        full_id = raw_id.split('/abs/')[-1] if '/abs/' in raw_id else raw_id
        arxiv_id = full_id.split('v')[0]
        published = entry.find('a:published', NS).text[:10]
        updated = entry.find('a:updated', NS).text[:10]
        authors = [a.find('a:name', NS).text for a in entry.findall('a:author', NS)]
        summary = entry.find('a:summary', NS).text.strip().replace('\n', ' ')
        cats = [c.get('term') for c in entry.findall('a:category', NS)]
        comment_el = entry.find('a:comment', NS)
        comment = comment_el.text.strip() if comment_el is not None else ""

        papers.append({
            "arxiv_id": arxiv_id,
            "version": full_id[len(arxiv_id):] if full_id.startswith(arxiv_id) else "",
            "title": title,
            "authors": authors,
            "published": published,
            "updated": updated,
            "categories": cats,
            "primary_cat": cats[0] if cats else "",
            "abstract": summary[:800],
            "abstract_full": summary,
            "comment": comment,
            "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
            "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
        })
    return total, papers


def query_ss(arxiv_id):
    """Semantic Scholar 引用数据"""
    url = (
        f"https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}"
        "?fields=title,citationCount,influentialCitationCount,"
        "publicationVenue,year,isOpenAccess,openAccessPdf,"
        "fieldsOfStudy,referenceCount,authors"
    )
    req = urllib.request.Request(url, headers={'User-Agent': 'HermesAgent/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e), "citationCount": None, "influentialCitationCount": None}


def main():
    parser = argparse.ArgumentParser(description="arXiv 每日论文搜索")
    parser.add_argument("--categories", default=",".join(DEFAULT_CATS))
    parser.add_argument("--max-per-cat", type=int, default=MAX_PER_CAT)
    parser.add_argument("--days", type=int, default=1, help="只保留最近N天，0=不过滤")
    parser.add_argument("--no-ss", action="store_true", help="跳过 Semantic Scholar")
    parser.add_argument("--output", default=str(OUTPUT_JSON))
    args = parser.parse_args()

    categories = [c.strip() for c in args.categories.split(",") if c.strip()]
    crawled_ids = load_crawled_ids()

    cutoff = None
    if args.days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%d")

    # ── 搜索 ──
    all_papers = {}
    total_all = 0

    for i, cat in enumerate(categories):
        print(f"[搜索] {cat} ...", file=sys.stderr)
        total, papers = search_category(cat, max_results=args.max_per_cat)
        total_all += total
        new_count = 0
        for p in papers:
            pid = p["arxiv_id"]
            if pid not in all_papers:
                all_papers[pid] = p
                if pid not in crawled_ids:
                    new_count += 1
            else:
                for c in p["categories"]:
                    if c not in all_papers[pid]["categories"]:
                        all_papers[pid]["categories"].append(c)
        print(f"        {total} total, {len(papers)} fetched, {new_count} new", file=sys.stderr)
        if i < len(categories) - 1:
            time.sleep(ARXIV_DELAY)

    # ── 日期过滤 ──
    if cutoff:
        all_papers = {k: v for k, v in all_papers.items() if v["published"] >= cutoff}

    # ── 标记新旧 ──
    new_ids = []
    for pid in all_papers:
        if pid not in crawled_ids:
            new_ids.append(pid)

    paper_list = sorted(all_papers.values(), key=lambda x: (x["published"], x["title"]), reverse=True)

    print(f"[汇总] {len(all_papers)} papers ({len(new_ids)} new)", file=sys.stderr)

    # ── Semantic Scholar ──
    if not args.no_ss and new_ids:
        print(f"[增强] Semantic Scholar for {len(new_ids)} new papers...", file=sys.stderr)
        for i, pid in enumerate(new_ids):
            p = all_papers[pid]
            ss = query_ss(pid)
            p["citations"] = ss.get("citationCount")
            p["influential_citations"] = ss.get("influentialCitationCount")
            p["reference_count"] = ss.get("referenceCount")
            p["year"] = ss.get("year")
            p["venue"] = ss.get("publicationVenue", {}).get("name") if ss.get("publicationVenue") else None
            p["is_open_access"] = ss.get("isOpenAccess")
            p["fields_of_study"] = ss.get("fieldsOfStudy", [])
            p["ss_error"] = ss.get("error")
            if (i + 1) % 10 == 0:
                print(f"        {i+1}/{len(new_ids)} ...", file=sys.stderr)
            time.sleep(SS_DELAY)

    # ── 保存 crawled_ids ──
    if new_ids:
        save_crawled_ids(new_ids)

    # ── 输出（分为 new 和 all） ──
    new_papers = [all_papers[pid] for pid in new_ids]
    result = {
        "searched_at": datetime.now(timezone.utc).isoformat(),
        "categories": categories,
        "total_found": total_all,
        "total_after_filter": len(all_papers),
        "new_count": len(new_ids),
        "cutoff_date": cutoff,
        "new_papers": new_papers,
        "all_papers": paper_list,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[输出] {args.output} ({len(new_ids)} new / {len(all_papers)} total)", file=sys.stderr)

    if new_ids:
        print(f"\nLLM_SUMMARIZATION_REQUIRED")
        print(f"new_count={len(new_ids)}")
        print(f"output={args.output}")
    else:
        print(f"\nNo new papers today.")


if __name__ == "__main__":
    import traceback
    try:
        main()
        # Write success status file (for cron agent to read, avoids terminal encoding issues)
        status = {"status": "ok"}
        if os.path.exists(OUTPUT_JSON):
            with open(OUTPUT_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            status["new_count"] = data.get("new_count", 0)
            status["total_count"] = data.get("total_after_filter", 0)
            status["output_file"] = str(OUTPUT_JSON)
        else:
            status["new_count"] = 0
        with open(BASE_DIR / "run_status.json", "w", encoding="utf-8") as f:
            json.dump(status, f)
    except Exception as e:
        with open(BASE_DIR / "run_status.json", "w", encoding="utf-8") as f:
            json.dump({"status": "error", "error": str(e), "traceback": traceback.format_exc()}, f)
        raise
