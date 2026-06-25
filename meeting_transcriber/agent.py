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


class MeetingSummary(BaseModel):
    meeting: MeetingInfo
    topics: list[Topic] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list, description="Things actually agreed/settled.")
    open_questions: list[str] = Field(default_factory=list, description="Explicitly deferred/unresolved.")
    action_items: list[ActionItem] = Field(default_factory=list)


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
only if stated). Empty categories are empty lists, not invented content."""


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
    if args.json:
        sys.stdout.write(summary.model_dump_json(indent=2) + "\n")
    else:
        sys.stdout.write(summary_to_markdown(summary, title=args.title))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
