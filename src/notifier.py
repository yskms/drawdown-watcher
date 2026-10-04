"""Sends drawdown/recovery/error/heartbeat notifications by email (SMTP).

Subjects and bodies are in Japanese -- the one reader is Japanese, and these
are the only messages the system ever sends (see src/event_format.py for why
the backtest keeps its own English formatter). The "[Drawdown Watcher]"
subject prefix stays ASCII so mail filters/labels keyed on it keep working.

Credentials and the recipient address come from the environment (see
.env.example), never from config -- config is meant to be shareable
(config/config.example.yaml ships in the public repo), secrets aren't.

Assumes STARTTLS on a plaintext-then-upgrade port (587) -- not implicit TLS
(465, SMTP_SSL). Pick an STARTTLS-capable provider/port.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

from src.event_format import event_title_ja, format_event_ja

SMTP_TIMEOUT_SECONDS = 30


class NotifierConfigError(RuntimeError):
    """A required SMTP/email environment variable is missing."""


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise NotifierConfigError(f"{name} is not set")
    return value


def _send_email(subject: str, body: str) -> None:
    host = _env("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    # `.get(key, default)` only falls back when the key is absent -- a
    # `.env` copied from .env.example leaves NOTIFICATION_EMAIL_FROM= as an
    # empty string, which *is* present, so `or` is required here to actually
    # fall back to SMTP_USERNAME.
    from_addr = os.environ.get("NOTIFICATION_EMAIL_FROM") or username
    to_addr = _env("NOTIFICATION_EMAIL_TO")
    if not from_addr:
        raise NotifierConfigError("NOTIFICATION_EMAIL_FROM or SMTP_USERNAME must be set")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_addr
    message["To"] = to_addr
    # base64, not the default 8bit: smtplib.send_message doesn't declare
    # BODY=8BITMIME, so a raw UTF-8 Japanese body would be sent as 8-bit data
    # a non-8BITMIME server may mangle. base64 is 7-bit clean everywhere.
    message.set_content(body, cte="base64")

    with smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        if username:
            smtp.login(username, password or "")
        smtp.send_message(message)


def notify_event(ticker: str, event: dict) -> None:
    title = event_title_ja(event)
    _send_email(f"[Drawdown Watcher] {ticker}: {title}", f"{ticker}: {title}\n\n{format_event_ja(event)}")


def notify_error(ticker: str | None, message: str) -> None:
    subject = f"[Drawdown Watcher] エラー{f' ({ticker})' if ticker else ''}"
    _send_email(subject, message)


def notify_heartbeat(status_lines: list[str]) -> None:
    subject = "[Drawdown Watcher] heartbeat（現在の状況）"
    # Blank line between tickers: each status is a multi-line block.
    _send_email(subject, "\n\n".join(status_lines))
