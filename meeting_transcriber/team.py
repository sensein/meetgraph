"""Team sharing — a single shareable key that points a whole team at one
centralized database.

One person configures the external database(s) and generates a **team key**: a
compact, shareable string that bundles a team id + the external relational and
graph DB connection settings. Teammates paste the key to join; their app then
writes every meeting summary into the same centralized database, tagged with the
team id, so the team's knowledge graph is shared.

The key is base64url(JSON) with a short prefix. It is NOT encryption — it carries
connection details (and any credentials embedded in them), so share it only over
trusted channels, exactly like sharing a database connection string.
"""

from __future__ import annotations

import base64
import json
import secrets
from dataclasses import asdict

from .external import ExternalConfig, GraphConfig, RelationalConfig

_PREFIX = "MGTEAM1."


def new_team_id() -> str:
    return secrets.token_hex(8)


def make_team_key(team_name: str, team_id: str, external: ExternalConfig) -> str:
    """Encode a shareable team key from the team identity + external DB config."""
    payload = {
        "v": 1,
        "team": team_name or "",
        "id": team_id or new_team_id(),
        "external": {
            "relational": asdict(external.relational),
            "graph": asdict(external.graph),
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return _PREFIX + base64.urlsafe_b64encode(raw).decode("ascii")


def parse_team_key(key: str) -> dict:
    """Decode a team key -> {'team', 'id', 'external': ExternalConfig}. Raises ValueError."""
    key = (key or "").strip()
    if not key.startswith(_PREFIX):
        raise ValueError("Not a MeetGraph team key.")
    try:
        raw = base64.urlsafe_b64decode(key[len(_PREFIX):].encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Corrupt team key: {exc}") from exc

    ext = data.get("external") or {}
    rel = ext.get("relational") or {}
    g = ext.get("graph") or {}
    external = ExternalConfig(
        relational=RelationalConfig(**{k: rel[k] for k in rel if k in RelationalConfig.__dataclass_fields__}),
        graph=GraphConfig(**{k: g[k] for k in g if k in GraphConfig.__dataclass_fields__}),
    )
    return {"team": data.get("team", ""), "id": data.get("id", ""), "external": external}
