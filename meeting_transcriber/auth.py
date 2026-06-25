"""Globus Auth sign-in (OAuth2 Native App flow).

Uses the Globus Native App flow: open the consent page in the browser, the user
copies back the authorization code, we exchange it for tokens and read their
identity. Register an app at https://app.globus.org/settings/developers to get a
Client ID (set ``GLOBUS_CLIENT_ID`` or paste it in the login dialog).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .storage import data_dir

SCOPES = "openid profile email"
_TOKEN_FILE = data_dir() / "globus_tokens.json"


@dataclass
class Identity:
    username: str
    name: str
    email: str
    sub: str  # stable Globus identity id

    @property
    def display(self) -> str:
        return self.name or self.username or self.email or self.sub


class GlobusAuth:
    def __init__(self, client_id: str):
        import globus_sdk

        if not client_id:
            raise ValueError("A Globus Client ID is required.")
        self._sdk = globus_sdk
        self.client = globus_sdk.NativeAppAuthClient(client_id)

    def authorize_url(self) -> str:
        self.client.oauth2_start_flow(requested_scopes=SCOPES, refresh_tokens=True)
        return self.client.oauth2_get_authorize_url()

    def exchange(self, auth_code: str) -> Identity:
        tokens = self.client.oauth2_exchange_code_for_tokens(auth_code.strip())
        self._persist(tokens)
        auth_tokens = tokens.by_resource_server["auth.globus.org"]
        authz = self._sdk.AccessTokenAuthorizer(auth_tokens["access_token"])
        ac = self._sdk.AuthClient(authorizer=authz)
        info = ac.oauth2_userinfo()
        return Identity(
            username=info.get("preferred_username", ""),
            name=info.get("name", ""),
            email=info.get("email", ""),
            sub=info.get("sub", ""),
        )

    def _persist(self, tokens) -> None:
        try:
            _TOKEN_FILE.write_text(json.dumps(tokens.by_resource_server))
            _TOKEN_FILE.chmod(0o600)
        except Exception:
            pass


def logout() -> None:
    try:
        _TOKEN_FILE.unlink(missing_ok=True)
    except Exception:
        pass
