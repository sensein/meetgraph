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
    graph_store_url: str = ""  # SPARQL Graph Store Protocol endpoint (HTTP PUT)
    update_url: str = ""       # SPARQL Update endpoint (fallback if no graph store)
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
    "user": "ext.graph.user", "password": "ext.graph.password",
}


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
        user=get_setting(_GRAPH_KEYS["user"]) or "",
        password=get_setting(_GRAPH_KEYS["password"]) or "",
    )
    return ExternalConfig(relational=rel, graph=g)


# --------------------------------------------------------------------------- #
# Relational sink (SQLAlchemy)
# --------------------------------------------------------------------------- #
_MEETING_COLS = [
    "id", "user", "title", "started_at", "ended_at",
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
        from sqlalchemy import (BigInteger, Column, MetaData, Table, Text)

        self._meta = MetaData()
        self._table = Table(
            "meetgraph_meetings", self._meta,
            Column("id", BigInteger, primary_key=True),
            Column("user", Text), Column("title", Text),
            Column("started_at", Text), Column("ended_at", Text),
            Column("transcript_md", Text), Column("transcript_plain", Text),
            Column("summary_md", Text), Column("summary_json", Text),
            Column("created_at", Text),
        )
        self._meta.create_all(self._engine)

    def upsert(self, rec: dict) -> None:
        from sqlalchemy import delete, insert

        row = {c: rec.get(c) for c in _MEETING_COLS}
        with self._engine.begin() as conn:
            conn.execute(delete(self._table).where(self._table.c.id == row["id"]))
            conn.execute(insert(self._table).values(**row))

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

    def push_meeting(self, rec: dict, summary: dict, prev_ids=None) -> None:
        """Replace this meeting's named graph with freshly-built RDF."""
        graph_iri = kg.meeting_iri(rec.get("id"))
        if self.cfg.graph_store_url:
            # Graph Store Protocol: PUT replaces the whole named graph.
            body = kg.serialize_meeting(rec, summary, prev_ids, fmt="turtle")
            sep = "&" if "?" in self.cfg.graph_store_url else "?"
            url = f"{self.cfg.graph_store_url}{sep}graph={urllib.parse.quote(graph_iri)}"
            self._request(url, body, "text/turtle", "PUT")
        elif self.cfg.update_url:
            triples = kg.serialize_meeting(rec, summary, prev_ids, fmt="nt").decode("utf-8")
            update = (
                f"DROP SILENT GRAPH <{graph_iri}> ;\n"
                f"INSERT DATA {{ GRAPH <{graph_iri}> {{\n{triples}\n}} }}"
            )
            self._request(self.cfg.update_url, update.encode("utf-8"),
                          "application/sparql-update", "POST")
        else:
            raise RuntimeError("Configure a Graph Store or Update URL to push RDF.")

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
            GraphSink(cfg.graph).push_meeting(rec, summary, prev_ids)
            results["graph"] = "ok"
        except Exception as exc:
            results["graph"] = f"{type(exc).__name__}: {exc}"

    return results
