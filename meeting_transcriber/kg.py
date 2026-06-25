"""Meeting knowledge graph — RDF storage and export via pyoxigraph.

Turns a structured ``MeetingSummary`` (as stored JSON) into RDF triples that
conform to the Meeting Content Ontology (``skills/schemas/mco.yaml``):

* the meeting, its participants, topics (+ points + attribution), decisions,
  open questions, and action items;
* salient **key terms** linked out to Wikipedia (``rdfs:seeAlso``) and Wikidata
  (``owl:sameAs``);
* links to **previous meetings** in the series via ``prov:wasInformedBy``.

Two surfaces:

* :func:`serialize_meeting` — build an in-memory graph from one stored meeting
  and dump it as JSON-LD / Turtle / N-Quads (used by the export buttons).
* :class:`MeetingGraph` — a persistent on-disk Oxigraph store (one named graph
  per meeting) that accumulates every meeting into a single, SPARQL-queryable
  knowledge graph across sessions.
"""

from __future__ import annotations

import io
import re
import urllib.parse
from typing import Iterable, Iterator

from pyoxigraph import DefaultGraph, Literal, NamedNode, Quad, RdfFormat, Store

# --- namespaces ------------------------------------------------------------ #
MCO = "https://tekrajchhetri.com/mco/"            # ontology terms
BASE = "https://tekrajchhetri.com/meetgraph/"      # instance data
MEETGRAPH_NG = "https://tekrajchhetri.com/meetgraph"  # the "meetgraph" named graph


def team_iri(team_id) -> str:
    return f"{BASE}team/{team_id}"

RDF_TYPE = NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
RDFS_LABEL = NamedNode("http://www.w3.org/2000/01/rdf-schema#label")
RDFS_SEEALSO = NamedNode("http://www.w3.org/2000/01/rdf-schema#seeAlso")
OWL_SAMEAS = NamedNode("http://www.w3.org/2002/07/owl#sameAs")
DCT_TITLE = NamedNode("http://purl.org/dc/terms/title")
DCT_DESCRIPTION = NamedNode("http://purl.org/dc/terms/description")
SKOS_PREFLABEL = NamedNode("http://www.w3.org/2004/02/skos/core#prefLabel")
FOAF_NAME = NamedNode("http://xmlns.com/foaf/0.1/name")
PROV_ATTIME = NamedNode("http://www.w3.org/ns/prov#atTime")
PROV_STARTED = NamedNode("http://www.w3.org/ns/prov#startedAtTime")
PROV_ENDED = NamedNode("http://www.w3.org/ns/prov#endedAtTime")
PROV_GENERATED = NamedNode("http://www.w3.org/ns/prov#generatedAtTime")
DCT_DATE = NamedNode("http://purl.org/dc/terms/date")
PROV_ASSOCIATED = NamedNode("http://www.w3.org/ns/prov#wasAssociatedWith")
PROV_ATTRIBUTED = NamedNode("http://www.w3.org/ns/prov#wasAttributedTo")
PROV_INFORMEDBY = NamedNode("http://www.w3.org/ns/prov#wasInformedBy")
SCHEMA_ISPARTOF = NamedNode("http://schema.org/isPartOf")
SKOS_RELATED = NamedNode("http://www.w3.org/2004/02/skos/core#related")
DCT_RELATION = NamedNode("http://purl.org/dc/terms/relation")
RDFS_COMMENT = NamedNode("http://www.w3.org/2000/01/rdf-schema#comment")
SCHEMA_AGENT = NamedNode("http://schema.org/agent")
ICAL_DUE = NamedNode("http://www.w3.org/2002/12/cal/ical#due")
XSD_DATETIME = NamedNode("http://www.w3.org/2001/XMLSchema#dateTime")
XSD_DATE = NamedNode("http://www.w3.org/2001/XMLSchema#date")

