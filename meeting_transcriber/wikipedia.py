"""Resolve key terms to *verified* Wikipedia articles and Wikidata entities.

Given a term the meeting actually mentioned (a concept, technology, person,
organisation…), we look it up against the live Wikipedia API and return the
canonical article URL plus the corresponding Wikidata entity. Links are only
returned when a real page is found — we never fabricate a URL — so the notes
can hyperlink terms without risking dead or wrong links.

Dependency-free (stdlib ``urllib``). Results are cached in-process, and a small
thread pool keeps a batch of look-ups fast. On any network failure the term is
simply returned without links (it stays plain text in the notes).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

_API = "https://en.wikipedia.org/w/api.php"
_UA = "MeetGraph/0.1 (https://tekrajchhetri.com; meeting knowledge-graph app)"
_WIKIDATA_ENTITY = "http://www.wikidata.org/entity/"

# term (lowercased) -> resolved TermLink | None  (None = looked up, not found)
_CACHE: dict[str, "TermLink | None"] = {}


@dataclass
class TermLink:
    term: str                 # the original term as mentioned
    title: str                # canonical Wikipedia article title
    wikipedia: str            # canonical article URL
    wikidata: str | None      # Wikidata entity URI (http://www.wikidata.org/entity/Qxxx)
    description: str | None    # short extract / gloss, if available


def _get(params: dict) -> dict:
    params = {**params, "format": "json", "formatversion": "2"}
    url = f"{_API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _article_url(title: str) -> str:
    return "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))


def _page_to_link(term: str, page: dict) -> TermLink:
    title = page.get("title") or term
    qid = (page.get("pageprops") or {}).get("wikibase_item")
    extract = (page.get("extract") or "").strip() or None
    return TermLink(
        term=term,
        title=title,
        wikipedia=_article_url(title),
        wikidata=(_WIKIDATA_ENTITY + qid) if qid else None,
        description=extract,
    )


def _resolve_one(term: str) -> TermLink | None:
    term = (term or "").strip()
    if not term:
        return None
    key = term.lower()
    if key in _CACHE:
        return _CACHE[key]

    result: TermLink | None = None
    try:
        # 1) Try the term as a title directly (follows redirects).
        data = _get({
            "action": "query", "titles": term, "redirects": "1",
            "prop": "extracts|pageprops", "ppprop": "wikibase_item",
            "exintro": "1", "explaintext": "1", "exsentences": "1",
        })
        pages = (data.get("query") or {}).get("pages") or []
        page = pages[0] if pages else None
        if page and not page.get("missing"):
            result = _page_to_link(term, page)
        else:
            # 2) Fall back to a search, then fetch that page for the wikidata id.
            sdata = _get({"action": "query", "list": "search", "srsearch": term, "srlimit": "1"})
            hits = (sdata.get("query") or {}).get("search") or []
            if hits:
                found = hits[0]["title"]
                pdata = _get({
                    "action": "query", "titles": found, "redirects": "1",
                    "prop": "extracts|pageprops", "ppprop": "wikibase_item",
                    "exintro": "1", "explaintext": "1", "exsentences": "1",
                })
                ppages = (pdata.get("query") or {}).get("pages") or []
                if ppages and not ppages[0].get("missing"):
                    result = _page_to_link(term, ppages[0])
    except Exception:
        result = None  # network/parse failure -> leave the term unlinked

    # Cache only positive results and confirmed-empty direct misses; transient
    # network failures (also -> None) are cheap to retry later, so don't cache them.
    if result is not None:
        _CACHE[key] = result
    return result


def resolve_terms(terms: list[str], max_terms: int = 30) -> dict[str, TermLink]:
    """Resolve a batch of terms; returns {original_term: TermLink} for hits only."""
    uniq: list[str] = []
    seen: set[str] = set()
    for t in terms:
        t = (t or "").strip()
        k = t.lower()
        if t and k not in seen:
            seen.add(k)
            uniq.append(t)
    uniq = uniq[:max_terms]
    if not uniq:
        return {}

    out: dict[str, TermLink] = {}
    with ThreadPoolExecutor(max_workers=min(6, len(uniq))) as pool:
        for term, link in zip(uniq, pool.map(_resolve_one, uniq)):
            if link is not None:
                out[term] = link
    return out
