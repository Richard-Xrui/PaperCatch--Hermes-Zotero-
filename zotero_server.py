#!/usr/bin/env python3
"""PaperCatch HTTP server.

Serves the viewer frontend and provides:
  - GET  /api/papers            paper database
  - GET  /api/enrich/pending    papers still missing Chinese content
  - POST /api/enrich            write back Chinese content (used by Hermes agent)
  - POST /hermes/search         natural-language arXiv search (real search, merges into DB)
  - POST /zotero/add            add papers to Zotero (auto-creates collection paths)
  - GET  /zotero/collections    list Zotero collection paths
"""
import json
import os
import re
import sys
import threading
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, quote as url_quote

BASE_DIR = Path(__file__).resolve().parent
VIEWER_DIR = BASE_DIR / "viewer"
DB_JSON = BASE_DIR / "papers_database.json"
CATS_JSON = BASE_DIR / "papercatch_categories.json"
CONFIG_JSON = BASE_DIR / "search_config.json"
CRAWLED_IDS_FILE = BASE_DIR / "crawled_ids.txt"

DB_LOCK = threading.Lock()
ARXIV_NS = {"a": "http://www.w3.org/2005/Atom"}


# ── Config ──────────────────────────────────────────────
def load_app_config():
    cfg_path = BASE_DIR / "config.local.json"
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


APP_CONFIG = load_app_config()
ZOTERO_API_KEY = str(APP_CONFIG.get("zotero", {}).get("api_key", os.environ.get("ZOTERO_API_KEY", "")))
ZOTERO_USER_ID = str(APP_CONFIG.get("zotero", {}).get("user_id", os.environ.get("ZOTERO_USER_ID", "")))
ZOTERO_API_ROOT = f"https://api.zotero.org/users/{ZOTERO_USER_ID}" if ZOTERO_USER_ID else ""
DEFAULT_COLLECTION = APP_CONFIG.get("zotero", {}).get("default_collection", "PaperCatch/Hermes Search")


def read_json(path, default):
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── Natural-language query parsing (builtin, no LLM needed) ──
CN_KEYWORD_MAP = [
    ("大语言模型", "large language model"),
    ("语言模型", "language model"),
    ("大模型", "LLM"),
    ("多智能体", "multi-agent"),
    ("智能体", "agent"),
    ("多模态", "multimodal"),
    ("视觉语言", "vision-language"),
    ("世界模型", "world model"),
    ("对齐", "alignment"),
    ("安全", "safety"),
    ("越狱", "jailbreak"),
    ("机器人", "robot"),
    ("具身", "embodied"),
    ("扩散模型", "diffusion model"),
    ("扩散", "diffusion"),
    ("视频生成", "video generation"),
    ("图像生成", "image generation"),
    ("三维重建", "3D reconstruction"),
    ("三维", "3D"),
    ("重建", "reconstruction"),
    ("强化学习", "reinforcement learning"),
    ("检索增强", "retrieval-augmented generation"),
    ("思维链", "chain of thought"),
    ("推理", "reasoning"),
    ("基准", "benchmark"),
    ("评测", "benchmark"),
    ("遗忘", "unlearning"),
    ("水印", "watermark"),
    ("语音识别", "speech recognition"),
    ("语音", "speech"),
    ("医疗", "medical"),
    ("医学", "medical"),
    ("自动驾驶", "autonomous driving"),
    ("知识蒸馏", "knowledge distillation"),
    ("蒸馏", "distillation"),
    ("量化", "quantization"),
    ("剪枝", "pruning"),
]

EN_STOPWORDS = {
    "find", "search", "get", "me", "the", "a", "an", "and", "or", "of", "to", "in",
    "on", "for", "about", "recent", "latest", "last", "past", "days", "day", "week",
    "papers", "paper", "articles", "article", "arxiv", "add", "zotero", "please",
    "top", "new", "with", "them", "then", "don", "t", "do", "not", "no", "into",
}