# MCO-local predicates / classes (no canonical reuse in the ontology)
C_MEETING = NamedNode(MCO + "Meeting")
C_TOPIC = NamedNode(MCO + "Topic")
C_DECISION = NamedNode(MCO + "Decision")
C_ACTION = NamedNode(MCO + "ActionItem")
C_QUESTION = NamedNode(MCO + "OpenQuestion")
C_KEYTERM = NamedNode(MCO + "KeyTerm")
C_AGENT = NamedNode(MCO + "Agent")
C_TEAM = NamedNode(MCO + "Team")
P_RELATED_MEETING = NamedNode(MCO + "relatedMeeting")
# Relation type -> RDF predicate for cross-meeting links.
_LINK_PREDICATE = {
    "follow_up": PROV_INFORMEDBY,
    "continues": PROV_INFORMEDBY,
    "depends_on": NamedNode("http://www.w3.org/ns/prov#wasInfluencedBy"),
    "supersedes": NamedNode("http://purl.org/dc/terms/replaces"),
    "related": SKOS_RELATED,
}
P_HAS_TOPIC = NamedNode(MCO + "has_topic")
P_HAS_DECISION = NamedNode(MCO + "has_decision")
P_HAS_ACTION = NamedNode(MCO + "has_action_item")
P_HAS_QUESTION = NamedNode(MCO + "has_open_question")
P_HAS_KEYTERM = NamedNode(MCO + "has_key_term")
P_POINT = NamedNode(MCO + "point")
P_DECISION_TEXT = NamedNode(MCO + "decision_text")
P_ACTION_TEXT = NamedNode(MCO + "action_text")
P_QUESTION_TEXT = NamedNode(MCO + "question_text")

PREFIXES = {
    # Instance IRIs (BASE) are left unprefixed so they render as plain IRIs in
    # Turtle rather than as prefixed names with escaped slashes.
    "mco": MCO,
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "dcterms": "http://purl.org/dc/terms/",
    "prov": "http://www.w3.org/ns/prov#",
    "schema": "http://schema.org/",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "foaf": "http://xmlns.com/foaf/0.1/",
    "ical": "http://www.w3.org/2002/12/cal/ical#",
}

_FORMATS = {
    "jsonld": RdfFormat.JSON_LD,
    "json-ld": RdfFormat.JSON_LD,
    "turtle": RdfFormat.TURTLE,
    "ttl": RdfFormat.TURTLE,
    "nquads": RdfFormat.N_QUADS,
    "nt": RdfFormat.N_TRIPLES,
}

EXTENSIONS = {"jsonld": ".jsonld", "turtle": ".ttl", "nquads": ".nq", "nt": ".nt"}


# --- IRI helpers ----------------------------------------------------------- #
def meeting_iri(meeting_id) -> str:
    return f"{BASE}meeting/{meeting_id}"


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return s or "x"


def _dt_literal(s: str | None) -> Literal | None:
    if not s:
        return None
    s = s.strip()
    if "T" in s:
        return Literal(s, datatype=XSD_DATETIME)
    if len(s) == 10 and s[4] == "-":
        return Literal(s, datatype=XSD_DATE)
    return Literal(s)


