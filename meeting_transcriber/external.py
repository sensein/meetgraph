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
import hashlib
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from . import kg

# --------------------------------------------------------------------------- #
# Global meeting ids — so a shared database doesn't collide across team members.
#
# Each install uses its own local autoincrement ids (1, 2, 3, …), so two members
# would both push a meeting "#1" and clobber each other in the shared store. We
# derive a stable, globally-unique id from (per-install node id, local id) before
# pushing. Global ids live in a high range so the mapping is idempotent: a value
# that is already global (e.g. a remote cross-link reference) passes through
# unchanged.
# --------------------------------------------------------------------------- #
_GID_BASE = 1 << 52  # global ids are >= this; local autoincrement ids stay small


def global_id(node: str, local_id) -> int | None:
    """Map a local meeting id to a stable global id for the shared store.

    Idempotent: ids already in the global range are returned unchanged, so it is
    safe to apply to records whose links mix local and remote references."""
    if local_id is None:
        return None
    lid = int(local_id)
    if lid >= _GID_BASE:
        return lid  # already global (e.g. a reference pulled from a remote store)
    h = hashlib.blake2b(f"{node}:{lid}".encode(), digest_size=6).digest()
    return _GID_BASE + int.from_bytes(h, "big")  # 48-bit offset -> stays < 2**53

# --------------------------------------------------------------------------- #
# Config (loaded from / saved to the settings DB by the UI)
# --------------------------------------------------------------------------- #
@dataclass
class RelationalConfig:
    enabled: bool = False
    kind: str = "sql"    # "sql" (SQLAlchemy) | "mongodb"
    url: str = ""        # SQLAlchemy URL, or a mongodb:// / mongodb+srv:// connection string
    user: str = ""       # optional — injected into the SQL URL if set
    password: str = ""   # optional — password or access token
    database: str = ""   # MongoDB database name (defaults to "meetgraph")


# Triplestore types and how their SPARQL endpoints are laid out, so the user
# only enters a base URL (+ repository/dataset name where applicable).
GRAPH_DB_TYPES = [
    ("oxigraph", "Oxigraph", False),
    ("fuseki", "Apache Jena Fuseki", True),
    ("graphdb", "GraphDB", True),
    ("blazegraph", "Blazegraph", True),
    ("rdf4j", "RDF4J Server", True),
    ("custom", "Other / Custom", False),
]
# "needs_dataset" -> the third element above (repository / dataset / namespace).


