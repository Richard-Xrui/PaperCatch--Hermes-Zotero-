#!/usr/bin/env python3
"""PaperCatch HTTP server.

Serves the viewer frontend and provides:
  - GET  /api/papers            paper database
  - POST /api/papers/download   download authorized OA PDFs for selected papers
  - DELETE /api/papers          delete selected papers
  - GET/POST /api/categories    paper category configuration
  - GET/POST /api/config        search configuration
  - GET/POST /api/integrations  redacted/read-write local Zotero settings
  - GET  /api/enrich/pending    papers still missing Chinese content
  - POST /api/enrich            write back Chinese content (used by Hermes agent)
  - GET  /api/status            effective local integration status
  - POST /hermes/search         natural-language arXiv search (real search, merges into DB)
  - POST /zotero/add            add papers to Zotero (auto-creates collection paths)
  - GET  /zotero/collections    list Zotero collection paths
  - GET  /zotero/status         paper Zotero status
  - GET  /health                local service health
"""
import json
import logging
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, quote as url_quote, unquote

from config import load_config
from enrich import local_enrich, mark_pending
from json_store import JsonStoreError, locked_update_json, read_json, write_json_atomic
from paper_agent import answer_question, generate_learning_notes
from paper_download import download_open_access_pdf
from paper_sources import DEFAULT_SOURCES, search_all_sources

MODULE_DIR = Path(__file__).resolve().parent
RESOURCE_DIR = Path(os.environ.get("PAPERCATCH_RESOURCE_DIR", MODULE_DIR)).expanduser().resolve()
BASE_DIR = Path(os.environ.get("PAPERCATCH_DATA_DIR", MODULE_DIR)).expanduser().resolve()
VIEWER_DIR = RESOURCE_DIR / "viewer"
DB_JSON = BASE_DIR / "papers_database.json"
CATS_JSON = BASE_DIR / "papercatch_categories.json"
CONFIG_JSON = BASE_DIR / "search_config.json"
CRAWLED_IDS_FILE = BASE_DIR / "crawled_ids.txt"

ARXIV_NS = {"a": "http://www.w3.org/2005/Atom"}
API_NAMESPACES = ("/api", "/zotero", "/hermes")
SEARCH_CONFIG_FIELDS = frozenset({"categories", "keywords", "max_per_cat", "days", "sources"})
SEARCH_SOURCE_FIELDS = frozenset(DEFAULT_SOURCES)
INTEGRATION_FIELDS = frozenset({"api_key", "user_id", "default_collection"})
INTEGRATION_TOP_LEVEL_FIELDS = frozenset({"zotero"})
ARXIV_CATEGORY_RE = re.compile(r"^[A-Za-z0-9]+(?:[.-][A-Za-z0-9-]+)*$")
ZOTERO_USER_ID_RE = re.compile(r"^[0-9]{1,20}$")
LOCAL_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "::1"})
LOGGER = logging.getLogger(__name__)


def viewer_state_dir():
    """Return the optional writable mirror directory for legacy frontend JSON."""

    configured = os.environ.get("PAPERCATCH_VIEWER_STATE_DIR")
    return Path(configured).expanduser().resolve() if configured else VIEWER_DIR


def write_json_with_optional_viewer_mirror(primary_path, mirror_name, data):
    """Persist runtime data first; a legacy frontend mirror is best-effort."""

    write_json_atomic(primary_path, data)
    try:
        write_json_atomic(viewer_state_dir() / mirror_name, data)
    except JsonStoreError as exc:
        LOGGER.warning("Unable to update optional viewer JSON mirror %s: %s", mirror_name, exc)


class InvalidRequestBody(ValueError):
    """Raised when an HTTP request body is not valid JSON."""


class InvalidRequestData(ValueError):
    """Raised when parsed JSON does not match an endpoint schema."""


def is_api_path(path):
    return any(path == prefix or path.startswith(prefix + "/") for prefix in API_NAMESPACES)


def is_local_hostname(hostname):
    return bool(hostname) and hostname.rstrip(".").lower() in LOCAL_HOSTNAMES


def is_local_host_header(host_header):
    if not host_header:
        return False
    try:
        return is_local_hostname(urlparse(f"//{host_header}").hostname)
    except ValueError:
        return False


def is_local_origin(origin):
    if not origin:
        return False
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and is_local_hostname(parsed.hostname)


