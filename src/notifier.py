"""Sends drawdown/recovery/error/heartbeat notifications by email (SMTP).

Credentials and the recipient address come from the environment (see
.env.example), never from config -- config is meant to be shareable
(config/config.example.yaml ships in the public repo), secrets aren't.
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

from src.event_format import format_event


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
    from_addr = os.environ.get("NOTIFICATION_EMAIL_FROM", username)
    to_addr = _env("NOTIFICATION_EMAIL_TO")
    if not from_addr:
        raise NotifierConfigError("NOTIFICATION_EMAIL_FROM or SMTP_USERNAME must be set")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_addr
    message["To"] = to_addr
    message.set_content(body)

    with smtplib.SMTP(host, port) as smtp:
        smtp.starttls()
        if username:
            smtp.login(username, password or "")
        smtp.send_message(message)


def notify_event(ticker: str, event: dict) -> None:
    subject = f"[Drawdown Watcher] {ticker}: {event['event']}"
    _send_email(subject, f"{ticker}\n\n{format_event(event)}")


def notify_error(ticker: str | None, message: str) -> None:
    subject = f"[Drawdown Watcher] ERROR{f' ({ticker})' if ticker else ''}"
    _send_email(subject, message)


def notify_heartbeat(status_lines: list[str]) -> None:
    subject = "[Drawdown Watcher] heartbeat"
    _send_email(subject, "\n".join(status_lines))
