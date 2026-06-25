"""Optional sync of meeting content to *external* databases.

Two independent, optional sinks the user configures in the app:

* :class:`RelationalSink` — any SQL database reachable by a SQLAlchemy URL
  (PostgreSQL, MySQL/MariaDB, SQLite, …). Mirrors each meeting row into a
  ``meetgraph_meetings`` table. Requires ``sqlalchemy`` (+ the DB driver).

* :class:`GraphSink` — any SPARQL 1.1 endpoint / triplestore (Oxigraph server,
  Apache Jena Fuseki, GraphDB, Blazegraph, …). Pushes each meeting's RDF as a
  named graph via the Graph Store Protocol (HTTP PUT) or SPARQL Update.
  Stdlib-only.

Both are best-effort: a sink that isn't configured or can't connect simply
reports an error string; it never raises into the UI/recording path.
"""

from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from . import kg

# --------------------------------------------------------------------------- #
# Config (loaded from / saved to the settings DB by the UI)
# --------------------------------------------------------------------------- #
@dataclass
class RelationalConfig:
    enabled: bool = False
    url: str = ""        # e.g. postgresql+psycopg://host:5432/dbname
    user: str = ""       # optional — injected into the URL if set
    password: str = ""   # optional — password or access token


@dataclass
class GraphConfig:
    enabled: bool = False
    query_url: str = ""        # SPARQL query endpoint (for connection test)
    graph_store_url: str = ""  # SPARQL Graph Store Protocol endpoint (HTTP PUT/POST/DELETE)
    update_url: str = ""       # SPARQL Update endpoint (preferred — enables incremental replace)
    named_graph: str = kg.MEETGRAPH_NG  # all meetings live in this one "meetgraph" named graph
    user: str = ""
    password: str = ""


@dataclass
class ExternalConfig:
    relational: RelationalConfig = field(default_factory=RelationalConfig)
    graph: GraphConfig = field(default_factory=GraphConfig)


_REL_KEYS = {
    "enabled": "ext.rel.enabled", "url": "ext.rel.url",
    "user": "ext.rel.user", "password": "ext.rel.password",
}
_GRAPH_KEYS = {
    "enabled": "ext.graph.enabled", "query_url": "ext.graph.query_url",
    "graph_store_url": "ext.graph.graph_store_url", "update_url": "ext.graph.update_url",
    "named_graph": "ext.graph.named_graph",
    "user": "ext.graph.user", "password": "ext.graph.password",
}


def save_config(set_setting, cfg: ExternalConfig) -> None:
    """Persist an ExternalConfig into the settings store (inverse of load_config)."""
    r, g = cfg.relational, cfg.graph
    set_setting(_REL_KEYS["enabled"], "1" if r.enabled else "0")
    set_setting(_REL_KEYS["url"], r.url)
    set_setting(_REL_KEYS["user"], r.user)
    set_setting(_REL_KEYS["password"], r.password)
    set_setting(_GRAPH_KEYS["enabled"], "1" if g.enabled else "0")
    set_setting(_GRAPH_KEYS["query_url"], g.query_url)
    set_setting(_GRAPH_KEYS["graph_store_url"], g.graph_store_url)
    set_setting(_GRAPH_KEYS["update_url"], g.update_url)
    set_setting(_GRAPH_KEYS["named_graph"], g.named_graph)
    set_setting(_GRAPH_KEYS["user"], g.user)
    set_setting(_GRAPH_KEYS["password"], g.password)