# --- triple construction --------------------------------------------------- #
def quads_for_meeting(
    rec: dict,
    summary: dict,
    prev_ids: Iterable[int] | None = None,
    graph=None,
    links: Iterable[dict] | None = None,
) -> Iterator[Quad]:
    """Yield the RDF quads describing one meeting.

    ``rec`` is a storage row (id, user, title, started_at, created_at);
    ``summary`` is the parsed ``MeetingSummary`` JSON; ``prev_ids`` are earlier
    meetings in the series. ``graph`` selects the target named graph (or the
    default graph when ``None``).
    """
    g = graph if graph is not None else DefaultGraph()
    mid = rec.get("id")
    m = NamedNode(meeting_iri(mid))

    def q(s, p, o):
        return Quad(s, p, o, g)

    meeting = summary.get("meeting") or {}
    title = (meeting.get("title") or rec.get("title") or f"Meeting {mid}").strip()

    yield q(m, RDF_TYPE, C_MEETING)
    yield q(m, RDFS_LABEL, Literal(title))
    yield q(m, DCT_TITLE, Literal(title))
    if meeting.get("purpose"):
        yield q(m, DCT_DESCRIPTION, Literal(meeting["purpose"]))
    # Temporal provenance (PROV): a Meeting is a prov:Activity with a start/end;
    # the notes are generated at created_at; the stated calendar date is dcterms:date.
    started = _dt_literal(rec.get("started_at"))
    if started is not None:
        yield q(m, PROV_STARTED, started)
        yield q(m, PROV_ATTIME, started)  # also a single timestamp for simple consumers
    ended = _dt_literal(rec.get("ended_at"))
    if ended is not None:
        yield q(m, PROV_ENDED, ended)
    generated = _dt_literal(rec.get("created_at"))
    if generated is not None:
        yield q(m, PROV_GENERATED, generated)
    if meeting.get("date"):
        yield q(m, DCT_DATE, _dt_literal(meeting["date"]) or Literal(meeting["date"]))

    # Agents (participants + any owner/attribution), minted once per name.
    agents: dict[str, NamedNode] = {}

    def agent_for(name: str | None) -> NamedNode | None:
        if not name or not name.strip():
            return None
        key = name.strip()
        node = agents.get(key.lower())
        if node is None:
            node = NamedNode(f"{meeting_iri(mid)}/agent/{_slug(key)}")
            agents[key.lower()] = node
        return node

    for name in meeting.get("participants") or []:
        a = agent_for(name)
        if a is not None:
            yield q(a, RDF_TYPE, C_AGENT)
            yield q(a, FOAF_NAME, Literal(name))
            yield q(m, PROV_ASSOCIATED, a)

    # Topics
    for i, t in enumerate(summary.get("topics") or []):
        node = NamedNode(f"{meeting_iri(mid)}/topic/{i}")
        yield q(node, RDF_TYPE, C_TOPIC)
        topic_name = (t.get("topic") or "").strip()
        if topic_name:
            yield q(node, SKOS_PREFLABEL, Literal(topic_name))
            yield q(node, RDFS_LABEL, Literal(topic_name))
        for p in t.get("points") or []:
            if p:
                yield q(node, P_POINT, Literal(p))
        attr = agent_for(t.get("attribution"))
        if attr is not None:
            yield q(attr, RDF_TYPE, C_AGENT)
            yield q(attr, FOAF_NAME, Literal(t["attribution"]))
            yield q(node, PROV_ATTRIBUTED, attr)
        yield q(m, P_HAS_TOPIC, node)

    # Decisions
    for i, d in enumerate(summary.get("decisions") or []):
        node = NamedNode(f"{meeting_iri(mid)}/decision/{i}")
        yield q(node, RDF_TYPE, C_DECISION)
        yield q(node, P_DECISION_TEXT, Literal(d))
        yield q(node, RDFS_LABEL, Literal(d))
        yield q(m, P_HAS_DECISION, node)

    # Open questions
    for i, oq in enumerate(summary.get("open_questions") or []):
        node = NamedNode(f"{meeting_iri(mid)}/question/{i}")
        yield q(node, RDF_TYPE, C_QUESTION)
        yield q(node, P_QUESTION_TEXT, Literal(oq))
        yield q(node, RDFS_LABEL, Literal(oq))
        yield q(m, P_HAS_QUESTION, node)

    # Action items
    for i, a in enumerate(summary.get("action_items") or []):
        node = NamedNode(f"{meeting_iri(mid)}/action/{i}")
        yield q(node, RDF_TYPE, C_ACTION)
        item = a.get("item") or ""
        yield q(node, P_ACTION_TEXT, Literal(item))
        yield q(node, RDFS_LABEL, Literal(item))
        owner = agent_for(a.get("owner"))
        if owner is not None:
            yield q(owner, RDF_TYPE, C_AGENT)
            yield q(owner, FOAF_NAME, Literal(a["owner"]))
            yield q(node, SCHEMA_AGENT, owner)
        due = _dt_literal(a.get("due"))
        if due is not None:
            yield q(node, ICAL_DUE, due)
        yield q(m, P_HAS_ACTION, node)

    # Key terms -> Wikipedia / Wikidata
    for kt in summary.get("key_terms") or []:
        term = (kt.get("term") or "").strip()
        if not term:
            continue
        node = NamedNode(f"{meeting_iri(mid)}/term/{_slug(term)}")
        yield q(node, RDF_TYPE, C_KEYTERM)
        yield q(node, SKOS_PREFLABEL, Literal(term))
        yield q(node, RDFS_LABEL, Literal(term))
        if kt.get("description"):
            yield q(node, DCT_DESCRIPTION, Literal(kt["description"]))
        if kt.get("wikipedia"):
            yield q(node, RDFS_SEEALSO, NamedNode(kt["wikipedia"]))
        if kt.get("wikidata"):
            yield q(node, OWL_SAMEAS, NamedNode(kt["wikidata"]))
        yield q(m, P_HAS_KEYTERM, node)

    # Team membership (centralized, shared knowledge graph)
    team_id = rec.get("team_id")
    if team_id:
        team = NamedNode(team_iri(team_id))
        yield q(team, RDF_TYPE, C_TEAM)
        yield q(m, SCHEMA_ISPARTOF, team)

    # Previous meetings in the series
    for pid in prev_ids or []:
        yield q(m, PROV_INFORMEDBY, NamedNode(meeting_iri(pid)))

    # Cross-meeting links discovered by the agent
    for link in links or []:
        rid = link.get("related_id")
        if rid is None:
            continue
        other = NamedNode(meeting_iri(rid))
        pred = _LINK_PREDICATE.get(link.get("relation"), SKOS_RELATED)
        yield q(m, pred, other)
        yield q(m, P_RELATED_MEETING, other)  # generic link too, for easy querying


