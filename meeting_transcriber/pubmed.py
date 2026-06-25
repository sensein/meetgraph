"""PubMed lookup via NCBI E-utilities (stdlib).

Given the scientific key terms of a meeting, search PubMed for relevant
publications and return lightweight citations (title, journal, year, authors,
DOI, PubMed URL). An optional NCBI API key raises the rate limit.

Dependency-free (urllib). Network/parse failures return an empty list.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_UA = "MeetGraph/0.1 (https://tekrajchhetri.com; meeting knowledge-graph app)"


@dataclass
class Article:
    pmid: str
    title: str
    journal: str
    year: str
    authors: str       # short author string ("Smith J, Doe A, et al.")
    doi: str | None
    url: str           # canonical PubMed URL

    def to_dict(self) -> dict:
        return {"pmid": self.pmid, "title": self.title, "journal": self.journal,
                "year": self.year, "authors": self.authors, "doi": self.doi, "url": self.url}


def _get(path: str, params: dict) -> dict:
    params = {**params, "retmode": "json", "tool": "meetgraph"}
    url = f"{_EUTILS}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=12) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_query(terms: list[str]) -> str:
    """Build a PubMed query that OR-combines the key terms (quoted)."""
    parts = [f'"{t.strip()}"' for t in terms if t and t.strip()]
    return " OR ".join(parts)


def _authors(doc: dict) -> str:
    names = [a.get("name", "") for a in (doc.get("authors") or []) if a.get("name")]
    if not names:
        return ""
    return ", ".join(names[:3]) + (", et al." if len(names) > 3 else "")


def _doi(doc: dict) -> str | None:
    for aid in (doc.get("articleids") or []):
        if aid.get("idtype") == "doi" and aid.get("value"):
            return aid["value"]
    el = doc.get("elocationid", "")
    return el.replace("doi:", "").strip() if el.lower().startswith("doi:") else None


def fetch_abstracts(pmids: list[str], api_key: str | None = None) -> dict[str, str]:
    """Return {pmid: abstract text} for the given PMIDs (best-effort, may be empty)."""
    import xml.etree.ElementTree as ET

    pmids = [p for p in pmids if p]
    if not pmids:
        return {}
    params = {"db": "pubmed", "id": ",".join(pmids), "rettype": "abstract",
              "retmode": "xml", "tool": "meetgraph"}
    if api_key:
        params["api_key"] = api_key
    url = f"{_EUTILS}/efetch.fcgi?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            root = ET.fromstring(resp.read())
    except Exception:
        return {}
    out: dict[str, str] = {}
    for art in root.iter("PubmedArticle"):
        pmid_el = art.find(".//MedlineCitation/PMID")
        if pmid_el is None or not pmid_el.text:
            continue
        texts = [(e.text or "").strip() for e in art.iter("AbstractText")]
        abstract = " ".join(t for t in texts if t)
        if abstract:
            out[pmid_el.text] = abstract
    return out


def search(query: str, api_key: str | None = None, retmax: int = 8) -> list[Article]:
    """Search PubMed and return up to ``retmax`` articles, ranked by relevance."""
    if not query.strip():
        return []
    key = {"api_key": api_key} if api_key else {}
    try:
        es = _get("esearch.fcgi", {"db": "pubmed", "term": query, "retmax": retmax,
                                   "sort": "relevance", **key})
        ids = (es.get("esearchresult") or {}).get("idlist") or []
        if not ids:
            return []
        summ = _get("esummary.fcgi", {"db": "pubmed", "id": ",".join(ids), **key})
        result = summ.get("result") or {}
    except Exception:
        return []

    out: list[Article] = []
    for pmid in result.get("uids", ids):
        doc = result.get(pmid)
        if not isinstance(doc, dict):
            continue
        out.append(Article(
            pmid=pmid,
            title=(doc.get("title") or "").strip().rstrip("."),
            journal=doc.get("fulljournalname") or doc.get("source") or "",
            year=(doc.get("pubdate") or "")[:4],
            authors=_authors(doc),
            doi=_doi(doc),
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        ))
    return out