# __APPEND__


def parse_query(message):
    """Parse a natural-language request into arXiv search parameters."""
    text = message.strip()
    low = text.lower()

    # number of papers
    max_results = 8
    m = re.search(r"(\d+)\s*(?:篇|个|results?|papers?)", low)
    if m:
        max_results = max(1, min(50, int(m.group(1))))

    # day range
    days = 0
    m = re.search(r"(?:最近|近|past|last)\s*(\d+)\s*(?:天|days?)", low)
    if m:
        days = max(0, min(60, int(m.group(1))))
    elif "今天" in text or "today" in low:
        days = 1
    elif "本周" in text or "this week" in low:
        days = 7

    # zotero intent
    auto_zotero = False
    if (any(kw in text for kw in ["入库", "放到", "放入", "存到"])
            or ("加入" in text and "zotero" in low)
            or ("add" in low and "zotero" in low)):
        auto_zotero = True
    if (any(kw in text for kw in ["不入库", "不加入", "别入库", "不要入库", "不用入库"])
            or ("don't" in low and "zotero" in low)
            or ("not" in low and "zotero" in low)
            or ("no zotero" in low)):
        auto_zotero = False

    # target collection: "放到 PaperCatch/Vision & 3D"
    collection = None
    m = re.search(r"(?:放到|放入|存到)\s*([A-Za-z][\w &/\-]*)", text)
    if m:
        collection = m.group(1).strip().rstrip("，,。 ")

    # keywords: translate Chinese phrases, then collect english words
    keywords = []
    remaining = text
    if collection:
        remaining = remaining.replace(m.group(0), " ")
    remaining = re.sub(r"(?i)zotero", " ", remaining)
    for cn, en in CN_KEYWORD_MAP:
        if cn in remaining:
            keywords.append(en)
            remaining = remaining.replace(cn, " ")

    # english/tech tokens (allow digit-leading like 3D/4D, hyphen and slash inside)
    for tok in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-/]*[A-Za-z][A-Za-z0-9\-/]*|[0-9]D(?:/[0-9]D)*", remaining):
        t = tok.strip("-/").lower()
        if len(t) >= 2 and t not in EN_STOPWORDS:
            keywords.append(tok)

    # dedupe preserving order
    seen = set()
    kw_clean = []
    for k in keywords:
        kl = k.lower()
        if kl not in seen:
            seen.add(kl)
            kw_clean.append(k)

    return {
        "keywords": kw_clean[:8],
        "days": days,
        "max_results": max_results,
        "auto_zotero": auto_zotero,
        "collection": collection or DEFAULT_COLLECTION,
    }