def derive_endpoints(db_type: str, base: str, dataset: str = "") -> dict:
    """Return {'query','update','store'} endpoint URLs for a triplestore type."""
    base = (base or "").rstrip("/")
    ds = (dataset or "").strip().strip("/")
    if not base:
        return {"query": "", "update": "", "store": ""}
    if db_type == "oxigraph":
        return {"query": f"{base}/query", "update": f"{base}/update", "store": f"{base}/store"}
    if db_type == "fuseki":
        d = ds or "ds"
        return {"query": f"{base}/{d}/sparql", "update": f"{base}/{d}/update", "store": f"{base}/{d}/data"}
    if db_type in ("graphdb", "rdf4j"):
        repo = ds or "repo"
        r = f"{base}/repositories/{repo}"
        return {"query": r, "update": f"{r}/statements", "store": f"{r}/rdf-graphs/service"}
    if db_type == "blazegraph":
        ns = ds or "kb"
        ep = f"{base}/blazegraph/namespace/{ns}/sparql"
        return {"query": ep, "update": ep, "store": ep}
    return {"query": "", "update": "", "store": ""}  # custom -> manual


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
    "enabled": "ext.rel.enabled", "kind": "ext.rel.kind", "url": "ext.rel.url",
    "user": "ext.rel.user", "password": "ext.rel.password", "database": "ext.rel.database",
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
        kind=get_setting(_REL_KEYS["kind"]) or "sql",
        url=get_setting(_REL_KEYS["url"]) or "",
        user=get_setting(_REL_KEYS["user"]) or "",
        password=get_setting(_REL_KEYS["password"]) or "",
        database=get_setting(_REL_KEYS["database"]) or "",
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
            "revoked_keys": Table(
                "meetgraph_revoked_keys", self._meta,
                Column("key_id", Text, primary_key=True),
                Column("ts", Text), Column("revoked_by", Text),
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

    def delete_meeting(self, meeting_id) -> None:
        from sqlalchemy import delete

        t = self._t
        with self._engine.begin() as conn:
            for name in ("participants", "topics", "decisions", "open_questions",
                         "action_items", "key_terms", "meeting_links"):
                conn.execute(delete(t[name]).where(t[name].c.meeting_id == meeting_id))
            conn.execute(delete(t["meetings"]).where(t["meetings"].c.id == meeting_id))

    def list_meetings(self, team_id: str | None = None, limit: int = 1000) -> list[dict]:
        """List meetings in the shared DB (optionally for one team), newest first."""
        from sqlalchemy import select

        t = self._t["meetings"]
        q = select(t.c.id, t.c.user, t.c.title, t.c.team_id, t.c.started_at,
                   t.c.created_at, t.c.summary_md)
        if team_id:
            q = q.where(t.c.team_id == team_id)
        q = q.order_by(t.c.id.desc()).limit(limit)
        with self._engine.connect() as conn:
            return [dict(r) for r in conn.execute(q).mappings().all()]

    def get_meeting(self, meeting_id) -> dict | None:
        """Full meeting record from the shared DB."""
        from sqlalchemy import select

        t = self._t["meetings"]
        with self._engine.connect() as conn:
            row = conn.execute(select(t).where(t.c.id == meeting_id)).mappings().first()
        return dict(row) if row else None

    def append_audit(self, entry: dict) -> None:
        from sqlalchemy import insert

        row = {c: entry.get(c) for c in
               ("ts", "team_id", "actor_name", "actor_email", "action", "target_id", "detail")}
        with self._engine.begin() as conn:
            conn.execute(insert(self._t["audit_log"]).values(**row))

    def revoke_key(self, key_id: str, revoked_by: str = "", ts: str = "") -> None:
        from sqlalchemy import delete, insert

        t = self._t["revoked_keys"]
        with self._engine.begin() as conn:
            conn.execute(delete(t).where(t.c.key_id == key_id))
            conn.execute(insert(t).values(key_id=key_id, ts=ts, revoked_by=revoked_by))

    def revoked_key_ids(self) -> set:
        from sqlalchemy import select

        t = self._t["revoked_keys"]
        with self._engine.connect() as conn:
            return {r[0] for r in conn.execute(select(t.c.key_id)).all()}

    def test(self) -> str:
        from sqlalchemy import text

        with self._engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return f"Connected to {self._engine.url.render_as_string(hide_password=True)}"


# --------------------------------------------------------------------------- #
# MongoDB sink (document store — Atlas or self-hosted)
# --------------------------------------------------------------------------- #
class MongoSink:
    """Mirror meetings to MongoDB. One document per meeting (summary embedded),
    plus audit_log. Works with MongoDB Atlas (mongodb+srv://) or a local server."""

    def __init__(self, cfg: RelationalConfig):
        if not cfg.url.strip():
            raise ValueError("No MongoDB connection string configured.")
        try:
            from pymongo import MongoClient
        except ImportError as exc:  # pragma: no cover - dependency hint
            raise RuntimeError(
                "MongoDB support needs pymongo. Install it with: pip install pymongo"
            ) from exc
        self._client = MongoClient(cfg.url, serverSelectionTimeoutMS=8000)
        self._db = self._client[cfg.database or "meetgraph"]

    def _doc(self, rec: dict) -> dict:
        import json as _json

        try:
            summary = _json.loads(rec.get("summary_json") or "") if rec.get("summary_json") else {}
        except Exception:
            summary = {}
        return {
            "_id": rec.get("id"), "id": rec.get("id"), "user": rec.get("user"),
            "title": rec.get("title"), "team_id": rec.get("team_id"),
            "started_at": rec.get("started_at"), "ended_at": rec.get("ended_at"),
            "created_at": rec.get("created_at"), "summary_md": rec.get("summary_md"),
            "summary_json": rec.get("summary_json"), "summary": summary,
            "transcript_md": rec.get("transcript_md"), "transcript_plain": rec.get("transcript_plain"),
            "links": rec.get("links") or [],
        }

    def upsert(self, rec: dict) -> None:
        doc = self._doc(rec)
        self._db.meetings.replace_one({"_id": doc["_id"]}, doc, upsert=True)

    def append_audit(self, entry: dict) -> None:
        self._db.audit_log.insert_one(dict(entry))

    def revoke_key(self, key_id: str, revoked_by: str = "", ts: str = "") -> None:
        self._db.revoked_keys.replace_one(
            {"_id": key_id}, {"_id": key_id, "ts": ts, "revoked_by": revoked_by}, upsert=True)

    def revoked_key_ids(self) -> set:
        return {d["_id"] for d in self._db.revoked_keys.find({}, {"_id": 1})}

    def list_meetings(self, team_id: str | None = None, limit: int = 1000) -> list[dict]:
        q = {"team_id": team_id} if team_id else {}
        cur = self._db.meetings.find(
            q, {"id": 1, "user": 1, "title": 1, "team_id": 1, "started_at": 1,
                "created_at": 1, "summary_md": 1}).sort("id", -1).limit(limit)
        return [{"id": d.get("id"), "user": d.get("user"), "title": d.get("title"),
                 "team_id": d.get("team_id"), "started_at": d.get("started_at"),
                 "created_at": d.get("created_at"), "summary_md": d.get("summary_md")} for d in cur]

    def get_meeting(self, meeting_id) -> dict | None:
        d = self._db.meetings.find_one({"_id": meeting_id}) or self._db.meetings.find_one({"id": meeting_id})
        if not d:
            return None
        d.pop("_id", None)
        return d

    def delete_meeting(self, meeting_id) -> None:
        self._db.meetings.delete_one({"_id": meeting_id})

    def test(self) -> str:
        self._client.admin.command("ping")
        return f"Connected to MongoDB (database: {self._db.name})"


def structured_sink(cfg: RelationalConfig):
    """Return the right structured-store sink for the configured kind."""
    if cfg.kind == "mongodb":
        return MongoSink(cfg)
    return RelationalSink(cfg.url, cfg.user, cfg.password)


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

    def delete_meeting(self, meeting_id) -> None:
        """Remove one meeting's triples from the shared named graph."""
        ng = self.named_graph
        m = kg.meeting_iri(meeting_id)
        if self.cfg.update_url:
            upd = (f"DELETE {{ GRAPH <{ng}> {{ ?s ?p ?o }} }} WHERE {{ GRAPH <{ng}> {{ ?s ?p ?o . "
                   f'FILTER(?s = <{m}> || STRSTARTS(STR(?s), "{m}/")) }} }}')
            self._request(self.cfg.update_url, upd.encode("utf-8"),
                          "application/sparql-update", "POST")
        # Graph Store Protocol can't delete a sub-resource set cleanly; needs Update.

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

    def _select(self, query: str) -> list[dict]:
        """Run a SPARQL SELECT and return the result bindings."""
        if not self.cfg.query_url:
            raise RuntimeError("This graph database has no SPARQL query endpoint configured.")
        q = urllib.parse.urlencode({"query": query})
        url = f"{self.cfg.query_url}{'&' if '?' in self.cfg.query_url else '?'}{q}"
        headers = {**self._auth_header(), "Accept": "application/sparql-results+json"}
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("results", {}).get("bindings", [])

    _PREFIXES = (
        "PREFIX mco: <https://tekrajchhetri.com/mco/> "
        "PREFIX dcterms: <http://purl.org/dc/terms/> "
        "PREFIX prov: <http://www.w3.org/ns/prov#> "
        "PREFIX schema: <http://schema.org/> "
        "PREFIX foaf: <http://xmlns.com/foaf/0.1/> "
        "PREFIX skos: <http://www.w3.org/2004/02/skos/core#> "
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
    )

    def list_meetings(self, team_id: str | None = None, limit: int = 1000) -> list[dict]:
        """List the team's meetings from the shared graph (newest first).

        Returns the same row shape as the relational sink so the UI can render
        either source. ``summary_md`` is a marker ('✦' when the meeting has notes)
        — the full notes are reconstructed on demand by :meth:`get_meeting`."""
        ng = self.named_graph
        team_filter = f"?m schema:isPartOf <{kg.team_iri(team_id)}> . " if team_id else ""
        query = (
            self._PREFIXES +
            "SELECT ?m ?title ?start ?date (COUNT(DISTINCT ?t) AS ?ntopics) "
            '(GROUP_CONCAT(DISTINCT ?pname; separator=", ") AS ?people) WHERE { '
            f"GRAPH <{ng}> {{ ?m a mco:Meeting . {team_filter}"
            "OPTIONAL { ?m dcterms:title ?title } "
            "OPTIONAL { ?m prov:startedAtTime ?start } "
            "OPTIONAL { ?m dcterms:date ?date } "
            "OPTIONAL { ?m mco:has_topic ?t } "
            "OPTIONAL { ?m prov:wasAssociatedWith ?a . ?a foaf:name ?pname } } } "
            f"GROUP BY ?m ?title ?start ?date ORDER BY DESC(?start) LIMIT {int(limit)}"
        )
        rows: list[dict] = []
        prefix = kg.BASE + "meeting/"
        for b in self._select(query):
            m = b.get("m", {}).get("value", "")
            if not m.startswith(prefix):
                continue
            tail = m[len(prefix):]
            rid = int(tail) if tail.isdigit() else tail
            start = b.get("start", {}).get("value", "") or b.get("date", {}).get("value", "")
            ntopics = b.get("ntopics", {}).get("value", "0")
            rows.append({
                "id": rid,
                "title": b.get("title", {}).get("value", "") or "Meeting",
                "user": b.get("people", {}).get("value", ""),
                "started_at": start, "created_at": start,
                "summary_md": "✦" if ntopics not in ("0", "", None) else "",
            })
        return rows

    def get_meeting(self, meeting_id) -> dict | None:
        """Reconstruct a read-only meeting record (notes as Markdown) from the
        shared graph. Transcripts aren't stored in RDF, so only notes come back."""
        ng = self.named_graph
        m_iri = kg.meeting_iri(meeting_id)
        query = (
            self._PREFIXES +
            "SELECT ?title ?start "
            '(GROUP_CONCAT(DISTINCT ?topic; separator="||") AS ?topics) '
            '(GROUP_CONCAT(DISTINCT ?dec; separator="||") AS ?decisions) '
            '(GROUP_CONCAT(DISTINCT ?q; separator="||") AS ?questions) '
            '(GROUP_CONCAT(DISTINCT ?act; separator="||") AS ?actions) '
            '(GROUP_CONCAT(DISTINCT ?term; separator="||") AS ?terms) '
            '(GROUP_CONCAT(DISTINCT ?pname; separator="||") AS ?people) WHERE { '
            f"GRAPH <{ng}> {{ BIND(<{m_iri}> AS ?m) ?m a mco:Meeting . "
            "OPTIONAL { ?m dcterms:title ?title } "
            "OPTIONAL { ?m prov:startedAtTime ?start } "
            "OPTIONAL { ?m mco:has_topic ?t . ?t skos:prefLabel ?topic } "
            "OPTIONAL { ?m mco:has_decision ?d . ?d rdfs:label ?dec } "
            "OPTIONAL { ?m mco:has_open_question ?oq . ?oq rdfs:label ?q } "
            "OPTIONAL { ?m mco:has_action_item ?ai . ?ai rdfs:label ?act } "
            "OPTIONAL { ?m mco:has_key_term ?k . ?k skos:prefLabel ?term } "
            "OPTIONAL { ?m prov:wasAssociatedWith ?ag . ?ag foaf:name ?pname } } } "
            "GROUP BY ?title ?start"
        )
        bindings = self._select(query)
        if not bindings:
            return None
        b = bindings[0]

        def parts(key: str) -> list[str]:
            return [s for s in (b.get(key, {}).get("value", "") or "").split("||") if s]

        title = b.get("title", {}).get("value", "") or f"Meeting {meeting_id}"
        md = [f"# {title}", ""]
        people = parts("people")
        if people:
            md += [f"*Participants: {', '.join(people)}*", ""]
        sections = [
            ("Key points by topic", parts("topics")),
            ("Decisions", parts("decisions")),
            ("Open questions", parts("questions")),
            ("Action items", parts("actions")),
            ("Key terms", parts("terms")),
        ]
        for heading, items in sections:
            if items:
                md.append(f"## {heading}")
                md += [f"- {it}" for it in items]
                md.append("")
        if len(md) <= 2:
            md.append("_No notes found for this meeting in the shared graph._")
        return {
            "id": meeting_id, "title": title,
            "user": ", ".join(people),
            "started_at": b.get("start", {}).get("value", ""),
            "summary_md": "\n".join(md).strip() + "\n",
            "transcript_md": "_Transcript isn't stored in the graph database._",
        }

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
            structured_sink(cfg.relational).append_audit(entry)
            results["relational"] = "ok"
        except Exception as exc:
            results["relational"] = f"{type(exc).__name__}: {exc}"
    return results


def delete_remote(meeting_id, cfg: ExternalConfig) -> dict[str, str]:
    """Propagate a deletion to every enabled external store."""
    results: dict[str, str] = {}
    if cfg.relational.enabled and cfg.relational.url:
        try:
            structured_sink(cfg.relational).delete_meeting(meeting_id)
            results["relational"] = "ok"
        except Exception as exc:
            results["relational"] = f"{type(exc).__name__}: {exc}"
    if cfg.graph.enabled and (cfg.graph.update_url or cfg.graph.graph_store_url):
        try:
            GraphSink(cfg.graph).delete_meeting(meeting_id)
            results["graph"] = "ok"
        except Exception as exc:
            results["graph"] = f"{type(exc).__name__}: {exc}"
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
            structured_sink(cfg.relational).upsert(rec)
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
