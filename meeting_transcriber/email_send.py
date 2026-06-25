"""Send meeting summaries by email (stdlib SMTP).

A small SMTP client the user configures once (host/port/credentials/security),
plus helpers to build and send a summary email to the team. Markdown is sent as
the plain-text body with an optional HTML alternative.
"""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage

_KEYS = {
    "host": "email.host", "port": "email.port", "username": "email.username",
    "password": "email.password", "from_addr": "email.from", "security": "email.security",
    "recipients": "email.recipients",
}


@dataclass
class EmailConfig:
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    from_addr: str = ""
    security: str = "starttls"  # starttls | ssl | none
    recipients: list[str] = field(default_factory=list)

    @property
    def configured(self) -> bool:
        return bool(self.host.strip())


def parse_recipients(text: str) -> list[str]:
    """Split a comma/semicolon/space/newline-separated address list."""
    import re

    return [a for a in re.split(r"[,;\s]+", (text or "").strip()) if a]


def load_config(get_setting) -> EmailConfig:
    def g(k, d=""):
        return get_setting(_KEYS[k]) or d

    try:
        port = int(g("port", "587") or "587")
    except ValueError:
        port = 587
    return EmailConfig(
        host=g("host"), port=port, username=g("username"), password=g("password"),
        from_addr=g("from_addr"), security=g("security", "starttls") or "starttls",
        recipients=parse_recipients(g("recipients")),
    )


def build_message(cfg: EmailConfig, recipients: list[str], subject: str,
                  text: str, html: str | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = cfg.from_addr or cfg.username
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(text or "")
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def send(cfg: EmailConfig, recipients: list[str], subject: str,
         text: str, html: str | None = None) -> str:
    """Send one email. Returns a short status string; raises on hard failure."""
    if not cfg.host.strip():
        raise ValueError("No SMTP host configured.")
    if not recipients:
        raise ValueError("No recipients.")
    msg = build_message(cfg, recipients, subject, text, html)
    ctx = ssl.create_default_context()
    if cfg.security == "ssl" or cfg.port == 465:
        with smtplib.SMTP_SSL(cfg.host, cfg.port, context=ctx, timeout=30) as s:
            if cfg.username:
                s.login(cfg.username, cfg.password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(cfg.host, cfg.port, timeout=30) as s:
            if cfg.security == "starttls":
                s.starttls(context=ctx)
            if cfg.username:
                s.login(cfg.username, cfg.password)
            s.send_message(msg)
    return f"Sent to {len(recipients)} recipient(s)."