def load_config(get_setting) -> ExternalConfig:
    def b(v):
        return (v or "0") == "1"
    rel = RelationalConfig(
        enabled=b(get_setting(_REL_KEYS["enabled"])),
        url=get_setting(_REL_KEYS["url"]) or "",
        user=get_setting(_REL_KEYS["user"]) or "",
        password=get_setting(_REL_KEYS["password"]) or "",
    )
    g = GraphConfig(
        enabled=b(get_setting(_GRAPH_KEYS["enabled"])),
        query_url=get_setting(_GRAPH_KEYS["query_url"]) or "",
        graph_store_url=get_setting(_GRAPH_KEYS["graph_store_url"]) or "",
        update_url=get_setting(_GRAPH_KEYS["update_url"]) or "",
        named_graph=get_setting(_GRAPH_KEYS["named_graph"]) or kg.MEETGRAPH_NG,
        user=get_setting(_GRAPH_KEYS["user"]) or "",
        password=get_setting(_GRAPH_KEYS["password"]) or "",
    )
    return ExternalConfig(relational=rel, graph=g)


# --------------------------------------------------------------------------- #
# Relational sink (SQLAlchemy)
# --------------------------------------------------------------------------- #
_MEETING_COLS = [
    "id", "user", "title", "team_id", "started_at", "ended_at",
    "transcript_md", "transcript_plain", "summary_md", "summary_json", "created_at",
]


