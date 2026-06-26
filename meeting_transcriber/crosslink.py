"""Automatic cross-meeting linking.

After a meeting is summarized, an agent looks across the other meetings and links
the new one to those it genuinely relates to - continuations, follow-ups, or
meetings about the same entities/topics. Links are typed and carry a one-line
reason, and they feed both the local store and the centralized knowledge graph,
so a team's meetings weave together over time.

Two stages:

1. **Candidate discovery (deterministic).** Cheap, reliable: find prior meetings
   that share a key-term Wikidata entity or a topic with the target. This bounds
   the work and never hallucinates a connection out of nothing.
2. **Labeling (agent, with fallback).** The configured notes LLM decides which
   candidates are truly related, the relation type, and why. If no model is
   available it falls back to the deterministic shared-entity links.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

RELATIONS = ("related", "follow_up", "continues", "depends_on", "supersedes")
_STOP = {"the", "of", "a", "an", "and", "to", "in", "on", "for", "is", "with", "our", "meeting", "sync"}


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) >= 4 and w not in _STOP}


@dataclass
class Digest:
    id: int
    title: str
    topics: list[str] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)
    term_qids: set[str] = field(default_factory=set)
    topic_tokens: set[str] = field(default_factory=set)


def digest_of(meeting_id: int, title: str, summary: dict) -> Digest:
    topics = [t.get("topic", "") for t in (summary.get("topics") or []) if t.get("topic")]
    terms, qids = [], set()
    for kt in (summary.get("key_terms") or []):
        if kt.get("term"):
            terms.append(kt["term"])
        wd = kt.get("wikidata")
        if wd:
            qids.add(wd.rstrip("/").rsplit("/", 1)[-1])  # Qxxxx
    toks = set()
    for t in topics:
        toks |= _tokens(t)
    return Digest(meeting_id, title or f"Meeting {meeting_id}", topics, terms, qids, toks)


def digest_from_remote(mid: int, title: str, topics: list[str], qids: list[str]) -> Digest:
    """Build a digest from a centralized-graph query row (no local key-term text)."""
    d = Digest(mid, title or f"Meeting {mid}", list(topics), [], set(qids), set())
    for t in topics:
        d.topic_tokens |= _tokens(t)
    return d


def digests_from_store(store, exclude_id: int | None = None, limit: int = 500) -> list[Digest]:
    out: list[Digest] = []
    for m in store.list_meetings(limit=limit):
        if exclude_id is not None and m.id == exclude_id:
            continue
        rec = store.get_meeting(m.id)
        if not rec:
            continue
        try:
            summary = json.loads(rec.get("summary_json") or "") if rec.get("summary_json") else {}
        except Exception:
            summary = {}
        out.append(digest_of(m.id, rec.get("title") or "", summary))
    return out


@dataclass
class Candidate:
    digest: Digest
    shared_terms: list[str]
    shared_topics: list[str]

    @property
    def score(self) -> int:
        return 2 * len(self.shared_terms) + len(self.shared_topics)


def find_candidates(target: Digest, others: list[Digest], max_candidates: int = 12) -> list[Candidate]:
    t_terms_lower = {t.lower(): t for t in target.terms}
    cands: list[Candidate] = []
    for o in others:
        # Shared key terms: by Wikidata entity, or by matching term text.
        shared_qids = target.term_qids & o.term_qids
        shared_terms = [t_terms_lower[t.lower()] for t in o.terms if t.lower() in t_terms_lower]
        if shared_qids and not shared_terms:
            shared_terms = sorted(shared_qids)  # fall back to the entity ids
        shared_topics = sorted(target.topic_tokens & o.topic_tokens)
        if shared_terms or shared_topics:
            cands.append(Candidate(o, shared_terms, shared_topics))
    cands.sort(key=lambda c: c.score, reverse=True)
    return cands[:max_candidates]


@dataclass
class Link:
    related_id: int
    relation: str
    reason: str

    def as_dict(self) -> dict:
        return {"related_id": self.related_id, "relation": self.relation, "reason": self.reason}


def deterministic_links(candidates: list[Candidate]) -> list[Link]:
    links: list[Link] = []
    for c in candidates:
        bits = []
        if c.shared_terms:
            bits.append("shares " + ", ".join(c.shared_terms[:3]))
        if c.shared_topics:
            bits.append("topic overlap: " + ", ".join(c.shared_topics[:3]))
        links.append(Link(c.digest.id, "related", "; ".join(bits) or "related content"))
    return links


# --------------------------------------------------------------------------- #
# Agent labeling (optional; falls back to deterministic links)
# --------------------------------------------------------------------------- #
def agent_links(target: Digest, candidates: list[Candidate], provider_cfg: dict | None) -> list[Link]:
    """Use the configured LLM to confirm/label links. Falls back on any failure."""
    if not candidates:
        return []
    if not provider_cfg or not provider_cfg.get("provider"):
        return deterministic_links(candidates)
    try:
        from pydantic import BaseModel, Field
        from pydantic_ai import Agent, PromptedOutput

        from .agent import _build_model

        valid_ids = {c.digest.id for c in candidates}

        class _Link(BaseModel):
            related_id: int = Field(description="id of a related meeting (must be one of the candidates)")
            relation: str = Field(description="one of: related, follow_up, continues, depends_on, supersedes")
            reason: str = Field(description="one short sentence on why they are related")

        class _LinkSet(BaseModel):
            links: list[_Link] = Field(default_factory=list)

        provider = provider_cfg["provider"]
        model = _build_model(provider, provider_cfg.get("model") or None,
                             provider_cfg.get("api_key") or None, provider_cfg.get("base_url") or None)
        output_type = PromptedOutput(_LinkSet) if provider in ("opensource", "openrouter") else _LinkSet
        agent = Agent(model, output_type=output_type, retries=2, system_prompt=(
            "You connect a new meeting to earlier ones. Only link meetings that are genuinely "
            "related (same project/thread, a follow-up, a continuation, a dependency, or one that "
            "supersedes another). Choose related_id ONLY from the given candidates. Pick the most "
            "specific relation. Keep reasons to one short sentence. If none truly relate, return an "
            "empty list — do not invent links."
        ))

        def fmt(d: Digest) -> str:
            return (f"id={d.id} | title={d.title!r} | topics={d.topics[:6]} | key_terms={d.terms[:8]}")

        prompt = (
            "New meeting:\n" + fmt(target) + "\n\nCandidate earlier meetings:\n"
            + "\n".join(fmt(c.digest) for c in candidates)
            + "\n\nReturn the genuine links."
        )
        result = agent.run_sync(prompt)
        links = [
            Link(l.related_id, l.relation if l.relation in RELATIONS else "related", l.reason)
            for l in result.output.links if l.related_id in valid_ids
        ]
        return links or deterministic_links(candidates)
    except Exception:
        return deterministic_links(candidates)


def cross_link(target: Digest, others: list[Digest], provider_cfg: dict | None = None) -> list[Link]:
    """Top-level entry: discover candidates then label them (agent or deterministic)."""
    candidates = find_candidates(target, others)
    if not candidates:
        return []
    return agent_links(target, candidates, provider_cfg)