def _dump(store: Store, fmt: str, from_graph=None) -> bytes:
    rf = _FORMATS[fmt]
    buf = io.BytesIO()
    kwargs: dict = {"prefixes": PREFIXES}
    if from_graph is not None and not rf.supports_datasets:
        kwargs["from_graph"] = from_graph
    store.dump(buf, rf, **kwargs)
    return buf.getvalue()


def serialize_meeting(rec: dict, summary: dict, prev_ids=None, fmt: str = "jsonld", links=None) -> bytes:
    """Build an in-memory graph for one meeting and serialize it."""
    store = Store()
    store.extend(list(quads_for_meeting(rec, summary, prev_ids, graph=None, links=links)))
    return _dump(store, fmt, from_graph=DefaultGraph())


def serialize_corpus(records: list[dict], fmt: str = "jsonld") -> bytes:
    """Build one connected graph from many meetings and serialize it.

    Each ``record`` is a full storage row including ``summary_json``. Meetings
    are chained per user: each links to the previous meeting of the same user
    via ``prov:wasInformedBy``, so the whole series threads together.
    """
    import json as _json

    store = Store()
    prev_by_user: dict[str, object] = {}
    for rec in sorted(records, key=lambda r: r.get("id") or 0):
        raw = rec.get("summary_json") or ""
        try:
            summary = _json.loads(raw) if raw else {}
        except Exception:
            summary = {}
        user = rec.get("user") or ""
        prev = prev_by_user.get(user)
        store.extend(list(quads_for_meeting(
            rec, summary, [prev] if prev else None, graph=None, links=rec.get("links"))))
        prev_by_user[user] = rec.get("id")
    return _dump(store, fmt, from_graph=DefaultGraph())


class MeetingGraph:
    """Persistent on-disk knowledge graph; one named graph per meeting."""

    def __init__(self, path: str | None = None):
        self.store = Store(path) if path else Store()

    def ingest(self, rec: dict, summary: dict, prev_ids=None, links=None) -> None:
        g = NamedNode(meeting_iri(rec.get("id")))
        self.store.remove_graph(g)  # idempotent re-ingest (summaries get updated)
        self.store.extend(list(quads_for_meeting(rec, summary, prev_ids, graph=g, links=links)))

    def export_meeting(self, meeting_id, fmt: str = "jsonld") -> bytes:
        return _dump(self.store, fmt, from_graph=NamedNode(meeting_iri(meeting_id)))

    def export_all(self, fmt: str = "nquads") -> bytes:
        rf = _FORMATS[fmt]
        buf = io.BytesIO()
        if rf.supports_datasets:
            self.store.dump(buf, rf, prefixes=PREFIXES)
        else:
            self.store.dump(buf, rf, prefixes=PREFIXES, from_graph=DefaultGraph())
        return buf.getvalue()

    def query(self, sparql: str, union_default: bool = True):
        # Triples live in per-meeting named graphs; union-default lets a plain
        # query span the whole corpus without explicit GRAPH clauses.
        return self.store.query(sparql, use_default_graph_as_union=union_default)