def validate_search_config(data):
    if not isinstance(data, dict):
        raise InvalidRequestData("expected JSON object")
    unknown = set(data) - SEARCH_CONFIG_FIELDS
    if unknown:
        raise InvalidRequestData(f"unknown fields: {', '.join(sorted(unknown))}")
    missing = {"categories", "keywords", "max_per_cat", "days"} - set(data)
    if missing:
        raise InvalidRequestData(f"missing fields: {', '.join(sorted(missing))}")

    categories = data["categories"]
    if not isinstance(categories, list) or not 1 <= len(categories) <= 50:
        raise InvalidRequestData("categories must contain 1 to 50 category strings")
    normalized_categories = []
    for category in categories:
        if not isinstance(category, str):
            raise InvalidRequestData("each category must be a string")
        category = category.strip()
        if not category or len(category) > 32 or not ARXIV_CATEGORY_RE.fullmatch(category):
            raise InvalidRequestData(f"invalid arXiv category: {category!r}")
        if category not in normalized_categories:
            normalized_categories.append(category)

    keywords = data["keywords"]
    if not isinstance(keywords, str) or len(keywords) > 1000:
        raise InvalidRequestData("keywords must be a string up to 1000 characters")

    max_per_cat = data["max_per_cat"]
    if type(max_per_cat) is not int or not 1 <= max_per_cat <= 100:
        raise InvalidRequestData("max_per_cat must be an integer from 1 to 100")

    days = data["days"]
    if type(days) is not int or not 0 <= days <= 30:
        raise InvalidRequestData("days must be an integer from 0 to 30")

    sources = data.get("sources", list(DEFAULT_SOURCES))
    if not isinstance(sources, list) or not 1 <= len(sources) <= len(SEARCH_SOURCE_FIELDS):
        raise InvalidRequestData("sources must contain 1 to 5 source names")
    normalized_sources = []
    for source in sources:
        if not isinstance(source, str) or source.strip().lower() not in SEARCH_SOURCE_FIELDS:
            raise InvalidRequestData(f"invalid paper source: {source!r}")
        source = source.strip().lower()
        if source not in normalized_sources:
            normalized_sources.append(source)
    if not normalized_sources:
        raise InvalidRequestData("sources must contain at least one source")

    normalized = {
        "categories": normalized_categories,
        "keywords": keywords.strip(),
        "max_per_cat": max_per_cat,
        "days": days,
    }
    # Keep legacy four-field configs byte-for-byte compatible; new clients can
    # opt into the public multi-source mode by sending ``sources`` explicitly.
    if "sources" in data:
        normalized["sources"] = normalized_sources
    return normalized


def normalize_requested_sources(value, *, strict=False):
    if value is None:
        return []
    if not isinstance(value, list):
        if strict:
            raise InvalidRequestData("sources must be an array of source names")
        return []
    if strict and not value:
        raise InvalidRequestData("sources must contain 1 to 5 supported source names")

    normalized = []
    for source in value:
        if strict and not isinstance(source, str):
            raise InvalidRequestData("sources must contain only strings")
        candidate = str(source).strip().lower()
        if not candidate:
            continue
        if strict and candidate not in SEARCH_SOURCE_FIELDS:
            raise InvalidRequestData(f"invalid paper source: {source!r}")
        if candidate in SEARCH_SOURCE_FIELDS and candidate not in normalized:
            normalized.append(candidate)

    if strict and not normalized:
        raise InvalidRequestData("sources must contain at least one supported source")
    return normalized


def validate_categories_config(data):
    if not isinstance(data, list) or len(data) > 100:
        raise InvalidRequestData("expected an array with at most 100 categories")
    normalized = []
    seen_ids = set()
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise InvalidRequestData(f"category {index} must be an object")
        unknown = set(item) - {"id", "label", "keywords"}
        if unknown:
            raise InvalidRequestData(
                f"category {index} has unknown fields: {', '.join(sorted(unknown))}"
            )
        category_id = item.get("id")
        label = item.get("label")
        keywords = item.get("keywords")
        if not isinstance(category_id, str) or not category_id.strip() or len(category_id) > 64:
            raise InvalidRequestData(f"category {index} has an invalid id")
        if not isinstance(label, str) or not label.strip() or len(label) > 100:
            raise InvalidRequestData(f"category {index} has an invalid label")
        if keywords is not None and (not isinstance(keywords, str) or len(keywords) > 1000):
            raise InvalidRequestData(f"category {index} has invalid keywords")
        category_id = category_id.strip()
        if category_id in seen_ids:
            raise InvalidRequestData(f"duplicate category id: {category_id}")
        seen_ids.add(category_id)
        normalized_item = {"id": category_id, "label": label.strip()}
        if keywords is not None:
            normalized_item["keywords"] = keywords.strip()
        normalized.append(normalized_item)
    return normalized