def arxiv_search(keywords, max_results=8, days=0):
    """Search arXiv by keywords, return normalized paper dicts."""
    if keywords:
        query = "+AND+".join(f"all:%22{url_quote(k)}%22" if " " in k else f"all:{url_quote(k)}" for k in keywords)
    else:
        query = "all:machine+learning"
    fetch = max_results * 3 if days > 0 else max_results
    url = (
        "https://export.arxiv.org/api/query?"
        f"search_query={query}"
        f"&sortBy=submittedDate&sortOrder=descending"
        f"&max_results={min(fetch, 80)}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "PaperCatch/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()

    root = ET.fromstring(data)
    cutoff = None
    if days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    papers = []
    for entry in root.findall("a:entry", ARXIV_NS):
        raw_id = entry.find("a:id", ARXIV_NS).text.strip()
        full_id = raw_id.split("/abs/")[-1] if "/abs/" in raw_id else raw_id
        arxiv_id = full_id.split("v")[0]
        published = entry.find("a:published", ARXIV_NS).text[:10]
        if cutoff and published < cutoff:
            continue
        title = entry.find("a:title", ARXIV_NS).text.strip().replace("\n", " ")
        title = re.sub(r"\s+", " ", title)
        authors = [a.find("a:name", ARXIV_NS).text for a in entry.findall("a:author", ARXIV_NS)]
        summary = entry.find("a:summary", ARXIV_NS).text.strip().replace("\n", " ")
        summary = re.sub(r"\s+", " ", summary)
        cats = [c.get("term") for c in entry.findall("a:category", ARXIV_NS)]
        comment_el = entry.find("a:comment", ARXIV_NS)
        comment = comment_el.text.strip() if comment_el is not None else ""
        papers.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "authors": authors,
            "published": published,
            "updated": entry.find("a:updated", ARXIV_NS).text[:10],
            "categories": cats,
            "primary_cat": cats[0] if cats else "",
            "abstract": summary[:800],
            "abstract_full": summary,
            "comment": comment,
            "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
            "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
            "citations": None,
            "influential_citations": None,
            "venue": None,
            "fields_of_study": [],
            "is_open_access": None,
            "quality_score": None,
            "tags": [],
            "abstract_cn": "",
            "title_cn": "",
            "summary_cn": "",
            "affiliations": "",
            "zotero_status": None,
            "crawled_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        })
        if len(papers) >= max_results:
            break
    return papers


def merge_into_db(new_papers):
    """Merge freshly-found papers into papers_database.json, preserving existing fields."""
    with DB_LOCK:
        db = read_json(DB_JSON, {"updated_at": "", "total_count": 0, "categories": [], "papers": []})
        existing = {p["arxiv_id"]: p for p in db.get("papers", [])}
        added = 0
        for p in new_papers:
            if p["arxiv_id"] in existing:
                # keep existing enriched fields
                for k, v in p.items():
                    existing[p["arxiv_id"]].setdefault(k, v)
            else:
                existing[p["arxiv_id"]] = p
                added += 1
        db["papers"] = list(existing.values())
        db["total_count"] = len(db["papers"])
        db["updated_at"] = datetime.now(timezone.utc).isoformat()
        db["categories"] = sorted({c for p in db["papers"] for c in p.get("categories", [])})
        write_json(DB_JSON, db)
    # record crawled ids
    try:
        with open(CRAWLED_IDS_FILE, "a", encoding="utf-8") as f:
            for p in new_papers:
                f.write(p["arxiv_id"] + "\n")
    except Exception:
        pass
    return added


# ── Zotero ──────────────────────────────────────────────
def zotero_request(method, path, payload=None, extra_headers=None):
    url = f"{ZOTERO_API_ROOT}{path}"
    headers = {"Zotero-API-Key": ZOTERO_API_KEY, "Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read()
    return json.loads(body) if body else {}


def list_zotero_collections():
    """Return {full_path: key} for all collections, resolving nesting."""
    items = []
    start = 0
    while True:
        batch = zotero_request("GET", f"/collections?limit=100&start={start}")
        if not batch:
            break
        items.extend(batch)
        if len(batch) < 100:
            break
        start += 100
    by_key = {}
    parent_of = {}
    name_of = {}
    for it in items:
        key = it["data"]["key"]
        name_of[key] = it["data"]["name"]
        parent_of[key] = it["data"].get("parentCollection") or None
        by_key[key] = it
    paths = {}
    for key in by_key:
        parts = [name_of[key]]
        parent = parent_of[key]
        guard = 0
        while parent and guard < 20:
            parts.append(name_of.get(parent, ""))
            parent = parent_of.get(parent)
            guard += 1
        paths["/".join(reversed(parts))] = key
    return paths, name_of, parent_of


def ensure_collection_path(path, cache):
    """Ensure a nested collection path exists; return its key. cache is {path:key}."""
    path = path.strip().strip("/")
    if not path:
        path = DEFAULT_COLLECTION
    if path in cache:
        return cache[path]
    parts = path.split("/")
    parent_key = None
    accumulated = ""
    for part in parts:
        accumulated = f"{accumulated}/{part}" if accumulated else part
        if accumulated in cache:
            parent_key = cache[accumulated]
            continue
        payload = [{"name": part, "parentCollection": parent_key or False}]
        result = zotero_request("POST", "/collections", payload)
        key = result.get("success", {}).get("0")
        if not key:
            # maybe it already exists but wasn't in cache; refetch
            fresh, _, _ = list_zotero_collections()
            cache.update(fresh)
            key = cache.get(accumulated)
            if not key:
                raise RuntimeError(f"无法创建 Zotero 文件夹: {accumulated}")
        cache[accumulated] = key
        parent_key = key
    return cache[path]


def build_zotero_item(paper, collection_key):
    authors = []
    for name in paper.get("authors", []):
        parts = name.rsplit(" ", 1)
        if len(parts) == 2:
            authors.append({"creatorType": "author", "firstName": parts[0], "lastName": parts[1]})
        else:
            authors.append({"creatorType": "author", "lastName": name})
    return {
        "itemType": "preprint",
        "title": paper.get("title", ""),
        "creators": authors,
        "abstractNote": paper.get("abstract_full") or paper.get("abstract", ""),
        "url": paper.get("abs_url", ""),
        "date": paper.get("published", ""),
        "repository": "arXiv",
        "archiveID": "arXiv:" + paper.get("arxiv_id", ""),
        "extra": "arXiv: " + paper.get("arxiv_id", ""),
        "collections": [collection_key] if collection_key else [],
        "tags": [{"tag": t} for t in paper.get("tags", []) if t],
    }


# ── HTTP Handler ────────────────────────────────────────
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(VIEWER_DIR), **kwargs)

    def log_message(self, *args):
        pass

    def json_response(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except Exception:
            return {}

    # ── GET ──
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/papers":
            self.json_response(read_json(DB_JSON, {"papers": [], "total_count": 0}))
        elif path == "/api/categories":
            self.json_response(read_json(CATS_JSON, []))
        elif path == "/api/config":
            self.json_response(read_json(CONFIG_JSON, {
                "categories": ["cs.AI", "cs.CL", "cs.CV", "cs.LG"], "max_per_cat": 25, "days": 0
            }))
        elif path == "/api/enrich/pending":
            self.handle_enrich_pending()
        elif path == "/api/status":
            self.json_response({
                "zotero_configured": bool(ZOTERO_API_KEY and ZOTERO_USER_ID),
                "default_collection": DEFAULT_COLLECTION,
            })
        elif path == "/zotero/status":
            self.handle_zotero_status(urlparse(self.path))
        elif path == "/zotero/collections":
            self.handle_zotero_collections()
        elif path == "/health":
            self.json_response({"status": "ok", "service": "PaperCatch"})
        else:
            self.serve_static(path)

    def serve_static(self, path):
        filepath = VIEWER_DIR / path.lstrip("/")
        if not filepath.exists() or filepath.is_dir():
            filepath = VIEWER_DIR / "index.html"
        try:
            content = filepath.read_bytes()
            ctype = "text/html; charset=utf-8"
            if filepath.suffix == ".json":
                ctype = "application/json; charset=utf-8"
            elif filepath.suffix == ".js":
                ctype = "application/javascript; charset=utf-8"
            elif filepath.suffix == ".css":
                ctype = "text/css; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception:
            self.send_error(404)

    # ── POST ──
    def do_POST(self):
        path = urlparse(self.path).path
        body = self.read_body()
        if path == "/hermes/search":
            self.handle_hermes_search(body)
        elif path == "/api/enrich":
            self.handle_enrich_save(body)
        elif path == "/zotero/add":
            self.handle_zotero_add(body)
        elif path == "/api/categories":
            self.handle_cats_save(body)
        elif path == "/api/config":
            self.handle_config_save(body)
        else:
            self.send_error(404)

    def do_DELETE(self):
        path = urlparse(self.path).path
        body = self.read_body()
        if path == "/api/papers":
            self.handle_papers_delete(body)
        else:
            self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ── Handlers ──
    def handle_hermes_search(self, body):
        message = (body.get("message") or "").strip()
        if not message:
            self.json_response({"success": False, "error": "请输入搜索内容"}, 400)
            return
        params = parse_query(message)
        try:
            papers = arxiv_search(params["keywords"], params["max_results"], params["days"])
        except Exception as e:
            self.json_response({"success": False, "error": f"arXiv 搜索失败：{e}"}, 502)
            return

        added = merge_into_db(papers) if papers else 0

        # optional auto-zotero
        zotero_note = ""
        if params["auto_zotero"] and papers:
            if not (ZOTERO_API_KEY and ZOTERO_USER_ID):
                zotero_note = "（Zotero 未配置，未入库）"
            else:
                try:
                    ids = [p["arxiv_id"] for p in papers]
                    res = self._zotero_add_ids(ids, params["collection"])
                    zotero_note = f"，已入库 {res['added']} 篇到 {params['collection']}"
                except Exception as e:
                    zotero_note = f"（入库失败：{e}）"

        kw_text = "、".join(params["keywords"]) if params["keywords"] else "最新"
        day_text = f"最近 {params['days']} 天" if params["days"] else "不限时间"
        msg = (f"找到 {len(papers)} 篇关于「{kw_text}」的论文（{day_text}），"
               f"新增 {added} 篇到列表{zotero_note}。")
        if papers:
            msg += "\n提示：新论文的中文标题/摘要/总结需由 Hermes agent 生成，可运行增强流程。"
        self.json_response({
            "success": True,
            "message": msg,
            "parsed": params,
            "papers": papers,
        })

    def handle_enrich_pending(self):
        db = read_json(DB_JSON, {"papers": []})
        pending = []
        for p in db.get("papers", []):
            needs = []
            if not p.get("title_cn"):
                needs.append("title_cn")
            if not p.get("abstract_cn"):
                needs.append("abstract_cn")
            if not p.get("summary_cn"):
                needs.append("summary_cn")
            if needs:
                pending.append({
                    "arxiv_id": p["arxiv_id"],
                    "title": p.get("title", ""),
                    "abstract": p.get("abstract_full") or p.get("abstract", ""),
                    "authors": p.get("authors", []),
                    "comment": p.get("comment", ""),
                    "needs": needs,
                })
        self.json_response({"count": len(pending), "pending": pending})

    def handle_enrich_save(self, body):
        """Write back Chinese content for one or more papers.
        Accepts {items:[{arxiv_id, title_cn, abstract_cn, summary_cn, background_cn, affiliations, tags, quality_score}]}"""
        items = body.get("items")
        if items is None and body.get("arxiv_id"):
            items = [body]
        if not items:
            self.json_response({"success": False, "error": "no items"}, 400)
            return
        fields = ["title_cn", "abstract_cn", "summary_cn", "background_cn",
                  "affiliations", "tags", "quality_score", "quality_signals"]
        with DB_LOCK:
            db = read_json(DB_JSON, {"papers": []})
            index = {p["arxiv_id"]: p for p in db.get("papers", [])}
            updated = 0
            for item in items:
                aid = item.get("arxiv_id")
                paper = index.get(aid)
                if not paper:
                    continue
                for f in fields:
                    if f in item and item[f] not in (None, ""):
                        paper[f] = item[f]
                updated += 1
            db["updated_at"] = datetime.now(timezone.utc).isoformat()
            write_json(DB_JSON, db)
        self.json_response({"success": True, "updated": updated})

    def handle_zotero_status(self, parsed):
        qs = parse_qs(parsed.query)
        arxiv_id = qs.get("arxiv_id", [None])[0]
        db = read_json(DB_JSON, {"papers": []})
        for p in db.get("papers", []):
            if p["arxiv_id"] == arxiv_id:
                self.json_response({"arxiv_id": arxiv_id, "zotero_status": p.get("zotero_status")})
                return
        self.json_response({"arxiv_id": arxiv_id, "zotero_status": None})

    def handle_zotero_collections(self):
        if not (ZOTERO_API_KEY and ZOTERO_USER_ID):
            self.json_response({"success": False, "error": "Zotero not configured", "collections": []})
            return
        try:
            paths, _, _ = list_zotero_collections()
            self.json_response({"success": True, "collections": sorted(paths.keys())})
        except Exception as e:
            self.json_response({"success": False, "error": str(e), "collections": []}, 502)

    def _zotero_add_ids(self, arxiv_ids, collection_path=None, collection_map=None):
        db = read_json(DB_JSON, {"papers": []})
        index = {p["arxiv_id"]: p for p in db.get("papers", [])}
        cache, _, _ = list_zotero_collections()
        results = []
        for aid in arxiv_ids:
            paper = index.get(aid)
            if not paper:
                results.append({"arxiv_id": aid, "status": "not_found"})
                continue
            path = (collection_map or {}).get(aid) or collection_path or DEFAULT_COLLECTION
            try:
                key = ensure_collection_path(path, cache)
                item = build_zotero_item(paper, key)
                res = zotero_request("POST", "/items", [item])
                zkey = res.get("success", {}).get("0", "")
                paper["zotero_status"] = "added"
                paper["zotero_collection"] = path
                results.append({"arxiv_id": aid, "status": "added", "zotero_key": zkey, "collection": path})
            except Exception as e:
                results.append({"arxiv_id": aid, "status": "failed", "error": str(e)})
        with DB_LOCK:
            fresh = read_json(DB_JSON, {"papers": []})
            fresh_index = {p["arxiv_id"]: p for p in fresh.get("papers", [])}
            for r in results:
                if r["status"] == "added" and r["arxiv_id"] in fresh_index:
                    fresh_index[r["arxiv_id"]]["zotero_status"] = "added"
                    fresh_index[r["arxiv_id"]]["zotero_collection"] = r["collection"]
            write_json(DB_JSON, fresh)
        added = sum(1 for r in results if r["status"] == "added")
        return {"added": added, "failed": len(results) - added, "results": results}

    def handle_zotero_add(self, body):
        if not (ZOTERO_API_KEY and ZOTERO_USER_ID):
            self.json_response({"success": False, "error": "Zotero is not configured"}, 500)
            return
        arxiv_ids = body.get("arxiv_ids", [])
        collection = body.get("collection") or DEFAULT_COLLECTION
        collection_map = body.get("collection_map")
        if not arxiv_ids:
            self.json_response({"success": False, "error": "no arxiv_ids"}, 400)
            return
        try:
            res = self._zotero_add_ids(arxiv_ids, collection, collection_map)
            self.json_response({"success": True, **res})
        except Exception as e:
            self.json_response({"success": False, "error": str(e)}, 502)

    def handle_cats_save(self, body):
        if isinstance(body, list):
            write_json(CATS_JSON, body)
            write_json(VIEWER_DIR / "papercatch_categories.json", body)
            self.json_response({"success": True})
        else:
            self.json_response({"success": False, "error": "expected array"}, 400)

    def handle_config_save(self, body):
        write_json(CONFIG_JSON, body)
        write_json(VIEWER_DIR / "search_config.json", body)
        self.json_response({"success": True})

    def handle_papers_delete(self, body):
        ids = set(body.get("arxiv_ids", []))
        with DB_LOCK:
            db = read_json(DB_JSON, {"papers": []})
            before = len(db.get("papers", []))
            db["papers"] = [p for p in db.get("papers", []) if p["arxiv_id"] not in ids]
            db["total_count"] = len(db["papers"])
            write_json(DB_JSON, db)
        self.json_response({"success": True, "removed": before - len(db["papers"])})


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    VIEWER_DIR.mkdir(exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"PaperCatch http://localhost:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()



