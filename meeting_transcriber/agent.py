"""Pydantic AI agent that turns a transcript into faithful, structured notes.

Implements the bundled ``meeting-notes`` skill (``skills/meeting-notes/``): its
``MeetingSummary`` schema, its faithfulness rules, and its ``clean_transcript``
pre-processor. The agent is **provider-agnostic** — pick Claude (Anthropic),
OpenAI, OpenRouter, or any OpenAI-compatible open-source / local server
(Ollama, vLLM, LM Studio, …) with your own API key and base URL.

The typed output is validated against the Pydantic models below; pydantic-ai
retries the model on a validation failure (the skill's "repair" step).
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent, PromptedOutput
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider

SKILL_DIR = Path(__file__).parent / "skills"


# --------------------------------------------------------------------------- #
# Output schema — mirrors skills/meeting-notes/schemas/meeting-summary.schema.json
# --------------------------------------------------------------------------- #
class MeetingInfo(BaseModel):
    title: str | None = Field(None, description="Meeting title if stated, else null.")
    date: str | None = Field(None, description="ISO 8601 date if explicitly stated, else null.")
    participants: list[str] = Field(default_factory=list, description="Speaker names present.")
    purpose: str | None = Field(None, description="Stated purpose, else null.")


class Topic(BaseModel):
    topic: str
    points: list[str] = Field(description="Short, paraphrased factual statements. No quotes.")
    attribution: str | None = Field(
        None, description="Person whose view this topic primarily reflects, if one owns it; else null."
    )


class ActionItem(BaseModel):
    item: str
    owner: str | None = Field(None, description="Named/clearly-implied owner, else null. Never guessed.")
    due: str | None = Field(None, description="Stated deadline or trigger, else null.")


class KeyTerm(BaseModel):
    term: str = Field(
        description="A salient concept, named entity, technology, method, or organisation actually mentioned."
    )
    description: str | None = Field(
        None, description="One-line gloss from the discussion, if helpful; else null."
    )
    # Filled automatically by link_key_terms() — the model must NOT populate these.
    wikipedia: str | None = Field(None, description="Leave null; resolved automatically.")
    wikidata: str | None = Field(None, description="Leave null; resolved automatically.")


class Publication(BaseModel):
    title: str
    pmid: str | None = None
    journal: str | None = None
    year: str | None = None
    authors: str | None = None
    doi: str | None = None
    url: str | None = None
    relevance: str | None = Field(None, description="Why this paper is relevant to the discussion.")
    points: list[str] = Field(default_factory=list, description="A few key points from the paper.")


class MeetingSummary(BaseModel):
    meeting: MeetingInfo
    topics: list[Topic] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list, description="Things actually agreed/settled.")
    open_questions: list[str] = Field(default_factory=list, description="Explicitly deferred/unresolved.")
    action_items: list[ActionItem] = Field(default_factory=list)
    key_terms: list[KeyTerm] = Field(
        default_factory=list,
        description="Salient terms worth looking up — named entities, technologies, methods, organisations.",
    )
    # Filled by link_literature() for scientific discussions — not by the main pass.
    publications: list[Publication] = Field(default_factory=list)
    research_gaps: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# System prompt — the skill's mode-C instruction + its Hard rules
# --------------------------------------------------------------------------- #
SYSTEM_PROMPT = """\
You convert a meeting/call transcript into a single structured object capturing \
what was actually said and decided. Be faithful above all.

