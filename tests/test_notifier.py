import ssl
from unittest.mock import patch

import pandas as pd
import pytest

from src.notifier import NotifierConfigError, notify_error, notify_event, notify_heartbeat


def _set_smtp_env(monkeypatch, **overrides):
    env = {
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": "587",
        "SMTP_USERNAME": "user@example.com",
        "SMTP_PASSWORD": "secret",
        "NOTIFICATION_EMAIL_FROM": "watcher@example.com",
        "NOTIFICATION_EMAIL_TO": "me@example.com",
    }
    env.update(overrides)
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)


@patch("src.notifier.smtplib.SMTP")
def test_notify_event_sends_email_with_ticker_and_event_details(mock_smtp, monkeypatch):
    _set_smtp_env(monkeypatch)
    smtp_instance = mock_smtp.return_value.__enter__.return_value

    event = {
        "date": pd.Timestamp("2026-03-01"),
        "event": "DRAWDOWN_MODE_ENTER",
        "close": 73.0,
        "reference_high": 100.0,
        "drawdown_pct": -27.0,
        "streak_trading_days": 2,
    }
    notify_event("SPXL", event)

    mock_smtp.assert_called_once_with("smtp.example.com", 587, timeout=30)
    smtp_instance.login.assert_called_once_with("user@example.com", "secret")
    sent = smtp_instance.send_message.call_args[0][0]
    assert sent["To"] == "me@example.com"
    assert sent["Subject"] == "[Drawdown Watcher] SPXL: 下落局面に入りました"
    body = sent.get_content()
    assert "下落局面に入りました" in body
    assert "73.00" in body and "100.00" in body and "-27.0%" in body
    assert "streak" not in body  # always 1d in production -- see event_format.py


@patch("src.notifier.smtplib.SMTP")
def test_starttls_verifies_the_server_certificate(mock_smtp, monkeypatch):
    _set_smtp_env(monkeypatch)
    smtp_instance = mock_smtp.return_value.__enter__.return_value

    notify_error(None, "boom")

    (call_context,) = smtp_instance.starttls.call_args.kwargs.values()
    assert call_context.verify_mode == ssl.CERT_REQUIRED
    assert call_context.check_hostname is True


@patch("src.notifier.smtplib.SMTP")
def test_notify_error_sends_email(mock_smtp, monkeypatch):
    _set_smtp_env(monkeypatch)
    smtp_instance = mock_smtp.return_value.__enter__.return_value

    notify_error("VOO", "fetch failed")

    sent = smtp_instance.send_message.call_args[0][0]
    assert sent["Subject"] == "[Drawdown Watcher] エラー (VOO)"
    assert "fetch failed" in sent.get_content()


@patch("src.notifier.smtplib.SMTP")
def test_notify_heartbeat_joins_status_lines(mock_smtp, monkeypatch):
    _set_smtp_env(monkeypatch)
    smtp_instance = mock_smtp.return_value.__enter__.return_value

    notify_heartbeat(["SPXL\n現在: 平常", "VOO\n現在: 平常"])

    sent = smtp_instance.send_message.call_args[0][0]
    assert "heartbeat" in sent["Subject"]
    # each ticker is a multi-line block, so blocks are separated by a blank line
    assert "SPXL\n現在: 平常\n\nVOO\n現在: 平常" in sent.get_content()


@patch("src.notifier.smtplib.SMTP")
def test_no_login_when_username_not_set(mock_smtp, monkeypatch):
    _set_smtp_env(monkeypatch, SMTP_USERNAME=None, SMTP_PASSWORD=None)
    smtp_instance = mock_smtp.return_value.__enter__.return_value

    notify_error(None, "boom")

    smtp_instance.login.assert_not_called()


def test_missing_smtp_host_raises(monkeypatch):
    _set_smtp_env(monkeypatch, SMTP_HOST=None)

    with pytest.raises(NotifierConfigError):
        notify_error(None, "boom")


def test_missing_to_address_raises(monkeypatch):
    _set_smtp_env(monkeypatch, NOTIFICATION_EMAIL_TO=None)

    with pytest.raises(NotifierConfigError):
        notify_error(None, "boom")


def test_missing_from_address_raises(monkeypatch):
    _set_smtp_env(monkeypatch, NOTIFICATION_EMAIL_FROM=None, SMTP_USERNAME=None)

    with pytest.raises(NotifierConfigError):
        notify_error(None, "boom")


@patch("src.notifier.smtplib.SMTP")
def test_empty_from_address_falls_back_to_username(mock_smtp, monkeypatch):
    # .env copied from .env.example leaves NOTIFICATION_EMAIL_FROM= as an
    # empty string, not unset -- os.environ.get(key, default) would not
    # fall back to SMTP_USERNAME in that case (the key is present).
    _set_smtp_env(monkeypatch, NOTIFICATION_EMAIL_FROM="")
    smtp_instance = mock_smtp.return_value.__enter__.return_value

    notify_error(None, "boom")

    sent = smtp_instance.send_message.call_args[0][0]
    assert sent["From"] == "user@example.com"


@patch("src.notifier.smtplib.SMTP")
def test_japanese_message_is_sent_as_7bit_safe_utf8(mock_smtp, monkeypatch):
    # smtplib.send_message doesn't declare BODY=8BITMIME, so the body must
    # not go out as raw 8-bit UTF-8 (the EmailMessage default for non-ASCII).
    _set_smtp_env(monkeypatch)
    smtp_instance = mock_smtp.return_value.__enter__.return_value

    notify_heartbeat(["SOXL\n現在: 底打ち確認済み"])

    sent = smtp_instance.send_message.call_args[0][0]
    assert sent["Content-Transfer-Encoding"] == "base64"
    assert all(byte < 128 for byte in sent.as_bytes())
    assert "現在: 底打ち確認済み" in sent.get_content()
