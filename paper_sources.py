#!/usr/bin/env python3
"""Configurable multi-source paper discovery for PaperCatch.

The module intentionally uses only the Python standard library.  It searches
public metadata APIs, normalizes their records, and never marks a paywalled
landing page as an accessible PDF.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

from json_store import write_json_atomic


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_JSON = BASE_DIR / "new_papers.json"
DEFAULT_SOURCES = ["arxiv", "openalex", "crossref", "semantic_scholar", "europe_pmc"]
SUPPORTED_SOURCES = tuple(DEFAULT_SOURCES)
ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}
OPENSEARCH_NS = "http://a9.com/-/spec/opensearch/1.1/"
SOURCE_LIMIT = 100


class SourceRequestError(RuntimeError):
    """Raised when a public source cannot be queried."""


def normalize_keywords(value: str | list[str] | None) -> list[str]:
    if isinstance(value, list):
        raw = value
    else:
        raw = re.split(r"[,，;；\n]+", str(value or ""))
    result: list[str] = []
    seen: set[str] = set()
    for item in raw:
        item = re.sub(r"\s+", " ", str(item).strip())
        key = item.casefold()
        if item and key not in seen:
            seen.add(key)
            result.append(item)
    return result[:16]


def _request_json(url: str, timeout: int = 20) -> Any:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "PaperCatch/2.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # pragma: no cover - exact network errors vary by host
        raise SourceRequestError(str(exc)) from exc


Fetcher = Callable[[str], Any]


def _date_cutoff(days: int) -> str | None:
    if days <= 0:
        return None
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


def _date_value(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        if not value:
            return ""
        return "-".join(f"{int(part):02d}" for part in value)
    text = str(value or "").strip()
    if re.fullmatch(r"\d{4}", text):
        return text + "-01-01"
    return text[:10] if text else ""


def _authors(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            name = str(
                item.get("name")
                or item.get("display_name")
                or " ".join(filter(None, [item.get("given"), item.get("family")]))
                or ""
            ).strip()
        else:
            name = ""
        if name:
            result.append(name)
    return result[:100]


def _doi(value: Any) -> str:
    value = str(value or "").strip()
    value = re.sub(r"^https?://doi\.org/", "", value, flags=re.I)
    return value.rstrip(" .").lower()


def _title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()


def _paper(
    *,
    source: str,
    title: str,
    authors: Any = None,
    abstract: str = "",
    published: Any = "",
    updated: Any = "",
    doi: Any = "",
    arxiv_id: Any = "",
    pmid: Any = "",
    openalex_id: Any = "",
    venue: str = "",
    landing_url: str = "",
    pdf_url: str = "",
    open_access: bool | None = None,
    citations: Any = None,
    fields_of_study: Any = None,
) -> dict[str, Any]:
    title = re.sub(r"\s+", " ", str(title or "").strip())
    abstract = re.sub(r"\s+", " ", str(abstract or "").strip())
    clean_arxiv = str(arxiv_id or "").strip()
    clean_pmid = str(pmid or "").strip()
    clean_openalex = str(openalex_id or "").strip()
    clean_doi = _doi(doi)
    if clean_doi:
        paper_id = f"doi:{clean_doi}"
    elif clean_arxiv:
        paper_id = f"arxiv:{clean_arxiv.split('v', 1)[0]}"
    elif clean_pmid:
        paper_id = f"pmid:{clean_pmid}"
    elif clean_openalex:
        paper_id = f"openalex:{clean_openalex.rsplit('/', 1)[-1]}"
    else:
        digest = hashlib.sha1(_title_key(title).encode("utf-8")).hexdigest()[:16]
        paper_id = f"title:{digest}"
    source_url = str(landing_url or "").strip()
    pdf_url = str(pdf_url or "").strip()
    return {
        "paper_id": paper_id,
        # Keep the historic field so existing merge/Zotero code remains usable.
        "arxiv_id": clean_arxiv or paper_id,
        "doi": clean_doi,
        "pmid": clean_pmid,
        "openalex_id": clean_openalex,
        "source": source,
        "sources": [source],
        "source_ids": {source: paper_id},
        "title": title,
        "authors": _authors(authors),
        "published": _date_value(published),
        "updated": _date_value(updated),
        "abstract": abstract[:800],
        "abstract_full": abstract,
        "venue": str(venue or "").strip(),
        "fields_of_study": list(fields_of_study or [])[:30]
        if isinstance(fields_of_study, (list, tuple))
        else [],
        "citations": citations,
        "influential_citations": None,
        "reference_count": None,
        "is_open_access": open_access,
        # A publisher/Crossref link alone is not proof of OA entitlement.
        "open_access": bool(open_access) if open_access is not None else False,
        "landing_url": source_url,
        "abs_url": source_url,
        "pdf_url": pdf_url if open_access is not False else "",
        "categories": [],
        "primary_cat": "",
        "tags": [],
        "title_cn": "",
        "abstract_cn": "",
        "summary_cn": "",
        "background_cn": "",
        "affiliations": "",
        "quality_score": None,
        "quality_signals": {},
        "zotero_status": None,
        "crawled_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


def _arxiv_search_url(keywords: list[str], limit: int) -> str:
    terms = normalize_keywords(keywords)
    query = " OR ".join(
        f'all:"{term}"' if " " in term else f"all:{term}" for term in terms
    ) or "all:machine+learning"
    return "https://export.arxiv.org/api/query?" + urlencode(
        {"search_query": query, "sortBy": "submittedDate", "sortOrder": "descending", "max_results": limit}
    )


def search_arxiv(keywords: list[str], limit: int, days: int, fetcher: Fetcher = _request_json) -> list[dict[str, Any]]:
    # The arXiv endpoint is Atom, so use a small adapter around the shared opener.
    url = _arxiv_search_url(keywords, limit)
    request = urllib.request.Request(url, headers={"User-Agent": "PaperCatch/2.0"})
    try:
        if fetcher is _request_json:
            with urllib.request.urlopen(request, timeout=20) as response:
                root = ET.fromstring(response.read())
        else:
            raw = fetcher(url)
            if isinstance(raw, ET.Element):
                root = raw
            elif isinstance(raw, bytes):
                root = ET.fromstring(raw)
            else:
                root = ET.fromstring(str(raw).encode("utf-8"))
    except Exception as exc:
        raise SourceRequestError(str(exc)) from exc
    cutoff = _date_cutoff(days)
    papers = []
    for entry in root.findall("a:entry", ATOM_NS):
        raw_id = (entry.findtext("a:id", "", ATOM_NS) or "").strip()
        arxiv_id = raw_id.rsplit("/abs/", 1)[-1].split("v", 1)[0]
        published = (entry.findtext("a:published", "", ATOM_NS) or "")[:10]
        if cutoff and published and published < cutoff:
            continue
        categories = [node.get("term", "") for node in entry.findall("a:category", ATOM_NS)]
        item = _paper(
            source="arxiv",
            title=entry.findtext("a:title", "", ATOM_NS),
            authors=[node.findtext("a:name", "", ATOM_NS) for node in entry.findall("a:author", ATOM_NS)],
            abstract=entry.findtext("a:summary", "", ATOM_NS),
            published=published,
            updated=(entry.findtext("a:updated", "", ATOM_NS) or "")[:10],
            arxiv_id=arxiv_id,
            landing_url=f"https://arxiv.org/abs/{arxiv_id}",
            pdf_url=f"https://arxiv.org/pdf/{arxiv_id}.pdf",
            open_access=True,
        )
        item["categories"] = categories
        item["primary_cat"] = categories[0] if categories else ""
        papers.append(item)
        if len(papers) >= limit:
            break
    return papers


def search_openalex(keywords: list[str], limit: int, days: int, fetcher: Fetcher = _request_json) -> list[dict[str, Any]]:
    params = {"search": " ".join(normalize_keywords(keywords)), "per-page": min(limit, SOURCE_LIMIT), "mailto": ""}
    cutoff = _date_cutoff(days)
    if cutoff:
        params["filter"] = f"from_publication_date:{cutoff}"
    data = fetcher("https://api.openalex.org/works?" + urlencode({k: v for k, v in params.items() if v != ""}))
    papers = []
    for row in (data or {}).get("results", []):
        location = row.get("best_oa_location") or row.get("primary_location") or {}
        oa = row.get("open_access") or {}
        doi = (row.get("doi") or (row.get("ids") or {}).get("doi") or "")
        item = _paper(
            source="openalex",
            title=row.get("title", ""),
            authors=[(a.get("author") or {}) for a in row.get("authorships", [])],
            abstract=row.get("abstract_inverted_index") and _openalex_abstract(row.get("abstract_inverted_index")) or "",
            published=row.get("publication_date", ""),
            doi=doi,
            openalex_id=row.get("id", ""),
            venue=((row.get("primary_location") or {}).get("source") or {}).get("display_name", ""),
            landing_url=location.get("landing_page_url") or row.get("id", ""),
            pdf_url=location.get("pdf_url", ""),
            open_access=bool(oa.get("is_oa") or location.get("pdf_url")),
            citations=row.get("cited_by_count"),
            fields_of_study=[concept.get("display_name") for concept in row.get("concepts", []) if concept.get("display_name")],
        )
        papers.append(item)
    return papers[:limit]


def _openalex_abstract(index: dict[str, list[int]]) -> str:
    words: list[tuple[int, str]] = []
    for word, positions in (index or {}).items():
        for position in positions or []:
            words.append((int(position), word))
    return " ".join(word for _, word in sorted(words))


def search_crossref(keywords: list[str], limit: int, days: int, fetcher: Fetcher = _request_json) -> list[dict[str, Any]]:
    params = {"query.bibliographic": " ".join(normalize_keywords(keywords)), "rows": min(limit, SOURCE_LIMIT)}
    cutoff = _date_cutoff(days)
    if cutoff:
        params["filter"] = f"from-pub-date:{cutoff}"
    data = fetcher("https://api.crossref.org/works?" + urlencode(params))
    papers = []
    for row in (data or {}).get("message", {}).get("items", []):
        links = row.get("link") or []
        pdf = next((link.get("URL", "") for link in links if "pdf" in str(link.get("content-type", "")).lower()), "")
        date_parts = ((row.get("published-print") or row.get("published-online") or row.get("issued") or {}).get("date-parts") or [[]])[0]
        authors = [{"given": a.get("given", ""), "family": a.get("family", "")} for a in row.get("author", [])]
        item = _paper(
            source="crossref",
            title=(row.get("title") or [""])[0],
            authors=authors,
            published=date_parts,
            doi=row.get("DOI", ""),
            venue=(row.get("container-title") or [""])[0],
            landing_url=row.get("URL", ""),
            pdf_url=pdf,
            # Crossref links may still require institutional authorization.
            open_access=None,
        )
        papers.append(item)
    return papers[:limit]


def search_semantic_scholar(keywords: list[str], limit: int, days: int, fetcher: Fetcher = _request_json) -> list[dict[str, Any]]:
    params = {
        "query": " ".join(normalize_keywords(keywords)),
        "limit": min(limit, 100),
        "fields": "title,authors,abstract,year,publicationDate,venue,externalIds,openAccessPdf,url,citationCount,fieldsOfStudy",
    }
    data = fetcher("https://api.semanticscholar.org/graph/v1/paper/search?" + urlencode(params))
    cutoff = _date_cutoff(days)
    papers = []
    for row in (data or {}).get("data", []):
        published = _date_value(row.get("publicationDate") or (str(row.get("year")) if row.get("year") else ""))
        if cutoff and published and published < cutoff:
            continue
        external = row.get("externalIds") or {}
        oa = row.get("openAccessPdf") or {}
        papers.append(_paper(
            source="semantic_scholar",
            title=row.get("title", ""),
            authors=row.get("authors", []),
            abstract=row.get("abstract", ""),
            published=published,
            doi=external.get("DOI", ""),
            arxiv_id=external.get("ArXiv", ""),
            venue=row.get("venue", ""),
            landing_url=row.get("url", ""),
            pdf_url=oa.get("url", ""),
            open_access=bool(oa.get("url")),
            citations=row.get("citationCount"),
            fields_of_study=row.get("fieldsOfStudy", []),
        ))
    return papers[:limit]


def search_europe_pmc(keywords: list[str], limit: int, days: int, fetcher: Fetcher = _request_json) -> list[dict[str, Any]]:
    query = " AND ".join(f'"{term}"' if " " in term else term for term in normalize_keywords(keywords)) or "*"
    params = {"query": query, "format": "json", "pageSize": min(limit, 100), "resultType": "core"}
    data = fetcher("https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urlencode(params))
    cutoff = _date_cutoff(days)
    papers = []
    for row in (data or {}).get("resultList", {}).get("result", []):
        published = _date_value(row.get("firstPublicationDate") or str(row.get("pubYear") or ""))
        if cutoff and published and published < cutoff:
            continue
        full_text_urls = ((row.get("fullTextUrlList") or {}).get("fullTextUrl") or [])
        pdf = next((entry.get("url", "") for entry in full_text_urls if str(entry.get("documentStyle", "")).lower() == "pdf"), "")
        doi = row.get("doi", "")
        landing = f"https://europepmc.org/article/MED/{row.get('pmid')}" if row.get("pmid") else ""
        papers.append(_paper(
            source="europe_pmc",
            title=row.get("title", ""),
            authors=re.split(r",\s*", row.get("authorString", "")) if row.get("authorString") else [],
            abstract=row.get("abstractText", ""),
            published=published,
            doi=doi,
            pmid=row.get("pmid", ""),
            venue=row.get("journalTitle", ""),
            landing_url=landing,
            pdf_url=pdf,
            open_access=bool(row.get("isOpenAccess") or pdf),
            citations=row.get("citedByCount"),
        ))
    return papers[:limit]


SOURCE_SEARCHERS = {
    "arxiv": search_arxiv,
    "openalex": search_openalex,
    "crossref": search_crossref,
    "semantic_scholar": search_semantic_scholar,
    "europe_pmc": search_europe_pmc,
}


def _merge_paper(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    for field in ("doi", "pmid", "openalex_id", "venue", "published", "abstract_full", "landing_url", "pdf_url"):
        if not target.get(field) and incoming.get(field):
            target[field] = incoming[field]
    if incoming.get("open_access"):
        target["open_access"] = True
        target["is_open_access"] = True
    if incoming.get("pdf_url") and not target.get("pdf_url"):
        target["pdf_url"] = incoming["pdf_url"]
    target["sources"] = list(dict.fromkeys(target.get("sources", []) + incoming.get("sources", [])))
    target["source_ids"].update(incoming.get("source_ids", {}))
    target["categories"] = list(dict.fromkeys(target.get("categories", []) + incoming.get("categories", [])))
    target["fields_of_study"] = list(dict.fromkeys(target.get("fields_of_study", []) + incoming.get("fields_of_study", [])))
    if not target.get("abs_url") and incoming.get("abs_url"):
        target["abs_url"] = incoming["abs_url"]


def deduplicate_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for paper in papers:
        key = (
            f"doi:{_doi(paper.get('doi'))}" if paper.get("doi") else ""
        ) or (
            f"arxiv:{str(paper.get('arxiv_id')).split('v', 1)[0]}" if paper.get("arxiv_id") and not str(paper.get("arxiv_id")).startswith(("doi:", "pmid:", "openalex:", "title:")) else ""
        ) or (f"pmid:{paper.get('pmid')}" if paper.get("pmid") else "") or (
            f"openalex:{str(paper.get('openalex_id')).rsplit('/', 1)[-1]}" if paper.get("openalex_id") else ""
        ) or f"title:{_title_key(paper.get('title', ''))}"
        if key not in index:
            index[key] = paper
            order.append(key)
        else:
            _merge_paper(index[key], paper)
    return [index[key] for key in order]


def search_all_sources(
    keywords: list[str] | str,
    sources: list[str] | None = None,
    max_results: int = 25,
    days: int = 0,
    fetcher: Fetcher = _request_json,
) -> dict[str, Any]:
    requested = sources or list(DEFAULT_SOURCES)
    normalized_sources = []
    for source in requested:
        source = str(source).strip().lower()
        if source in SOURCE_SEARCHERS and source not in normalized_sources:
            normalized_sources.append(source)
    if not normalized_sources:
        normalized_sources = ["arxiv"]
    terms = normalize_keywords(keywords)
    all_papers: list[dict[str, Any]] = []
    source_errors: dict[str, str] = {}
    source_counts: dict[str, int] = {}
    total_limit = max(1, min(int(max_results), SOURCE_LIMIT))
    # Collect a balanced candidate pool so the first source cannot fill the
    # whole result window before other disciplines/sources are considered.
    per_source_limit = min(
        SOURCE_LIMIT,
        max(5, math.ceil(total_limit / len(normalized_sources)) * 2),
    )
    for source in normalized_sources:
        try:
            rows = SOURCE_SEARCHERS[source](terms, per_source_limit, days, fetcher=fetcher)
            source_counts[source] = len(rows)
            all_papers.extend(rows)
        except Exception as exc:
            source_errors[source] = str(exc)
            source_counts[source] = 0
    papers = deduplicate_papers(all_papers)
    papers.sort(
        key=lambda paper: (str(paper.get("published") or ""), str(paper.get("title") or "")),
        reverse=True,
    )
    return {
        "papers": papers[:total_limit],
        "sources": normalized_sources,
        "source_counts": source_counts,
        "source_errors": source_errors,
        "failed_sources": sorted(source_errors),
        "keywords": terms,
    }


def _read_crawled(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Search configurable public paper sources")
    parser.add_argument("--keywords", default="")
    parser.add_argument("--sources", default=",".join(DEFAULT_SOURCES))
    parser.add_argument("--days", type=int, default=0)
    parser.add_argument("--max-results", type=int, default=25)
    parser.add_argument("--output", default=str(OUTPUT_JSON))
    args = parser.parse_args(argv)
    output_path = Path(args.output).expanduser()
    if not output_path.is_absolute():
        output_path = (Path.cwd() / output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = search_all_sources(
        args.keywords,
        sources=normalize_keywords(args.sources),
        max_results=max(1, min(args.max_results, SOURCE_LIMIT)),
        days=max(0, args.days),
    )
    status_path = output_path.parent / "run_status.json"
    if result["source_errors"] and len(result["source_errors"]) == len(result["sources"]):
        error = "All configured paper sources failed"
        try:
            write_json_atomic(status_path, {
                "status": "error",
                "error": error,
                "sources": result["sources"],
                "source_errors": result["source_errors"],
                "output_file": str(output_path),
            })
        except Exception:
            pass
        print(f"SOURCE_ERROR: {error}: {result['source_errors']}", file=sys.stderr)
        return 1
    crawled = _read_crawled(output_path.parent / "crawled_ids.txt")
    new_papers = [paper for paper in result["papers"] if paper.get("arxiv_id") not in crawled]
    payload = {
        "searched_at": datetime.now(timezone.utc).isoformat(),
        "sources": result["sources"],
        "source_counts": result["source_counts"],
        "source_errors": result["source_errors"],
        "failed_sources": result["failed_sources"],
        "keywords": result["keywords"],
        "total_count": len(result["papers"]),
        "new_count": len(new_papers),
        "new_papers": new_papers,
        "all_papers": result["papers"],
    }
    try:
        write_json_atomic(output_path, payload)
        write_json_atomic(status_path, {"status": "ok", **{k: payload[k] for k in ("searched_at", "sources", "failed_sources", "source_errors", "total_count", "new_count")}, "output_file": str(output_path)})
    except Exception as exc:
        try:
            write_json_atomic(status_path, {"status": "error", "error": str(exc), "output_file": str(output_path)})
        except Exception:
            pass
        print(f"OUTPUT_ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"[SUMMARY] {len(result['papers'])} papers ({len(new_papers)} new)", file=sys.stderr)
    if result["failed_sources"]:
        print(f"[WARN] failed sources: {', '.join(result['failed_sources'])}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