Hard rules (from the meeting-notes skill):
1. Be faithful. Include only what is in the transcript. Do not add outside facts \
or infer owners/dates that were never stated. Unknown owner/date -> null, never a guess.
2. Preserve nuance. Keep caveats and hedges intact ("considered unsettled", "their \
read, not formal advice"). Never flatten a tentative opinion into a firm fact.
3. Attribute where it matters. When a position or commitment belongs to a specific \
person, set `attribution` to that person; neutral factual recaps need no attribution.
4. Separate firm from tentative. `decisions` are things actually settled; speculation \
and deferred items are not decisions. Conditional decisions keep their condition in the text.
5. Paraphrase, don't quote. `points` are short, paraphrased, factual statements — not \
quotes, not whole paragraphs.
6. Flag the messy parts. If a thread was inconclusive or contradictory, say so in a point \
or open question rather than papering over it.
7. Organize by topic, not by clock. Group related discussion even if scattered.
8. A decision is something settled; an action item is something to be done (with an owner \
only if stated). Empty categories are empty lists, not invented content.
9. Surface key terms. List the salient terms the meeting actually mentioned and that a reader \
might want to look up: named entities, technologies, tools, methods, standards, organisations, \
domain concepts. Use the canonical name (e.g. "Kubernetes", not "k8s"). Skip generic words and \
anything not in the transcript. Leave the wikipedia/wikidata fields null — they are filled \
automatically; never invent a URL.
10. Fix transcription errors. The text comes from automatic speech-to-text and contains \
mis-recognised words, wrong homophones, dropped punctuation, and garbled proper nouns. Silently \
correct obvious errors to the word the speaker clearly meant, using surrounding context (e.g. \
"mid-graph" -> "MeetGraph", "best off" -> "best of", "Green Gria" -> the real name if recoverable). \
This is cleanup of recognition mistakes, not invention: never change the actual meaning, add facts, \
or "correct" something that was genuinely said. If a garbled term can't be confidently recovered, \
leave it out of key_terms rather than guessing."""


# --------------------------------------------------------------------------- #
# Provider abstraction
# --------------------------------------------------------------------------- #
# provider key -> (default model, default base_url or None, needs_base_url)
PROVIDERS = {
    "anthropic": ("claude-opus-4-8", None, False),
    "openai": ("gpt-4o", None, False),
    "openrouter": ("anthropic/claude-opus-4-8", "https://openrouter.ai/api/v1", False),
    "opensource": ("llama3.1", "http://localhost:11434/v1", True),  # Ollama/vLLM/LM Studio
}

PROVIDER_LABELS = {
    "anthropic": "Claude (Anthropic)",
    "openai": "OpenAI",
    "openrouter": "OpenRouter (all models)",
    "opensource": "Open-source / Custom (OpenAI-compatible)",
}

# Curated fallback lists; OpenRouter / local are fetched live (see fetch_models).
ANTHROPIC_MODELS = [
    "claude-opus-4-8", "claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5",
]
OPENAI_MODELS = [
    "gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "o3", "o4-mini",
]
OPENROUTER_FALLBACK = [
    "anthropic/claude-opus-4-8", "anthropic/claude-sonnet-4-6",
    "openai/gpt-4o", "openai/gpt-4.1", "google/gemini-2.5-pro",
    "meta-llama/llama-3.1-70b-instruct", "deepseek/deepseek-chat",
]


def default_models(provider: str) -> list[str]:
    return {
        "anthropic": ANTHROPIC_MODELS,
        "openai": OPENAI_MODELS,
        "openrouter": OPENROUTER_FALLBACK,
        "opensource": [PROVIDERS["opensource"][0]],
    }.get(provider, [])


