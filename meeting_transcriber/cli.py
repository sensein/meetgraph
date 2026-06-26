"""Command-line entry point for MeetGraph (the ``meetgraph`` command).

Installed via the ``[project.scripts]`` entry point in pyproject.toml, so after
``pip install meetgraph`` the user gets a ``meetgraph`` command:

    meetgraph                 launch the desktop app (default)
    meetgraph gui             launch the desktop app (explicit)
    meetgraph --version       print the installed version
    meetgraph notes FILE      generate structured notes from a transcript (no GUI)

The bare ``meetgraph`` (no arguments) launches the GUI, so double-clicking or
running the command "just works" for the common case; the subcommands add a
headless path and version/help without booting Qt.
"""

from __future__ import annotations

import argparse
import sys


def _version() -> str:
    """The installed package version, or a dev placeholder when run from source."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("meetgraph")
        except PackageNotFoundError:
            return "0+unknown (not installed)"
    except Exception:
        return "0+unknown"


def _launch_gui() -> int:
    from .ui import run

    run()
    return 0


def _run_notes(args: argparse.Namespace) -> int:
    """Headless: transcript file -> structured notes (Markdown or JSON) on stdout."""
    import os

    from .agent import (
        MeetingNotesAgent,
        clean_transcript_file,
        link_key_terms,
        summary_to_markdown,
    )

    try:
        text = clean_transcript_file(args.transcript)
    except OSError as exc:
        print(f"meetgraph: cannot read transcript: {exc}", file=sys.stderr)
        return 2
    agent = MeetingNotesAgent(
        provider=args.provider,
        model_name=args.model,
        api_key=(args.api_key or os.environ.get("ANTHROPIC_API_KEY")
                 or os.environ.get("OPENAI_API_KEY")),
        base_url=args.base_url,
    )
    summary = agent.summarize(text, title=args.title)
    link_key_terms(summary)
    if args.json:
        sys.stdout.write(summary.model_dump_json(indent=2) + "\n")
    else:
        sys.stdout.write(summary_to_markdown(summary, title=args.title))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="meetgraph",
        description="MeetGraph — record & transcribe meetings, take notes, and build a "
                    "shareable knowledge graph. Run with no arguments to open the app.",
    )
    parser.add_argument("-V", "--version", action="version",
                        version=f"meetgraph {_version()}")
    sub = parser.add_subparsers(dest="command", metavar="[command]")

    sub.add_parser("gui", help="Launch the MeetGraph desktop app (default).")

    p_notes = sub.add_parser(
        "notes", help="Generate structured notes from a transcript file, no GUI.")
    p_notes.add_argument("transcript", help="Path to a transcript (.txt/.md/.vtt/.srt).")
    p_notes.add_argument("--provider", default="anthropic",
                         help="Notes LLM provider (anthropic/openai/openrouter/opensource).")
    p_notes.add_argument("--model", default=None, help="Model name (provider default if omitted).")
    p_notes.add_argument("--api-key", default=None,
                         help="API key (else uses ANTHROPIC_API_KEY / OPENAI_API_KEY).")
    p_notes.add_argument("--base-url", default=None, help="Custom API base URL (local/OpenRouter).")
    p_notes.add_argument("--title", default=None, help="Optional meeting title.")
    p_notes.add_argument("--json", action="store_true", help="Print raw JSON instead of Markdown.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "notes":
        return _run_notes(args)
    # No subcommand (or `gui`) -> launch the desktop app.
    return _launch_gui()


if __name__ == "__main__":
    raise SystemExit(main())