class RelationalSink:
    def __init__(self, url: str, user: str = "", password: str = ""):
        if not url.strip():
            raise ValueError("No database URL configured.")
        try:
            from sqlalchemy import create_engine
            from sqlalchemy.engine import make_url
        except ImportError as exc:  # pragma: no cover - dependency hint
            raise RuntimeError(
                "SQLAlchemy is required for relational export. "
                "Install it with: pip install sqlalchemy (plus your DB driver, "
                "e.g. psycopg2-binary for PostgreSQL or pymysql for MySQL)."
            ) from exc
        # Inject separately-entered credentials/token into the URL when present
        # (a user/password embedded directly in the URL still works on its own).
        u = make_url(url)
        if user:
            u = u.set(username=user)
        if password:
            u = u.set(password=password)
        self._engine = create_engine(u, pool_pre_ping=True)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """A normalized 'meetgraph' schema: one parent table + relevant child tables."""
        from sqlalchemy import (BigInteger, Column, Integer, MetaData, Table, Text)

        self._meta = MetaData()
        fk = lambda: Column("meeting_id", BigInteger, index=True)  # noqa: E731
        pk = lambda: Column("id", Integer, primary_key=True, autoincrement=True)  # noqa: E731
        self._t = {
            "meetings": Table(
                "meetgraph_meetings", self._meta,
                Column("id", BigInteger, primary_key=True),
                Column("user", Text), Column("title", Text),
                Column("team_id", Text, index=True),
                Column("started_at", Text), Column("ended_at", Text),
                Column("purpose", Text),
                Column("transcript_md", Text), Column("transcript_plain", Text),
                Column("summary_md", Text), Column("summary_json", Text),
                Column("created_at", Text),
            ),
            "meeting_links": Table(
                "meetgraph_meeting_links", self._meta, pk(), fk(),
                Column("related_id", BigInteger), Column("relation", Text), Column("reason", Text),
            ),
            "audit_log": Table(
                "meetgraph_audit_log", self._meta, pk(),
                Column("ts", Text), Column("team_id", Text, index=True),
                Column("actor_name", Text), Column("actor_email", Text),
                Column("action", Text), Column("target_id", BigInteger), Column("detail", Text),
            ),
            "participants": Table(
                "meetgraph_participants", self._meta, pk(), fk(), Column("name", Text),
            ),
            "topics": Table(
                "meetgraph_topics", self._meta, pk(), fk(),
                Column("ord", Integer), Column("topic", Text),
                Column("attribution", Text), Column("points", Text),
            ),
            "decisions": Table(
                "meetgraph_decisions", self._meta, pk(), fk(),
                Column("ord", Integer), Column("text", Text),
            ),
            "open_questions": Table(
                "meetgraph_open_questions", self._meta, pk(), fk(),
                Column("ord", Integer), Column("text", Text),
            ),
            "action_items": Table(
                "meetgraph_action_items", self._meta, pk(), fk(),
                Column("ord", Integer), Column("item", Text),
                Column("owner", Text), Column("due", Text),
            ),
            "key_terms": Table(
                "meetgraph_key_terms", self._meta, pk(), fk(),
                Column("term", Text), Column("description", Text),
                Column("wikipedia", Text), Column("wikidata", Text),
            ),
        }
        self._meta.create_all(self._engine)

    def upsert(self, rec: dict) -> None:
        import json as _json

        from sqlalchemy import delete, insert

        mid = rec.get("id")
        try:
            summary = _json.loads(rec.get("summary_json") or "") if rec.get("summary_json") else {}
        except Exception:
            summary = {}
        meeting = summary.get("meeting") or {}

        parent = {c: rec.get(c) for c in _MEETING_COLS}
        parent["purpose"] = meeting.get("purpose")

        participants = [{"meeting_id": mid, "name": n} for n in (meeting.get("participants") or [])]
        topics = [
            {"meeting_id": mid, "ord": i, "topic": t.get("topic"),
             "attribution": t.get("attribution"), "points": _json.dumps(t.get("points") or [])}
            for i, t in enumerate(summary.get("topics") or [])
        ]
        decisions = [{"meeting_id": mid, "ord": i, "text": d}
                     for i, d in enumerate(summary.get("decisions") or [])]
        questions = [{"meeting_id": mid, "ord": i, "text": q}
                     for i, q in enumerate(summary.get("open_questions") or [])]
        actions = [
            {"meeting_id": mid, "ord": i, "item": a.get("item"),
             "owner": a.get("owner"), "due": a.get("due")}
            for i, a in enumerate(summary.get("action_items") or [])
        ]
        terms = [
            {"meeting_id": mid, "term": k.get("term"), "description": k.get("description"),
             "wikipedia": k.get("wikipedia"), "wikidata": k.get("wikidata")}
            for k in (summary.get("key_terms") or [])
        ]
        link_rows = [
            {"meeting_id": mid, "related_id": l.get("related_id"),
             "relation": l.get("relation"), "reason": l.get("reason")}
            for l in (rec.get("links") or [])
        ]

        t = self._t
        with self._engine.begin() as conn:
            for name in ("participants", "topics", "decisions", "open_questions",
                         "action_items", "key_terms", "meeting_links"):
                conn.execute(delete(t[name]).where(t[name].c.meeting_id == mid))
            conn.execute(delete(t["meetings"]).where(t["meetings"].c.id == mid))
            conn.execute(insert(t["meetings"]).values(**parent))
            for name, rows in (("participants", participants), ("topics", topics),
                               ("decisions", decisions), ("open_questions", questions),
                               ("action_items", actions), ("key_terms", terms),
                               ("meeting_links", link_rows)):
                if rows:
                    conn.execute(insert(t[name]), rows)

    def append_audit(self, entry: dict) -> None:
        from sqlalchemy import insert

        row = {c: entry.get(c) for c in
               ("ts", "team_id", "actor_name", "actor_email", "action", "target_id", "detail")}
        with self._engine.begin() as conn:
            conn.execute(insert(self._t["audit_log"]).values(**row))

    def test(self) -> str:
        from sqlalchemy import text

        with self._engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return f"Connected to {self._engine.url.render_as_string(hide_password=True)}"