def fetch_models(provider: str, api_key: str | None = None, base_url: str | None = None) -> list[str]:
    """Fetch the live model list for a provider's OpenAI-compatible ``/models`` endpoint.

    OpenRouter lists every model it proxies (text + multimodal/voice); local
    servers (Ollama/vLLM/LM Studio) list whatever you've pulled. Anthropic/OpenAI
    fall back to the curated lists above. Network failures return the fallback.
    """
    import json
    import urllib.request

    if provider == "anthropic":
        return ANTHROPIC_MODELS
    if provider == "openrouter":
        url = "https://openrouter.ai/api/v1/models"  # public, no key needed
    elif provider == "opensource":
        base = (base_url or PROVIDERS["opensource"][1]).rstrip("/")
        url = f"{base}/models"
    elif provider == "openai":
        base = (base_url or "https://api.openai.com/v1").rstrip("/")
        url = f"{base}/models"
    else:
        return default_models(provider)

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "meeting-transcriber"})
        if api_key and provider in ("opensource", "openai"):
            req.add_header("Authorization", f"Bearer {api_key}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        ids = sorted(m["id"] for m in data.get("data", []) if m.get("id"))
        return ids or default_models(provider)
    except Exception:
        return default_models(provider)


def _build_model(provider: str, model_name: str, api_key: str | None, base_url: str | None):
    provider = provider or "anthropic"
    if provider == "anthropic":
        kwargs = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        return AnthropicModel(model_name, provider=AnthropicProvider(**kwargs))

    # Everything else speaks the OpenAI API: openai, openrouter, open-source/local.
    default_base = PROVIDERS.get(provider, (None, None, False))[1]
    base = base_url or default_base
    # Local servers usually accept any/blank key; default to a placeholder so the
    # OpenAI client doesn't refuse to construct.
    key = api_key or ("not-needed" if provider == "opensource" else None)
    provider_kwargs = {"api_key": key}
    if base:
        provider_kwargs["base_url"] = base
    return OpenAIChatModel(model_name, provider=OpenAIProvider(**provider_kwargs))


class MeetingNotesAgent:
    """Runs the meeting-notes skill over a transcript via any configured provider."""

    def __init__(
        self,
        provider: str = "anthropic",
        model_name: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        self.provider = provider or "anthropic"
        self.model_name = model_name or PROVIDERS.get(self.provider, ("",))[0]
        model = _build_model(self.provider, self.model_name, api_key, base_url)
        # Hosted models (Claude/OpenAI) do tool/native structured output reliably.
        # Local/open-source models are far more robust with prompted-JSON output.
        if self.provider in ("opensource", "openrouter"):
            output_type = PromptedOutput(MeetingSummary)
        else:
            output_type = MeetingSummary
        self._agent = Agent(model, output_type=output_type, system_prompt=SYSTEM_PROMPT, retries=3)

    def summarize(self, transcript_text: str, title: str | None = None) -> MeetingSummary:
        if not transcript_text.strip():
            raise ValueError("Transcript is empty.")
        header = f"Meeting title (if useful): {title}\n\n" if title else ""
        prompt = (
            f"{header}Convert the following transcript into the structured object. "
            f"Follow the hard rules exactly.\n\nTranscript:\n\n{transcript_text}"
        )
        result = self._agent.run_sync(prompt)
        return result.output


# --------------------------------------------------------------------------- #
# Transcript cleaning (uses the skill's dependency-free cleaner) + Markdown notes
# --------------------------------------------------------------------------- #
def clean_transcript_file(path: str) -> str:
    """Clean a .vtt/.srt/plain transcript using the bundled skill cleaner."""
    import importlib.util
    import sys

    script = SKILL_DIR / "scripts" / "clean_transcript.py"
    spec = importlib.util.spec_from_file_location("_clean_transcript", script)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # @dataclass needs the module registered
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    cues = mod.parse(mod.read_text(path))
    speakers = mod.detect_speakers(cues)
    mod.assign_speakers(cues, speakers)
    cues = mod.merge_turns(cues)
    return mod.render(cues)


def link_key_terms(summary: MeetingSummary) -> MeetingSummary:
    """Resolve each key term to a verified Wikipedia article + Wikidata entity.

    Mutates and returns ``summary``. Network failures leave terms unlinked.
    Cheap to call repeatedly (auto-summary): look-ups are cached and only the
    ``wikipedia`` field is refilled, so already-linked terms cost nothing.
    """
    if not summary.key_terms:
        return summary
    try:
        from .wikipedia import resolve_terms
    except Exception:
        return summary
    pending = [kt.term for kt in summary.key_terms if not kt.wikipedia]
    if not pending:
        return summary
    links = resolve_terms(pending)
    for kt in summary.key_terms:
        link = links.get(kt.term)
        if link:
            kt.wikipedia = link.wikipedia
            kt.wikidata = link.wikidata
            if not kt.description and link.description:
                kt.description = link.description
    return summary


def merge_summaries(base: MeetingSummary, add: MeetingSummary) -> MeetingSummary:
    """Merge ``add`` into ``base`` (dedup), for incremental live summarization of
    long meetings — so earlier content is never lost as new speech is summarized."""
    m, a = base.meeting, add.meeting
    m.title = m.title or a.title
    m.date = m.date or a.date
    m.purpose = m.purpose or a.purpose
    for p in a.participants:
        if p not in m.participants:
            m.participants.append(p)

    topics = {t.topic.strip().lower(): t for t in base.topics}
    for t in add.topics:
        k = t.topic.strip().lower()
        if k in topics:
            for pt in t.points:
                if pt not in topics[k].points:
                    topics[k].points.append(pt)
            topics[k].attribution = topics[k].attribution or t.attribution
        else:
            base.topics.append(t)
            topics[k] = t

    def _merge_strs(dst, src):
        seen = {x.strip().lower() for x in dst}
        for x in src:
            if x.strip().lower() not in seen:
                dst.append(x)
                seen.add(x.strip().lower())

    _merge_strs(base.decisions, add.decisions)
    _merge_strs(base.open_questions, add.open_questions)
    _merge_strs(base.research_gaps, add.research_gaps)

    items = {ai.item.strip().lower() for ai in base.action_items}
    for ai in add.action_items:
        if ai.item.strip().lower() not in items:
            base.action_items.append(ai)
            items.add(ai.item.strip().lower())

    terms = {kt.term.strip().lower() for kt in base.key_terms}
    for kt in add.key_terms:
        if kt.term.strip().lower() not in terms:
            base.key_terms.append(kt)
            terms.add(kt.term.strip().lower())
    return base


def link_literature(
    summary: MeetingSummary,
    api_key: str | None = None,
    max_results: int = 8,
    provider_cfg: dict | None = None,
) -> MeetingSummary:
    """For a scientific discussion, attach relevant PubMed publications + research gaps.

    Searches PubMed using the meeting's key terms. When a model provider is given,
    an LLM judges whether the discussion is scientific, picks the genuinely relevant
    papers (with a one-line reason), and proposes research gaps relative to the
    literature. Without a provider it simply attaches the top results. Best-effort:
    any failure leaves the summary unchanged.
    """
    terms = [kt.term for kt in summary.key_terms if kt.term]
    if not terms:
        return summary
    try:
        from . import pubmed
    except Exception:
        return summary
    articles = pubmed.search(pubmed.build_query(terms), api_key=api_key, retmax=max_results)
    if not articles:
        return summary

    pubs = [Publication(**a.to_dict()) for a in articles]
    abstracts = pubmed.fetch_abstracts([a.pmid for a in articles], api_key=api_key)

    if provider_cfg and provider_cfg.get("provider"):
        try:
            from pydantic import BaseModel, Field
            from pydantic_ai import Agent, PromptedOutput

            class _Rel(BaseModel):
                pmid: str
                relevance: str = Field(description="one short sentence on why it's relevant")
                points: list[str] = Field(
                    default_factory=list,
                    description="2-3 short key points from the paper (findings/method); keep it brief")

            class _Sci(BaseModel):
                is_scientific: bool = Field(description="Is this a scientific/research discussion?")
                relevant: list[_Rel] = Field(default_factory=list)
                gaps: list[str] = Field(default_factory=list,
                                        description="research gaps/open problems vs. the literature")

            provider = provider_cfg["provider"]
            model = _build_model(provider, provider_cfg.get("model") or None,
                                 provider_cfg.get("api_key") or None, provider_cfg.get("base_url") or None)
            output_type = PromptedOutput(_Sci) if provider in ("opensource", "openrouter") else _Sci
            agent = Agent(model, output_type=output_type, retries=2, system_prompt=(
                "You connect a meeting to the scientific literature. Decide if the discussion is "
                "scientific/research-oriented. If so, select the genuinely relevant papers from the "
                "candidates (by pmid), give a one-line reason, and 2-3 short key points from each "
                "paper's abstract (findings or method — concise, not a deep review). Also list concrete "
                "research gaps the discussion raises relative to the literature. If it is not "
                "scientific, set is_scientific=false and return empty lists. Use only the given pmids."))
            topics = "; ".join(f"{t.topic}: {', '.join(t.points[:3])}" for t in summary.topics[:8])
            cand = "\n\n".join(
                f"pmid={a.pmid} | {a.title} ({a.journal} {a.year})"
                + (f"\nAbstract: {abstracts[a.pmid][:600]}" if abstracts.get(a.pmid) else "")
                for a in articles)
            result = agent.run_sync(
                f"Discussion topics:\n{topics}\n\nKey terms: {', '.join(terms)}\n\n"
                f"Candidate papers:\n{cand}\n\nReturn the assessment.")
            sci = result.output
            # Enabling PubMed means the user wants the literature: when the model
            # finds it scientific, filter to the papers it judged relevant (with
            # points + gaps); otherwise still show the top results, just no gaps.
            if sci.is_scientific:
                rels = {r.pmid: r for r in sci.relevant}
                if rels:
                    pubs = [p for p in pubs if p.pmid in rels]
                    for p in pubs:
                        r = rels.get(p.pmid)
                        p.relevance = r.relevance if r else None
                        p.points = list(r.points) if r else []
                summary.research_gaps = list(sci.gaps)
        except Exception:
            pass  # keep the unfiltered top results

    summary.publications = pubs
    return summary


def summary_to_markdown(summary: MeetingSummary, title: str | None = None) -> str:
    """Render a MeetingSummary as readable Markdown notes (skill mode A shape)."""
    m = summary.meeting
    lines: list[str] = [f"# {title or m.title or 'Meeting Notes'}", ""]
    if m.date:
        lines += [f"*Date: {m.date}*", ""]
    if m.participants:
        lines += [f"*Participants: {', '.join(m.participants)}*", ""]
    if m.purpose:
        lines += [f"**Purpose:** {m.purpose}", ""]

    if summary.topics:
        lines += ["## Key points by topic", ""]
        for t in summary.topics:
            head = f"### {t.topic}"
            if t.attribution:
                head += f"  _(per {t.attribution})_"
            lines.append(head)
            lines += [f"- {p}" for p in t.points]
            lines.append("")

    if summary.decisions:
        lines += ["## Decisions", ""] + [f"- {d}" for d in summary.decisions] + [""]

    if summary.open_questions:
        lines += ["## Open questions", ""] + [f"- {q}" for q in summary.open_questions] + [""]

    if summary.action_items:
        lines += ["## Action items", ""]
        for a in summary.action_items:
            meta = []
            if a.owner:
                meta.append(f"owner: {a.owner}")
            if a.due:
                meta.append(f"due: {a.due}")
            suffix = f"  _({'; '.join(meta)})_" if meta else "  _(unassigned)_"
            lines.append(f"- [ ] {a.item}{suffix}")
        lines.append("")

    if summary.key_terms:
        lines += ["## Key terms", ""]
        for kt in summary.key_terms:
            label = f"[{kt.term}]({kt.wikipedia})" if kt.wikipedia else kt.term
            gloss = f" — {kt.description}" if kt.description else ""
            lines.append(f"- {label}{gloss}")
        lines.append("")

    if summary.publications:
        lines += ["## Related publications", ""]
        for p in summary.publications:
            cite = f"[{p.title}]({p.url})" if p.url else p.title
            meta = " · ".join(x for x in [p.journal, p.year] if x)
            tail = f"  _{p.relevance}_" if p.relevance else ""
            line = f"- {cite}" + (f" — {meta}" if meta else "")
            if p.authors:
                line += f". {p.authors}"
            lines.append(line + tail)
            lines += [f"  - {pt}" for pt in p.points]
        lines.append("")

    if summary.research_gaps:
        lines += ["## Research gaps", ""] + [f"- {g}" for g in summary.research_gaps] + [""]

    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _main() -> int:
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="Generate structured meeting notes from a transcript.")
    ap.add_argument("transcript", help="Path to a transcript (.txt/.md/.vtt/.srt).")
    ap.add_argument("--provider", default="anthropic", choices=list(PROVIDERS))
    ap.add_argument("--model", default=None, help="Model name (provider default if omitted).")
    ap.add_argument("--api-key", default=None, help="API key (or set the provider's env var).")
    ap.add_argument("--base-url", default=None, help="Custom API base URL (for local/OpenRouter).")
    ap.add_argument("--title", default=None)
    ap.add_argument("--json", action="store_true", help="Print JSON instead of Markdown.")
    args = ap.parse_args()

    text = clean_transcript_file(args.transcript)
    agent = MeetingNotesAgent(
        provider=args.provider,
        model_name=args.model,
        api_key=args.api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"),
        base_url=args.base_url,
    )
    summary = agent.summarize(text, title=args.title)
    link_key_terms(summary)
    if args.json:
        sys.stdout.write(summary.model_dump_json(indent=2) + "\n")
    else:
        sys.stdout.write(summary_to_markdown(summary, title=args.title))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