def validate_integrations_config(data):
    """Validate the public shape of the local integrations settings.

    The API key is intentionally accepted as an empty string: the save
    operation treats that value as "keep the existing key" so a redacted GET
    response can safely round-trip through the desktop form.
    """

    if not isinstance(data, dict):
        raise InvalidRequestData("expected JSON object")
    unknown = set(data) - INTEGRATION_TOP_LEVEL_FIELDS
    if unknown:
        raise InvalidRequestData(
            f"unknown fields: {', '.join(sorted(unknown))}"
        )
    if set(data) != INTEGRATION_TOP_LEVEL_FIELDS:
        raise InvalidRequestData("zotero settings are required")

    zotero = data["zotero"]
    if not isinstance(zotero, dict):
        raise InvalidRequestData("zotero must be an object")
    unknown = set(zotero) - INTEGRATION_FIELDS
    if unknown:
        raise InvalidRequestData(
            f"unknown zotero fields: {', '.join(sorted(unknown))}"
        )
    missing = INTEGRATION_FIELDS - set(zotero)
    if missing:
        raise InvalidRequestData(
            f"missing zotero fields: {', '.join(sorted(missing))}"
        )

    api_key = zotero["api_key"]
    if not isinstance(api_key, str):
        raise InvalidRequestData("api_key must be a string")
    if len(api_key) > 256 or any(ord(char) < 32 or ord(char) == 127 for char in api_key):
        raise InvalidRequestData("api_key contains invalid characters")
    if api_key and (api_key != api_key.strip() or any(char.isspace() for char in api_key)):
        raise InvalidRequestData("api_key must not contain whitespace")

    user_id = zotero["user_id"]
    if not isinstance(user_id, str) or not ZOTERO_USER_ID_RE.fullmatch(user_id.strip()):
        raise InvalidRequestData("user_id must contain 1 to 20 digits")
    user_id = user_id.strip()

    default_collection = zotero["default_collection"]
    if not isinstance(default_collection, str):
        raise InvalidRequestData("default_collection must be a string")
    default_collection = default_collection.strip()
    if not default_collection or len(default_collection) > 500:
        raise InvalidRequestData(
            "default_collection must contain 1 to 500 characters"
        )
    if any(ord(char) < 32 or ord(char) == 127 for char in default_collection):
        raise InvalidRequestData("default_collection contains invalid characters")

    return {
        "zotero": {
            "api_key": api_key,
            "user_id": user_id,
            "default_collection": default_collection,
        }
    }


# ── Config ──────────────────────────────────────────────
def load_app_config():
    return load_config(BASE_DIR / "config.local.json")


def reload_runtime_config():
    """Reload effective Zotero settings after a local config update.

    ``load_config`` applies non-empty environment variables after the file,
    so desktop saves remain editable while deployment-level overrides retain
    their precedence.
    """

    global APP_CONFIG, ZOTERO_API_KEY, ZOTERO_USER_ID, ZOTERO_API_ROOT, DEFAULT_COLLECTION
    APP_CONFIG = load_app_config()
    zotero = APP_CONFIG.get("zotero", {})
    if not isinstance(zotero, dict):
        zotero = {}
    ZOTERO_API_KEY = str(zotero.get("api_key") or "")
    ZOTERO_USER_ID = str(zotero.get("user_id") or "")
    ZOTERO_API_ROOT = f"https://api.zotero.org/users/{ZOTERO_USER_ID}" if ZOTERO_USER_ID else ""
    DEFAULT_COLLECTION = str(
        zotero.get("default_collection") or "PaperCatch/Hermes Search"
    )


reload_runtime_config()


def public_zotero_status():
    """Return the intentionally redacted Zotero state exposed to the UI."""

    return {
        "configured": bool(ZOTERO_API_KEY and ZOTERO_USER_ID),
        "user_id": ZOTERO_USER_ID,
        "default_collection": DEFAULT_COLLECTION,
    }


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


# ── LLM-powered query parser ─────────────────────────────
def _load_dotenv(path):
    """Load a simple .env file (no shell expansion, no quotes handling)."""
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if key and key not in os.environ:
                os.environ[key] = val


def _llm_config():
    """Read DeepSeek config from config.local.json, env, or Hermes .env."""
    # 1. Try config.local.json (preferred)
    app_cfg = load_app_config()
    llm = app_cfg.get("llm", {})
    key = llm.get("api_key", "")
    base = llm.get("base_url", "")
    if key and base:
        return key, base
    
    # 2. Try loading Hermes .env
    hermes_env = os.path.join(os.path.expanduser("~"), "AppData", "Local", "hermes", ".env")
    _load_dotenv(hermes_env)
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    base = os.environ.get("DEEPSEEK_BASE_URL", "")
    
    # 3. Try current environment
    if not key:
        key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not base:
        base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    return key, base


