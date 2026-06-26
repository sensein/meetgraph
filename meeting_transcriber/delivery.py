"""Deliver meeting summary + transcript to external integrations.

Beyond email and the database, the user can push each finished meeting to:

* a **REST endpoint** (webhook) - an HTTP POST/PUT of a JSON payload with the
  summary, structured notes, and transcript; stdlib-only.
* an **MCP server** - call a tool on a Model Context Protocol server with the
  summary + transcript as arguments. Uses the optional ``mcp`` package.

Both are best-effort and configured in the app; a sink that isn't enabled or
fails just reports an error string.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

_REST_KEYS = {
    "enabled": "rest.enabled", "url": "rest.url", "method": "rest.method",
    "auth": "rest.auth", "headers": "rest.headers",
}
_MCP_KEYS = {
    "enabled": "mcp.enabled", "url": "mcp.url", "tool": "mcp.tool", "token": "mcp.token",
}


@dataclass
class RestConfig:
    enabled: bool = False
    url: str = ""
    method: str = "POST"
    auth: str = ""       # full Authorization header value, e.g. "Bearer xyz"
    headers: str = ""    # optional extra headers as a JSON object


@dataclass
class McpConfig:
    enabled: bool = False
    url: str = ""        # streamable-HTTP MCP endpoint
    tool: str = ""       # tool name to call
    token: str = ""      # optional bearer token


@dataclass
class DeliveryConfig:
    rest: RestConfig
    mcp: McpConfig


def load_config(get_setting) -> DeliveryConfig:
    def b(v):
        return (v or "0") == "1"
    rest = RestConfig(
        enabled=b(get_setting(_REST_KEYS["enabled"])),
        url=get_setting(_REST_KEYS["url"]) or "",
        method=(get_setting(_REST_KEYS["method"]) or "POST"),
        auth=get_setting(_REST_KEYS["auth"]) or "",
        headers=get_setting(_REST_KEYS["headers"]) or "",
    )
    mcp = McpConfig(
        enabled=b(get_setting(_MCP_KEYS["enabled"])),
        url=get_setting(_MCP_KEYS["url"]) or "",
        tool=get_setting(_MCP_KEYS["tool"]) or "",
        token=get_setting(_MCP_KEYS["token"]) or "",
    )
    return DeliveryConfig(rest=rest, mcp=mcp)


def payload_for(rec: dict) -> dict:
    """The JSON payload sent to integrations for one meeting."""
    try:
        summary = json.loads(rec.get("summary_json") or "") if rec.get("summary_json") else {}
    except Exception:
        summary = {}
    return {
        "meeting_id": rec.get("id"),
        "title": rec.get("title"),
        "team_id": rec.get("team_id"),
        "user": rec.get("user"),
        "started_at": rec.get("started_at"),
        "ended_at": rec.get("ended_at"),
        "summary_markdown": rec.get("summary_md"),
        "summary": summary,
        "transcript_markdown": rec.get("transcript_md"),
        "transcript_text": rec.get("transcript_plain"),
    }


# --------------------------------------------------------------------------- #
# REST webhook
# --------------------------------------------------------------------------- #
class RestSink:
    def __init__(self, cfg: RestConfig):
        if not cfg.url.strip():
            raise ValueError("No REST URL configured.")
        self.cfg = cfg

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "User-Agent": "MeetGraph"}
        if self.cfg.auth.strip():
            h["Authorization"] = self.cfg.auth.strip()
        if self.cfg.headers.strip():
            try:
                extra = json.loads(self.cfg.headers)
                if isinstance(extra, dict):
                    h.update({str(k): str(v) for k, v in extra.items()})
            except Exception:
                pass
        return h

    def send(self, payload: dict) -> str:
        data = json.dumps(payload).encode("utf-8")
        method = (self.cfg.method or "POST").upper()
        req = urllib.request.Request(self.cfg.url, data=data, headers=self._headers(), method=method)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return f"HTTP {resp.status}"

    def test(self) -> str:
        return self.send({"meetgraph": "test", "message": "MeetGraph REST connection test"})


# --------------------------------------------------------------------------- #
# MCP (Model Context Protocol) tool call
# --------------------------------------------------------------------------- #
class McpSink:
    def __init__(self, cfg: McpConfig):
        if not cfg.url.strip():
            raise ValueError("No MCP server URL configured.")
        if not cfg.tool.strip():
            raise ValueError("No MCP tool name configured.")
        self.cfg = cfg

    async def _call(self, arguments: dict) -> str:
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client
        except ImportError as exc:  # pragma: no cover - dependency hint
            raise RuntimeError(
                "MCP delivery needs the 'mcp' package. Install it with: pip install mcp"
            ) from exc
        headers = {"Authorization": f"Bearer {self.cfg.token}"} if self.cfg.token.strip() else None
        async with streamablehttp_client(self.cfg.url, headers=headers) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.call_tool(self.cfg.tool, arguments=arguments)
        return f"Called MCP tool '{self.cfg.tool}'."

    def send(self, arguments: dict) -> str:
        import asyncio

        return asyncio.run(self._call(arguments))

    def test(self) -> str:
        return self.send({"title": "MeetGraph test", "summary": "MeetGraph MCP connection test",
                          "transcript": ""})


def _mcp_arguments(rec: dict) -> dict:
    return {
        "title": rec.get("title"),
        "meeting_id": rec.get("id"),
        "team_id": rec.get("team_id"),
        "summary": rec.get("summary_md") or "",
        "transcript": rec.get("transcript_md") or "",
    }


def deliver(rec: dict, cfg: DeliveryConfig) -> dict[str, str]:
    """Send one meeting to every enabled integration. Returns {sink: 'ok' | error}."""
    results: dict[str, str] = {}
    if cfg.rest.enabled and cfg.rest.url:
        try:
            RestSink(cfg.rest).send(payload_for(rec))
            results["rest"] = "ok"
        except Exception as exc:
            results["rest"] = f"{type(exc).__name__}: {exc}"
    if cfg.mcp.enabled and cfg.mcp.url and cfg.mcp.tool:
        try:
            McpSink(cfg.mcp).send(_mcp_arguments(rec))
            results["mcp"] = "ok"
        except Exception as exc:
            results["mcp"] = f"{type(exc).__name__}: {exc}"
    return results