# --------------------------------------------------------------------------- #
# Graph sink (SPARQL 1.1)
# --------------------------------------------------------------------------- #
class GraphSink:
    def __init__(self, cfg: GraphConfig):
        if not (cfg.graph_store_url or cfg.update_url or cfg.query_url):
            raise ValueError("No SPARQL endpoint configured.")
        self.cfg = cfg

    def _auth_header(self) -> dict:
        if self.cfg.user:
            token = base64.b64encode(f"{self.cfg.user}:{self.cfg.password}".encode()).decode()
            return {"Authorization": f"Basic {token}"}
        return {}

    def _request(self, url: str, data: bytes | None, content_type: str | None, method: str) -> str:
        headers = self._auth_header()
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read().decode("utf-8", "replace")

    @property
    def named_graph(self) -> str:
        return self.cfg.named_graph or kg.MEETGRAPH_NG

    def _gsp_url(self) -> str:
        sep = "&" if "?" in self.cfg.graph_store_url else "?"
        return f"{self.cfg.graph_store_url}{sep}graph={urllib.parse.quote(self.named_graph)}"

    def push_meeting(self, rec: dict, summary: dict, prev_ids=None, links=None) -> None:
        """Upsert one meeting into the single 'meetgraph' named graph.

        With a SPARQL Update endpoint (preferred) we delete just this meeting's
        triples and re-insert them, so re-syncing is clean. With only a Graph
        Store endpoint we POST (merge) the triples — additive, so use
        ``replace_all`` for a full clean re-sync.
        """
        ng = self.named_graph
        meeting_iri = kg.meeting_iri(rec.get("id"))
        triples = kg.serialize_meeting(rec, summary, prev_ids, fmt="nt", links=links).decode("utf-8")
        if self.cfg.update_url:
            update = (
                # Drop this meeting + all its sub-resources (topic/term/… IRIs)
                f"DELETE {{ GRAPH <{ng}> {{ ?s ?p ?o }} }} WHERE {{ GRAPH <{ng}> {{ ?s ?p ?o . "
                f'FILTER(?s = <{meeting_iri}> || STRSTARTS(STR(?s), "{meeting_iri}/")) }} }} ;\n'
                f"INSERT DATA {{ GRAPH <{ng}> {{\n{triples}\n}} }}"
            )
            self._request(self.cfg.update_url, update.encode("utf-8"),
                          "application/sparql-update", "POST")
        elif self.cfg.graph_store_url:
            self._request(self._gsp_url(), triples.encode("utf-8"),
                          "application/n-triples", "POST")  # merge into the graph
        else:
            raise RuntimeError("Configure a Graph Store or Update URL to push RDF.")

    def clear_graph(self) -> None:
        """Empty the 'meetgraph' named graph (used before a full re-sync)."""
        ng = self.named_graph
        if self.cfg.update_url:
            self._request(self.cfg.update_url, f"CLEAR SILENT GRAPH <{ng}>".encode(),
                          "application/sparql-update", "POST")
        elif self.cfg.graph_store_url:
            try:
                self._request(self._gsp_url(), None, None, "DELETE")
            except Exception:
                pass  # 404 if the graph doesn't exist yet — fine

    def replace_all(self, records: list[dict]) -> None:
        """Replace the whole 'meetgraph' graph with the full corpus (clean re-sync).

        Prefer SPARQL Update (CLEAR + INSERT) when an Update endpoint is set — it
        targets the named graph directly. The Graph Store PUT is used only when
        no Update URL is configured (and it must point at the store endpoint,
        e.g. Oxigraph's /store, not the server root).
        """
        ng = self.named_graph
        if self.cfg.update_url:
            triples = kg.serialize_corpus(records, fmt="nt").decode("utf-8")
            update = (f"CLEAR SILENT GRAPH <{ng}> ;\n"
                      f"INSERT DATA {{ GRAPH <{ng}> {{\n{triples}\n}} }}")
            self._request(self.cfg.update_url, update.encode("utf-8"),
                          "application/sparql-update", "POST")
        elif self.cfg.graph_store_url:
            body = kg.serialize_corpus(records, fmt="turtle")
            self._request(self._gsp_url(), body, "text/turtle", "PUT")  # PUT replaces graph
        else:
            raise RuntimeError("Configure a Graph Store or Update URL to push RDF.")

    def fetch_digests(self) -> list[dict]:
        """Query the shared graph for every meeting's id/title/topics/entities.

        Used for team-wide cross-link candidate discovery. Best-effort: returns
        [] if there's no query endpoint or the query fails.
        """
        if not self.cfg.query_url:
            return []
        ng = self.named_graph
        query = (
            "PREFIX mco: <https://tekrajchhetri.com/mco/> "
            "PREFIX dcterms: <http://purl.org/dc/terms/> "
            "PREFIX skos: <http://www.w3.org/2004/02/skos/core#> "
            "PREFIX owl: <http://www.w3.org/2002/07/owl#> "
            "SELECT ?m ?title "
            '(GROUP_CONCAT(DISTINCT ?topic; separator="||") AS ?topics) '
            '(GROUP_CONCAT(DISTINCT STR(?wd); separator="||") AS ?wds) WHERE { '
            f"GRAPH <{ng}> {{ ?m a mco:Meeting . OPTIONAL {{ ?m dcterms:title ?title }} "
            "OPTIONAL { ?m mco:has_topic ?t . ?t skos:prefLabel ?topic } "
            "OPTIONAL { ?m mco:has_key_term ?k . ?k owl:sameAs ?wd } } } GROUP BY ?m ?title"
        )
        q = urllib.parse.urlencode({"query": query})
        url = f"{self.cfg.query_url}{'&' if '?' in self.cfg.query_url else '?'}{q}"
        headers = {**self._auth_header(), "Accept": "application/sparql-results+json"}
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return []
        out = []
        prefix = kg.BASE + "meeting/"
        for b in data.get("results", {}).get("bindings", []):
            m = b.get("m", {}).get("value", "")
            if not m.startswith(prefix):
                continue
            tail = m[len(prefix):]
            if not tail.isdigit():
                continue
            topics = [s for s in (b.get("topics", {}).get("value", "") or "").split("||") if s]
            wds = [s for s in (b.get("wds", {}).get("value", "") or "").split("||") if s]
            out.append({"id": int(tail), "title": b.get("title", {}).get("value", ""),
                        "topics": topics, "qids": [w.rstrip("/").rsplit("/", 1)[-1] for w in wds]})
        return out

    def test(self) -> str:
        url = self.cfg.query_url or self.cfg.update_url or self.cfg.graph_store_url
        if self.cfg.query_url:
            q = urllib.parse.urlencode({"query": "ASK {}"})
            full = f"{self.cfg.query_url}{'&' if '?' in self.cfg.query_url else '?'}{q}"
            headers = {**self._auth_header(), "Accept": "application/sparql-results+json"}
            req = urllib.request.Request(full, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp.read()
            return f"SPARQL endpoint reachable: {self.cfg.query_url}"
        # No query endpoint to probe — just report what we'll write to.
        return f"Will write RDF to: {url}"


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def push_audit(entry: dict, cfg: ExternalConfig) -> dict[str, str]:
    """Mirror one audit-log entry to the centralized relational DB (keep all logs)."""
    results: dict[str, str] = {}
    if cfg.relational.enabled and cfg.relational.url:
        try:
            RelationalSink(
                cfg.relational.url, cfg.relational.user, cfg.relational.password
            ).append_audit(entry)
            results["relational"] = "ok"
        except Exception as exc:
            results["relational"] = f"{type(exc).__name__}: {exc}"
    return results


def push_meeting(rec: dict, cfg: ExternalConfig, prev_ids=None) -> dict[str, str]:
    """Push one meeting to every enabled sink. Returns {sink: 'ok' | error}."""
    results: dict[str, str] = {}
    try:
        summary = json.loads(rec.get("summary_json") or "") if rec.get("summary_json") else {}
    except Exception:
        summary = {}

    if cfg.relational.enabled and cfg.relational.url:
        try:
            RelationalSink(
                cfg.relational.url, cfg.relational.user, cfg.relational.password
            ).upsert(rec)
            results["relational"] = "ok"
        except Exception as exc:
            results["relational"] = f"{type(exc).__name__}: {exc}"

    if cfg.graph.enabled and (cfg.graph.graph_store_url or cfg.graph.update_url):
        try:
            GraphSink(cfg.graph).push_meeting(rec, summary, prev_ids, links=rec.get("links"))
            results["graph"] = "ok"
        except Exception as exc:
            results["graph"] = f"{type(exc).__name__}: {exc}"

    return results