def llm_parse_query(message):
    """Use DeepSeek LLM to intelligently parse a natural-language arXiv query.

    Returns the same dict shape as parse_query(), or None if LLM is unavailable.
    """
    api_key, base_url = _llm_config()
    if not api_key:
        return None

    system_prompt = (
        "You are an arXiv search assistant. Given a user's natural language request (in Chinese or English), "
        "output ONLY a JSON object with these fields:\n"
        '  "keywords": list of English search terms for arXiv (max 8). Translate Chinese concepts to English. '
        'For example "大语言模型" → "large language model", "多智能体" → "multi-agent". '
        'For ambiguous short words like "hermes", add clarifying terms if the intent is clear '
        '(e.g. "Hermes agent" if they mean the AI agent framework, or keep as-is if unclear).\n'
        '  "days": integer, time range in days (0 = no limit, 1 = today, 7 = this week).\n'
        '  "max_results": integer, number of papers to return (default 8, max 50).\n'
        '  "auto_zotero": boolean, whether the user wants to add papers to Zotero.\n'
        '  "collection": string or null, Zotero collection path if specified (e.g. "PaperCatch/Agent").\n\n'
        "Rules:\n"
        "- Understand the user's INTENT, not just keywords. "
        'If they say "最近AI safety论文" search for "AI safety" not just "AI" and "safety" separately.\n'
        "- For short/ambiguous search terms, keep them as-is but prefer phrase search when possible.\n"
        "- Default max_results=8, days=0 unless specified.\n"
        "- Output ONLY the JSON, no explanation."
    )

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ],
        "temperature": 0,
        "max_tokens": 300,
        "response_format": {"type": "json_object"},
    }

    try:
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        content_text = data["choices"][0]["message"]["content"]
        parsed = json.loads(content_text)

        return {
            "keywords": parsed.get("keywords", [])[:8],
            "days": max(0, min(60, int(parsed.get("days", 0)))),
            "max_results": max(1, min(50, int(parsed.get("max_results", 8)))),
            "auto_zotero": bool(parsed.get("auto_zotero", False)),
            "collection": parsed.get("collection") or DEFAULT_COLLECTION,
        }
    except Exception as e:
        pass  # LLM parse failed silently
        return None


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
            "open_access": True,
            "is_open_access": True,
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


def paper_identity(paper):
    return str(
        paper.get("paper_id")
        or paper.get("arxiv_id")
        or paper.get("doi")
        or paper.get("pmid")
        or paper.get("title")
        or ""
    ).strip()


def normalize_doi_identifier(value):
    text = str(value or "").strip()
    text = re.sub(r"^https?://doi\.org/", "", text, flags=re.I)
    return text.rstrip(" .").lower()


def normalize_arxiv_identifier(value):
    text = str(value or "").strip()
    if text.startswith("arxiv:"):
        text = text.split(":", 1)[1]
    return text.split("v", 1)[0]


def paper_lookup_keys(paper):
    keys = set()
    for value in (
        str(paper.get("paper_id") or "").strip(),
        str(paper.get("arxiv_id") or "").strip(),
        str(paper.get("pmid") or "").strip(),
    ):
        if value:
            keys.add(value)
    doi = normalize_doi_identifier(paper.get("doi"))
    if doi:
        keys.add(doi)
        keys.add(f"doi:{doi}")
    arxiv_id = normalize_arxiv_identifier(paper.get("arxiv_id"))
    if arxiv_id:
        keys.add(arxiv_id)
        keys.add(f"arxiv:{arxiv_id}")
    pmid = str(paper.get("pmid") or "").strip()
    if pmid:
        keys.add(f"pmid:{pmid}")
    return keys


def normalize_download_identifiers(body):
    raw_groups = []
    for field in ("paper_ids", "arxiv_ids"):
        raw_value = body.get(field)
        if raw_value is None:
            continue
        if not isinstance(raw_value, list):
            raise InvalidRequestData(f"{field} must be an array of strings")
        raw_groups.extend(raw_value)
    if not raw_groups:
        raise InvalidRequestData("paper_ids or arxiv_ids is required")

    identifiers = []
    for value in raw_groups:
        if not isinstance(value, str) or not value.strip():
            raise InvalidRequestData("paper_ids and arxiv_ids must be arrays of strings")
        normalized = value.strip()
        if normalized not in identifiers:
            identifiers.append(normalized)
    if not 1 <= len(identifiers) <= 10:
        raise InvalidRequestData("paper_ids and arxiv_ids must contain 1 to 10 unique strings")
    return identifiers


def merge_into_db(new_papers):
    """Merge freshly-found papers into papers_database.json, preserving existing fields."""
    added = 0

    def update(db):
        nonlocal added
        existing = {paper_identity(p): p for p in db.get("papers", []) if paper_identity(p)}
        for p in new_papers:
            identity = paper_identity(p)
            if not identity:
                continue
            p.setdefault("paper_id", identity)
            p.setdefault("arxiv_id", identity)
            if identity in existing:
                # keep existing enriched fields
                for k, v in p.items():
                    existing[identity].setdefault(k, v)
            else:
                # Set Chinese placeholders for new papers (LLM will replace later)
                p.setdefault("title_cn", p.get("title", "")[:80])
                p.setdefault("abstract_cn", p.get("abstract", "")[:200])
                p.setdefault("summary_cn", "待 LLM 生成")
                p.setdefault("background_cn", "")
                p.setdefault("affiliations", "")
                p.setdefault("quality_score", None)
                p.setdefault("quality_signals", {})
                p.setdefault("zotero_status", None)
                p.setdefault("crawled_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
                p.setdefault("tags", [])
                existing[identity] = p
                added += 1
        db["papers"] = list(existing.values())
        db["total_count"] = len(db["papers"])
        db["updated_at"] = datetime.now(timezone.utc).isoformat()
        db["categories"] = sorted({c for p in db["papers"] for c in p.get("categories", [])})
        return db

    locked_update_json(
        DB_JSON,
        {"updated_at": "", "total_count": 0, "categories": [], "papers": []},
        update,
    )
    # record crawled ids
    try:
        with open(CRAWLED_IDS_FILE, "a", encoding="utf-8") as f:
            for p in new_papers:
                f.write(paper_identity(p) + "\n")
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
    doi = paper.get("doi") or ""
    source = ", ".join(paper.get("sources") or [paper.get("source") or "PaperCatch"])
    item = {
        "itemType": "journalArticle" if doi else "preprint",
        "title": paper.get("title", ""),
        "creators": authors,
        "abstractNote": paper.get("abstract_full") or paper.get("abstract", ""),
        "url": paper.get("landing_url") or paper.get("abs_url", ""),
        "date": paper.get("published", ""),
        "repository": source,
        "archiveID": "arXiv:" + paper.get("arxiv_id", "") if paper.get("arxiv_id", "").startswith(tuple("0123456789")) else "",
        "extra": "DOI: " + doi if doi else "arXiv: " + paper.get("arxiv_id", ""),
        "collections": [collection_key] if collection_key else [],
        "tags": [{"tag": t} for t in paper.get("tags", []) if t],
    }
    if doi:
        item["DOI"] = doi
        if paper.get("venue"):
            item["publicationTitle"] = paper["venue"]
    return item


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
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def json_error(self, code, message, status, **extra):
        payload = {
            "success": False,
            "error": {"code": code, "message": message},
        }
        payload.update(extra)
        self.json_response(payload, status)

    def read_body(self):
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length) if raw_length is not None else 0
        except (TypeError, ValueError) as exc:
            raise InvalidRequestBody("Content-Length must be a non-negative integer") from exc
        if length <= 0:
            raise InvalidRequestBody("Request body must contain valid JSON")
        raw_body = self.rfile.read(length)
        if len(raw_body) != length:
            raise InvalidRequestBody("Request body ended before Content-Length bytes were read")
        try:
            return json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidRequestBody("Request body must contain valid UTF-8 JSON") from exc

    def validate_mutation_request(self):
        if self.headers.get_content_type() != "application/json":
            self.json_error(
                "unsupported_media_type",
                "mutating requests must use Content-Type: application/json",
                415,
            )
            return False
        origin = self.headers.get("Origin")
        if origin and not is_local_origin(origin):
            self.json_error("invalid_origin", "Origin must be a loopback address", 403)
            return False
        return True

    def validate_request_host(self):
        if is_local_host_header(self.headers.get("Host")):
            return True
        self.json_error("invalid_host", "Host must be a loopback address", 403)
        return False

    def storage_error_response(self, exc):
        LOGGER.error("PaperCatch JSON storage operation failed: %s", exc)
        self.json_error(
            "storage_error",
            "Stored JSON data is invalid or unavailable",
            500,
        )

    # ── GET ──
    def do_GET(self):
        if not self.validate_request_host():
            return
        path = unquote(urlparse(self.path).path)
        try:
            if path == "/api/papers":
                self.json_response(read_json(DB_JSON, {"papers": [], "total_count": 0}))
            elif path == "/api/categories":
                self.json_response(read_json(CATS_JSON, []))
            elif path == "/api/config":
                self.json_response(read_json(CONFIG_JSON, {
                    "categories": ["cs.AI", "cs.CL", "cs.CV", "cs.LG"],
                    "keywords": "",
                    "max_per_cat": 25,
                    "days": 0,
                    "sources": list(DEFAULT_SOURCES),
                }))
            elif path == "/api/sources":
                self.json_response({
                    "sources": list(DEFAULT_SOURCES),
                    "description": "公开元数据聚合源；开放获取 PDF 由各源返回的明确链接决定",
                })
            elif path == "/api/integrations":
                self.json_response({"zotero": public_zotero_status()})
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
            elif is_api_path(path):
                self.json_error("not_found", f"Unknown endpoint: {path}", 404)
            else:
                self.serve_static(path)
        except JsonStoreError as exc:
            self.storage_error_response(exc)

    def serve_static(self, path):
        try:
            viewer_root = VIEWER_DIR.resolve()
            normalized_path = path.replace("\\", "/")
            if normalized_path == "/":
                filepath = viewer_root / "index.html"
            else:
                filepath = (viewer_root / normalized_path.lstrip("/")).resolve()
            filepath.relative_to(viewer_root)
        except (OSError, RuntimeError, ValueError):
            self.send_error(404)
            return
        if not filepath.is_file():
            self.send_error(404)
            return
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
        if not self.validate_request_host():
            return
        path = unquote(urlparse(self.path).path)
        handler = {
            "/hermes/search": self.handle_hermes_search,
            "/hermes/ask": self.handle_hermes_ask,
            "/hermes/notes": self.handle_hermes_notes,
            "/api/papers/download": self.handle_papers_download,
            "/api/enrich": self.handle_enrich_save,
            "/zotero/add": self.handle_zotero_add,
            "/api/categories": self.handle_cats_save,
            "/api/config": self.handle_config_save,
            "/api/integrations": self.handle_integrations_save,
        }.get(path)
        if handler is None:
            self.json_error("not_found", f"Unknown endpoint: {path}", 404)
            return
        if not self.validate_mutation_request():
            return
        try:
            body = self.read_body()
        except InvalidRequestBody as exc:
            self.json_error("invalid_json", str(exc), 400)
            return
        expected_type = list if path == "/api/categories" else dict
        if not isinstance(body, expected_type):
            expected_name = "array" if expected_type is list else "object"
            self.json_error("invalid_request", f"expected JSON {expected_name}", 400)
            return
        try:
            handler(body)
        except JsonStoreError as exc:
            self.storage_error_response(exc)

    def do_DELETE(self):
        if not self.validate_request_host():
            return
        path = unquote(urlparse(self.path).path)
        if path != "/api/papers":
            self.json_error("not_found", f"Unknown endpoint: {path}", 404)
            return
        if not self.validate_mutation_request():
            return
        try:
            body = self.read_body()
        except InvalidRequestBody as exc:
            self.json_error("invalid_json", str(exc), 400)
            return
        if not isinstance(body, dict):
            self.json_error("invalid_request", "expected JSON object", 400)
            return
        try:
            self.handle_papers_delete(body)
        except JsonStoreError as exc:
            self.storage_error_response(exc)

    def do_OPTIONS(self):
        if not self.validate_request_host():
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ── Handlers ──
    def handle_hermes_search(self, body):
        message_value = body.get("message")
        if not isinstance(message_value, str):
            self.json_error("invalid_request", "message must be a string", 400)
            return
        message = message_value.strip()
        if not message:
            self.json_error("invalid_request", "请输入搜索内容", 400)
            return

        # Try LLM-powered parsing first, fall back to rule-based
        try:
            params = llm_parse_query(message)
        except Exception:
            params = None
        llm_used = params is not None
        if params is None:
            params = parse_query(message)
        configured = read_json(CONFIG_JSON, {})
        if "sources" in body:
            try:
                requested_sources = normalize_requested_sources(body.get("sources"), strict=True)
            except InvalidRequestData as exc:
                self.json_error("invalid_request", str(exc), 400)
                return
        else:
            requested_sources = None
            if isinstance(configured, dict):
                requested_sources = configured.get("sources")
            requested_sources = normalize_requested_sources(requested_sources)
        use_multi_source = bool(requested_sources and any(source != "arxiv" for source in requested_sources))
        source_errors = {}
        source_counts = {}
        if use_multi_source:
            try:
                batch = search_all_sources(
                    params["keywords"],
                    sources=requested_sources,
                    max_results=params["max_results"],
                    days=params["days"],
                )
                papers = batch["papers"]
                source_errors = batch["source_errors"]
                source_counts = batch["source_counts"]
                if not papers and source_errors and set(source_errors) >= set(requested_sources):
                    self.json_error(
                        "upstream_error",
                        "多源搜索失败：所有请求来源都不可用",
                        502,
                        source_errors=source_errors,
                    )
                    return
            except Exception as e:
                self.json_error("upstream_error", f"多源搜索失败：{e}", 502)
                return
        else:
            try:
                papers = arxiv_search(params["keywords"], params["max_results"], params["days"])
            except Exception as e:
                self.json_error("upstream_error", f"arXiv 搜索失败：{e}", 502)
                return

        added = merge_into_db(papers) if papers else 0

        # Auto-enrich new papers: tags + quality scores + mark pending
        warnings = []
        enrichment = {
            "status": "skipped",
            "updated_fields": 0,
            "pending_count": 0,
        }
        if papers:
            updated_fields = None
            pending_count = None
            try:
                updated_fields = local_enrich(db_path=DB_JSON)
            except Exception as exc:
                LOGGER.error("Local enrichment failed: %s", exc)
                warnings.append({
                    "code": "local_enrichment_failed",
                    "message": "论文已保存，但标签与评分增强失败",
                })
            try:
                pending_count = mark_pending(
                    db_path=DB_JSON,
                    pending_path=BASE_DIR / "pending_enrichment.json",
                )
            except Exception as exc:
                LOGGER.error("Pending enrichment generation failed: %s", exc)
                warnings.append({
                    "code": "pending_enrichment_failed",
                    "message": "论文已保存，但待增强清单生成失败",
                })
            if not warnings:
                enrichment["status"] = "completed"
            elif updated_fields is None and pending_count is None:
                enrichment["status"] = "failed"
            else:
                enrichment["status"] = "partial"
            enrichment["updated_fields"] = updated_fields
            enrichment["pending_count"] = pending_count

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
        source_text = "、".join(requested_sources) if use_multi_source else "arXiv"
        msg = (f"从 {source_text} 找到 {len(papers)} 篇关于「{kw_text}」的论文（{day_text}），"
               f"新增 {added} 篇到列表{zotero_note}。")
        if papers:
            msg += "\n提示：新论文的中文标题/摘要/总结需由 Hermes agent 生成，可运行增强流程。"
        if warnings:
            msg += "\n警告：" + "；".join(item["message"] for item in warnings)
        self.json_response({
            "success": True,
            "message": msg,
            "parsed": params,
            "llm_used": llm_used,
            "papers": papers,
            "sources": requested_sources or ["arxiv"],
            "source_counts": source_counts,
            "source_errors": source_errors,
            "enrichment": enrichment,
            "warnings": warnings,
        })

    @staticmethod
    def _find_paper(db: dict, identifier: str) -> dict | None:
        identifier = str(identifier or "").strip()
        if not identifier:
            return None
        for paper in db.get("papers", []):
            if identifier in paper_lookup_keys(paper):
                return paper
        return None

    def _agent_paper(self, body):
        identifier = body.get("paper_id") or body.get("arxiv_id") or body.get("doi") or body.get("pmid")
        if not isinstance(identifier, str) or not identifier.strip():
            self.json_error("invalid_request", "paper_id or arxiv_id is required", 400)
            return None
        db = read_json(DB_JSON, {"papers": []})
        paper = self._find_paper(db, identifier)
        if paper is None:
            self.json_error("not_found", "paper not found", 404)
            return None
        return paper

    def handle_hermes_ask(self, body):
        paper = self._agent_paper(body)
        if paper is None:
            return
        question = body.get("question")
        if not isinstance(question, str) or not question.strip():
            self.json_error("invalid_request", "question must be a non-empty string", 400)
            return
        try:
            result = answer_question(paper, question)
        except ValueError as exc:
            self.json_error("invalid_request", str(exc), 400)
            return
        self.json_response({"success": True, **result})

    def handle_hermes_notes(self, body):
        paper = self._agent_paper(body)
        if paper is None:
            return
        focus = body.get("focus", "")
        if not isinstance(focus, str):
            self.json_error("invalid_request", "focus must be a string", 400)
            return
        try:
            result = generate_learning_notes(paper, focus)
        except ValueError as exc:
            self.json_error("invalid_request", str(exc), 400)
            return
        self.json_response({"success": True, **result})

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
        if items is None and "arxiv_id" in body:
            items = [body]
        if not isinstance(items, list) or not items:
            self.json_error("invalid_request", "items must be a non-empty array", 400)
            return
        if any(
            not isinstance(item, dict)
            or not isinstance(item.get("arxiv_id"), str)
            or not item.get("arxiv_id", "").strip()
            for item in items
        ):
            self.json_error("invalid_request", "each item needs a string arxiv_id", 400)
            return
        fields = ["title_cn", "abstract_cn", "summary_cn", "background_cn",
                  "affiliations", "tags", "quality_score", "quality_signals"]
        updated = 0

        def update(db):
            nonlocal updated
            index = {p["arxiv_id"]: p for p in db.get("papers", [])}
            for item in items:
                aid = item.get("arxiv_id")
                paper = index.get(aid)
                if not paper:
                    continue
                changed = False
                for f in fields:
                    if f in item and item[f] not in (None, "") and paper.get(f) != item[f]:
                        paper[f] = item[f]
                        changed = True
                if changed:
                    updated += 1
            if updated:
                db["updated_at"] = datetime.now(timezone.utc).isoformat()
            return db

        locked_update_json(DB_JSON, {"papers": []}, update)
        self.json_response({"success": True, "updated": updated})

    def handle_papers_download(self, body):
        try:
            identifiers = normalize_download_identifiers(body)
        except InvalidRequestData as exc:
            self.json_error("invalid_request", str(exc), 400)
            return

        results = []
        counts = {"downloaded": 0, "already_exists": 0, "failed": 0, "not_found": 0}
        db = read_json(DB_JSON, {"papers": []})
        seen_papers = set()
        for identifier in identifiers:
            paper = self._find_paper(db, identifier)
            if paper is None:
                counts["not_found"] += 1
                counts["failed"] += 1
                results.append({
                    "requested_id": identifier,
                    "paper_id": "",
                    "arxiv_id": "",
                    "status": "not_found",
                    "reason": "paper_not_found",
                })
                continue

            paper_key = paper_identity(paper)
            if paper_key in seen_papers:
                continue
            seen_papers.add(paper_key)

            result = download_open_access_pdf(paper, BASE_DIR)
            results.append({"requested_id": identifier, **result})
            if result["status"] == "downloaded":
                counts["downloaded"] += 1
            elif result["status"] == "already_exists":
                counts["already_exists"] += 1
            else:
                counts["failed"] += 1

            def update(fresh):
                for current in fresh.get("papers", []):
                    if paper_identity(current) != paper_key:
                        continue
                    current["download_status"] = result["status"]
                    current["download_reason"] = result.get("reason", "")
                    current["downloaded_at"] = result.get("downloaded_at", "")
                    if result["status"] in {"downloaded", "already_exists"} and result.get("file_path"):
                        current["pdf_path"] = result["file_path"]
                    break
                return fresh

            locked_update_json(DB_JSON, {"papers": []}, update)
            db = read_json(DB_JSON, {"papers": []})

        self.json_response({"success": True, "results": results, **counts})

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
            self.json_error(
                "not_configured",
                "Zotero not configured",
                200,
                collections=[],
            )
            return
        try:
            paths, _, _ = list_zotero_collections()
            self.json_response({"success": True, "collections": sorted(paths.keys())})
        except Exception as e:
            self.json_error("upstream_error", str(e), 502, collections=[])

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
        def update(fresh):
            fresh_index = {p["arxiv_id"]: p for p in fresh.get("papers", [])}
            for r in results:
                if r["status"] == "added" and r["arxiv_id"] in fresh_index:
                    fresh_index[r["arxiv_id"]]["zotero_status"] = "added"
                    fresh_index[r["arxiv_id"]]["zotero_collection"] = r["collection"]
            return fresh

        locked_update_json(DB_JSON, {"papers": []}, update)
        added = sum(1 for r in results if r["status"] == "added")
        return {"added": added, "failed": len(results) - added, "results": results}

    def handle_zotero_add(self, body):
        arxiv_ids = body.get("arxiv_ids", [])
        collection = body.get("collection") or DEFAULT_COLLECTION
        collection_map = body.get("collection_map")
        if (
            not isinstance(arxiv_ids, list)
            or any(not isinstance(aid, str) or not aid.strip() for aid in arxiv_ids)
        ):
            self.json_error("invalid_request", "arxiv_ids must be an array of strings", 400)
            return
        if collection_map is not None and not isinstance(collection_map, dict):
            self.json_error("invalid_request", "collection_map must be an object", 400)
            return
        if not arxiv_ids:
            self.json_error("invalid_request", "no arxiv_ids", 400)
            return
        if not (ZOTERO_API_KEY and ZOTERO_USER_ID):
            self.json_error("not_configured", "Zotero is not configured", 500)
            return
        try:
            res = self._zotero_add_ids(arxiv_ids, collection, collection_map)
            self.json_response({"success": True, **res})
        except JsonStoreError:
            raise
        except Exception as e:
            self.json_error("upstream_error", str(e), 502)

    def handle_cats_save(self, body):
        try:
            normalized = validate_categories_config(body)
        except InvalidRequestData as exc:
            self.json_error("invalid_request", str(exc), 400)
            return
        write_json_with_optional_viewer_mirror(
            CATS_JSON,
            "papercatch_categories.json",
            normalized,
        )
        self.json_response({"success": True})

    def handle_config_save(self, body):
        try:
            normalized = validate_search_config(body)
        except InvalidRequestData as exc:
            self.json_error("invalid_request", str(exc), 400)
            return
        write_json_with_optional_viewer_mirror(
            CONFIG_JSON,
            "search_config.json",
            normalized,
        )
        self.json_response({"success": True})

    def handle_integrations_save(self, body):
        """Save local Zotero settings without exposing the API key.

        Only the three desktop-editable fields are touched.  The existing
        document is read and replaced under the shared JSON sidecar lock, so
        unrelated settings survive concurrent updates.  An empty API key is
        the redacted form returned by GET and therefore deliberately leaves
        the existing file value unchanged.
        """

        try:
            normalized = validate_integrations_config(body)
        except InvalidRequestData as exc:
            self.json_error("invalid_request", str(exc), 400)
            return

        requested = normalized["zotero"]
        config_path = BASE_DIR / "config.local.json"

        def update(config):
            if not isinstance(config, dict):
                raise JsonStoreError("config.local.json must contain a JSON object")
            current = config.get("zotero", {})
            if not isinstance(current, dict):
                raise JsonStoreError("config.local.json zotero section must be an object")
            current = dict(current)
            if requested["api_key"]:
                current["api_key"] = requested["api_key"]
            elif "api_key" in current and not isinstance(current["api_key"], str):
                raise JsonStoreError("config.local.json zotero api_key must be a string")
            current["user_id"] = requested["user_id"]
            current["default_collection"] = requested["default_collection"]
            replacement = dict(config)
            replacement["zotero"] = current
            return replacement

        locked_update_json(config_path, {}, update)
        reload_runtime_config()
        self.json_response({"success": True, "zotero": public_zotero_status()})

    def handle_papers_delete(self, body):
        raw_ids = body.get("arxiv_ids", [])
        if (
            not isinstance(raw_ids, list)
            or any(not isinstance(arxiv_id, str) or not arxiv_id.strip() for arxiv_id in raw_ids)
        ):
            self.json_error("invalid_request", "arxiv_ids must be an array of strings", 400)
            return
        ids = set(raw_ids)
        removed = 0

        def update(db):
            nonlocal removed
            before = len(db.get("papers", []))
            db["papers"] = [p for p in db.get("papers", []) if p["arxiv_id"] not in ids]
            db["total_count"] = len(db["papers"])
            removed = before - len(db["papers"])
            return db

        locked_update_json(DB_JSON, {"papers": []}, update)
        self.json_response({"success": True, "removed": removed})


def create_server(port):
    VIEWER_DIR.mkdir(parents=True, exist_ok=True)
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = create_server(args.port)
    print(f"PaperCatch http://localhost:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()



